from __future__ import annotations

import json
from pathlib import Path

from rs_core.common.config import load_config
from rs_core.common.io import write_jsonl
from rs_core.recsys.candidate_merge import RecallCandidate, load_semantic_index, merge_candidates, merge_for_user, semantic_candidates_for_user
from rs_core.recsys.evaluation import evaluate
from rs_core.recsys.ranking import rank_candidates
from rs_core.rsagent.decision import make_agent_decision
from rs_core.rsagent.inference_policy import ModelUnavailableError, QWEN_POLICY_TYPE, RerankPolicyResult, RerankSignal
from rs_core.workflow.hybrid_demo import _leave_one_positive_out_sequences, _ranking_case_summary, run_hybrid_demo, run_qwen_evaluation_harness


def test_merge_dedups_sources_and_excludes_seen_items():
    merged = merge_candidates(
        [
            RecallCandidate("a", "popular", 1.0),
            RecallCandidate("a", "category", 2.0),
            RecallCandidate("seen", "popular", 9.0),
        ],
        seen_items={"seen"},
    )
    assert len(merged) == 1
    assert merged[0].item_id == "a"
    assert merged[0].sources == ["popular", "category"]
    assert merged[0].source_scores == {"popular": 1.0, "category": 2.0}


def test_ranking_weights_and_tie_break_order():
    candidates = merge_candidates(
        [
            RecallCandidate("b", "popular", 1.0),
            RecallCandidate("a", "itemcf_weak", 1.0),
            RecallCandidate("c", "popular", 1.0),
        ]
    )
    result = rank_candidates("u1", candidates, {"top_k": 3, "rank_weights": {"popular": 1.0, "itemcf_weak": 3.0}})
    assert [item["parent_asin"] for item in result.items] == ["a", "b", "c"]


def test_item_feature_rerank_is_disabled_by_default():
    candidates = merge_candidates([
        RecallCandidate("multi", "semantic", 1.0),
        RecallCandidate("multi", "category", 1.0),
        RecallCandidate("single", "popular", 3.0),
    ])

    result = rank_candidates("u1", candidates, {"top_k": 2, "rank_weights": {"popular": 1.0, "semantic": 1.0, "category": 1.0}})

    assert [item["parent_asin"] for item in result.items] == ["single", "multi"]
    assert result.items[0]["feature_score"] == 0.0
    assert result.items[1]["item_features"]["multi_source"] == 1



def test_item_feature_rerank_scores_candidate_features():
    candidates = merge_candidates([
        RecallCandidate("multi", "semantic", 1.0, metadata={"feedback_boost_events": [{"type": "preferred_keyword"}]}),
        RecallCandidate("multi", "category", 1.0),
        RecallCandidate("single", "popular", 3.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "semantic": 1.0, "category": 1.0},
        "item_feature_rerank": {"enabled": True, "weights": {"multi_source": 2.0, "feedback_keyword_match_count": 1.0, "popular_only": -1.0}},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["multi", "single"]
    assert result.items[0]["feature_score"] == 3.0
    assert result.items[0]["item_features"]["multi_source"] == 1
    assert result.items[0]["item_features"]["feedback_keyword_match_count"] == 1
    assert {event["feature"] for event in result.items[0]["rerank_events"] if event["type"] == "item_feature"} == {"multi_source", "feedback_keyword_match_count"}



def test_rerank_policy_is_disabled_by_default():
    candidates = merge_candidates([
        RecallCandidate("pop", "popular", 10.0),
        RecallCandidate("sem", "semantic", 1.0),
    ])

    result = rank_candidates("u1", candidates, {"top_k": 2, "rank_weights": {"popular": 1.0, "semantic": 1.0}})

    assert [item["parent_asin"] for item in result.items] == ["pop", "sem"]


def test_rerank_policy_boosts_semantic_and_penalizes_popular_only():
    candidates = merge_candidates([
        RecallCandidate("pop", "popular", 10.0),
        RecallCandidate("sem", "semantic", 7.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "semantic": 1.0},
        "rerank_policy": {"enabled": True, "semantic_boost": 3.0, "popular_only_penalty": 1.0},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["sem", "pop"]


def test_rerank_policy_penalizes_semantic_only_candidates():
    candidates = merge_candidates([
        RecallCandidate("semantic_only", "semantic", 10.0),
        RecallCandidate("multi", "semantic", 7.0),
        RecallCandidate("multi", "category", 1.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"semantic": 1.0, "category": 1.0},
        "rerank_policy": {"enabled": True, "semantic_only_penalty": 3.0},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["multi", "semantic_only"]


def test_rerank_policy_boosts_multi_source_candidates():
    candidates = merge_candidates([
        RecallCandidate("pop", "popular", 8.0),
        RecallCandidate("multi", "semantic", 4.0),
        RecallCandidate("multi", "category", 1.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "semantic": 1.0, "category": 1.0},
        "rerank_policy": {"enabled": True, "multi_source_boost": 4.0},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["multi", "pop"]


    candidates = merge_candidates(
        [
            RecallCandidate("pop1", "popular", 10.0),
            RecallCandidate("pop2", "popular", 9.0),
            RecallCandidate("cf1", "itemcf_weak", 1.0),
        ]
    )
    config = {"top_k": 2, "topk_source_minimums": {"itemcf": 1}, "rank_weights": {"popular": 1.0, "itemcf_weak": 1.0}}
    result = rank_candidates("u1", candidates, config)
    assert [item["parent_asin"] for item in result.items] == ["pop1", "cf1"]


def test_ranking_unchanged_without_topk_source_minimums():
    candidates = merge_candidates(
        [
            RecallCandidate("pop1", "popular", 10.0),
            RecallCandidate("pop2", "popular", 9.0),
            RecallCandidate("cf1", "itemcf_weak", 1.0),
        ]
    )
    config = {"top_k": 2, "rank_weights": {"popular": 1.0, "itemcf_weak": 1.0}}
    result = rank_candidates("u1", candidates, config)
    assert [item["parent_asin"] for item in result.items] == ["pop1", "pop2"]


def test_topk_source_minimum_respects_allowed_sources():
    candidates = merge_candidates(
        [
            RecallCandidate("pop1", "popular", 10.0),
            RecallCandidate("pop2", "popular", 9.0),
            RecallCandidate("cf1", "itemcf_weak", 1.0),
        ]
    )
    config = {"top_k": 2, "topk_source_minimums": {"itemcf": 1}, "rank_weights": {"popular": 1.0, "itemcf_weak": 1.0}}
    result = rank_candidates("u1", candidates, config, allowed_sources={"popular"})
    assert [item["parent_asin"] for item in result.items] == ["pop1", "pop2"]


def test_fallback_popular_candidates_used_when_no_personal_candidates():
    sequence = {"user_id": "u1", "recent_item_sequence": [], "recent_positive_item_sequence": [], "recent_strong_positive_item_sequence": []}
    candidates, fallback_used = merge_for_user(
        sequence,
        [RecallCandidate("p1", "popular", 2.0), RecallCandidate("p2", "popular", 1.0)],
        {},
        {},
        {},
        {},
        {"popular_fallback_count": 2, "candidate_pool_size": 10},
    )
    assert fallback_used is True
    assert [candidate.item_id for candidate in candidates] == ["p1", "p2"]


def test_fallback_marked_when_personal_candidates_are_seen_items():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seen", "seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    candidates, fallback_used = merge_for_user(
        sequence,
        [RecallCandidate("p1", "popular", 2.0)],
        {"seed": [RecallCandidate("seen", "itemcf_weak", 3.0)]},
        {},
        {},
        {},
        {"popular_fallback_count": 1, "candidate_pool_size": 10},
    )
    assert fallback_used is True
    assert [candidate.item_id for candidate in candidates] == ["p1"]


def test_semantic_candidates_are_opt_in_and_ranked_by_text_overlap(tmp_path: Path):
    semantic_path = tmp_path / "semantic.jsonl"
    write_jsonl(semantic_path, [
        {"parent_asin": "seed", "title_clean": "wireless bluetooth earbuds", "main_category": "Audio", "categories_flat": ["Electronics", "Audio"]},
        {"parent_asin": "rec", "title_clean": "bluetooth wireless headphones", "main_category": "Audio", "categories_flat": ["Electronics", "Audio"]},
        {"parent_asin": "other", "title_clean": "camera tripod stand", "main_category": "Camera", "categories_flat": ["Electronics", "Camera"]},
    ])
    semantic_index = load_semantic_index(semantic_path)
    sequence = {"recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}

    assert semantic_candidates_for_user(sequence, semantic_index, {}) == []
    candidates = semantic_candidates_for_user(sequence, semantic_index, {"semantic_enabled": True, "semantic_per_user": 2})

    assert [candidate.item_id for candidate in candidates] == ["rec"]
    assert candidates[0].source == "semantic"


def test_semantic_text_fields_can_exclude_description_noise(tmp_path: Path):
    semantic_path = tmp_path / "semantic.jsonl"
    write_jsonl(semantic_path, [
        {"parent_asin": "seed", "title_clean": "wireless earbuds", "description_text": "camera cable charger"},
        {"parent_asin": "title_match", "title_clean": "wireless earbuds", "description_text": "plain"},
        {"parent_asin": "description_noise", "title_clean": "plain item", "description_text": "wireless earbuds camera cable charger"},
    ])
    full_index = load_semantic_index(semantic_path)
    title_index = load_semantic_index(semantic_path, ["title_clean"])
    sequence = {"recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}

    full = semantic_candidates_for_user(sequence, full_index, {"semantic_enabled": True, "semantic_per_user": 2})
    title_only = semantic_candidates_for_user(sequence, title_index, {"semantic_enabled": True, "semantic_per_user": 2})

    assert [candidate.item_id for candidate in full] == ["description_noise", "title_match"]
    assert [candidate.item_id for candidate in title_only] == ["title_match"]


    semantic_path = tmp_path / "semantic.jsonl"
    write_jsonl(semantic_path, [
        {"parent_asin": "seed", "title_clean": "wireless bluetooth earbuds", "main_category": "Audio", "categories_flat": ["Audio"]},
        {"parent_asin": "focused", "title_clean": "wireless bluetooth", "main_category": "Audio", "categories_flat": ["Audio"]},
        {"parent_asin": "noisy", "title_clean": "wireless bluetooth earbuds camera cable charger adapter speaker tablet laptop phone monitor", "main_category": "Audio", "categories_flat": ["Audio"]},
    ])
    semantic_index = load_semantic_index(semantic_path)
    sequence = {"recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}

    raw = semantic_candidates_for_user(sequence, semantic_index, {"semantic_enabled": True, "semantic_per_user": 2})
    normalized = semantic_candidates_for_user(sequence, semantic_index, {"semantic_enabled": True, "semantic_score_mode": "normalized", "semantic_per_user": 2})

    assert [candidate.item_id for candidate in raw] == ["noisy", "focused"]
    assert [candidate.item_id for candidate in normalized] == ["focused", "noisy"]


    semantic_path = tmp_path / "semantic.jsonl"
    write_jsonl(semantic_path, [
        {"parent_asin": "seed", "title_clean": "wireless bluetooth earbuds", "main_category": "Audio", "categories_flat": ["Electronics", "Audio"]},
        {"parent_asin": "rec", "title_clean": "bluetooth wireless headphones", "main_category": "Audio", "categories_flat": ["Electronics", "Audio"]},
    ])
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }

    candidates, fallback_used = merge_for_user(
        sequence,
        [],
        {},
        {},
        {},
        {},
        {"candidate_pool_size": 10, "semantic_enabled": True},
        load_semantic_index(semantic_path),
    )

    assert fallback_used is False
    assert [candidate.item_id for candidate in candidates] == ["rec"]
    assert candidates[0].sources == ["semantic"]


def test_candidate_source_minimum_preserves_itemcf_when_semantic_scores_dominate():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    candidates, fallback_used = merge_for_user(
        sequence,
        [],
        {"seed": [RecallCandidate("cf", "itemcf_weak", 1.0)]},
        {},
        {},
        {},
        {"candidate_pool_size": 2, "candidate_source_minimums": {"itemcf": 1, "semantic": 1}, "semantic_enabled": True},
        {
            "seed": {"parent_asin": "seed", "title_clean": "wireless bluetooth earbuds", "main_category": "Audio", "categories_flat": ["Audio"], "semantic_tokens": {"wireless", "bluetooth", "earbuds"}},
            "sem": {"parent_asin": "sem", "title_clean": "wireless bluetooth earbuds headphones", "main_category": "Audio", "categories_flat": ["Audio"], "semantic_tokens": {"wireless", "bluetooth", "earbuds", "headphones"}},
        },
    )

    assert fallback_used is False
    assert {candidate.item_id for candidate in candidates} == {"cf", "sem"}


def test_agent_decision_fields_and_limitations():
    ranking = rank_candidates("u1", merge_candidates([RecallCandidate("a", "popular", 1.0)]), {"top_k": 1})
    decision = make_agent_decision("u1", ranking, {"strategy_name": "demo"}).to_dict()
    assert decision["strategy_name"] == "demo"
    assert "LLM" in decision["limitations"][0]
    assert decision["final_items"][0]["parent_asin"] == "a"


def test_metrics_schema_with_holdout_and_ablation_fields():
    candidates = {"u1": merge_candidates([RecallCandidate("target", "popular", 1.0), RecallCandidate("other", "itemcf_weak", 2.0)])}
    rankings = {"u1": rank_candidates("u1", candidates["u1"], {"top_k": 2})}
    summary = evaluate(candidates, rankings, [{"user_id": "u1", "parent_asin": "target", "label_binary": 1}], {"top_k": 2}).to_dict()
    expected = {
        "users_evaluated",
        "candidate_count_avg",
        "recall_source_coverage",
        "topk_source_coverage",
        "source_diagnostics",
        "candidate_hit_rate_at_pool",
        "candidate_hit_users",
        "candidate_hit_source_coverage",
        "candidate_hit_rank_min",
        "candidate_hit_rank_avg",
        "candidate_hit_rank_p50",
        "candidate_hit_missed_topk_users",
        "ranked_hit_users",
        "fallback_rate",
        "hit_rate_at_k",
        "popular_only_hit_rate_at_k",
        "itemcf_only_hit_rate_at_k",
        "hybrid_hit_rate_at_k",
        "hybrid_no_itemcf_hit_rate_at_k",
        "category_diversity_avg",
        "sample_limitations",
        "evaluation_mode",
    }
    assert expected <= set(summary)
    assert summary["hit_rate_at_k"] == 1.0
    assert summary["candidate_hit_rate_at_pool"] == 1.0
    assert summary["candidate_hit_users"] == 1
    assert summary["candidate_hit_source_coverage"] == {"popular": 1}
    assert summary["candidate_hit_rank_min"] == 2
    assert summary["candidate_hit_rank_avg"] == 2.0
    assert summary["candidate_hit_rank_p50"] == 2.0
    assert summary["candidate_hit_missed_topk_users"] == 0
    assert summary["ranked_hit_users"] == 1
    assert summary["popular_only_hit_rate_at_k"] == 1.0
    assert summary["topk_source_coverage"] == {"itemcf_weak": 1, "popular": 1}


def test_candidate_hit_rank_diagnostics_when_hit_misses_topk():
    candidates = {
        "u1": merge_candidates([
            RecallCandidate("top", "popular", 10.0),
            RecallCandidate("middle", "popular", 9.0),
            RecallCandidate("target", "semantic", 1.0),
        ])
    }
    rankings = {"u1": rank_candidates("u1", candidates["u1"], {"top_k": 2, "rank_weights": {"popular": 1.0, "semantic": 1.0}})}
    summary = evaluate(
        candidates,
        rankings,
        [{"user_id": "u1", "parent_asin": "target", "label_binary": 1}],
        {"top_k": 2, "rank_weights": {"popular": 1.0, "semantic": 1.0}},
    ).to_dict()

    assert summary["candidate_hit_users"] == 1
    assert summary["ranked_hit_users"] == 0
    assert summary["candidate_hit_rank_min"] == 3
    assert summary["candidate_hit_rank_avg"] == 3.0
    assert summary["candidate_hit_rank_p50"] == 3.0
    assert summary["candidate_hit_missed_topk_users"] == 1


def test_ranking_case_summary_aggregates_missed_case_source_patterns():
    summary = _ranking_case_summary([
        {
            "target_score": 5.0,
            "target_sources": ["semantic"],
            "is_topk_hit": False,
            "items_above_target": [
                {"score": 9.0, "sources": ["semantic"]},
                {"score": 8.0, "sources": ["category", "semantic"]},
            ],
            "top_items": [
                {"score": 9.0, "sources": ["semantic"]},
                {"score": 8.0, "sources": ["category", "semantic"]},
            ],
        },
        {
            "target_score": 7.0,
            "target_sources": ["category", "popular"],
            "is_topk_hit": True,
            "items_above_target": [],
            "top_items": [{"score": 7.0, "sources": ["category", "popular"]}],
        },
    ])

    assert summary["total_hit_cases"] == 2
    assert summary["topk_hit_cases"] == 1
    assert summary["missed_topk_cases"] == 1
    assert summary["target_source_combinations"] == {"semantic": 1}
    assert summary["items_above_source_combinations"] == {"semantic": 1, "category+semantic": 1}
    assert summary["semantic_only_items_above_share"] == 0.5
    assert summary["top1_score_gap_avg"] == 4.0


def test_leave_one_positive_out_removes_heldout_from_sequences():
    sequences, holdout, stats = _leave_one_positive_out_sequences([
        {
            "user_id": "u1",
            "recent_item_sequence": ["old", "seed", "target"],
            "recent_timestamp_sequence": [1, 2, 3],
            "recent_positive_item_sequence": ["seed", "target"],
            "recent_positive_timestamp_sequence": [2, 3],
            "recent_strong_positive_item_sequence": ["target"],
            "recent_strong_positive_timestamp_sequence": [3],
            "sequence_len": 3,
            "positive_sequence_len": 2,
            "strong_positive_sequence_len": 1,
        },
        {
            "user_id": "u2",
            "recent_item_sequence": ["only"],
            "recent_positive_item_sequence": ["only"],
            "recent_strong_positive_item_sequence": [],
        },
    ])

    assert holdout == [{"user_id": "u1", "parent_asin": "target", "label_binary": 1}]
    assert stats == {
        "lopo_input_users": 2,
        "lopo_eligible_users": 1,
        "lopo_skipped_users_fewer_than_2_positives": 1,
    }
    assert len(sequences) == 1
    assert sequences[0]["recent_item_sequence"] == ["old", "seed"]
    assert sequences[0]["recent_timestamp_sequence"] == [1, 2]
    assert sequences[0]["recent_positive_item_sequence"] == ["seed"]
    assert sequences[0]["recent_positive_timestamp_sequence"] == [2]
    assert sequences[0]["recent_strong_positive_item_sequence"] == []
    assert sequences[0]["recent_strong_positive_timestamp_sequence"] == []
    assert sequences[0]["sequence_len"] == 2
    assert sequences[0]["positive_sequence_len"] == 1
    assert sequences[0]["strong_positive_sequence_len"] == 0


def test_leave_one_positive_out_removes_duplicate_heldout_from_all_sequences():
    sequences, holdout, stats = _leave_one_positive_out_sequences([
        {
            "user_id": "u1",
            "recent_item_sequence": ["target", "seed", "target", "target"],
            "recent_timestamp_sequence": [1, 2, 3, 4],
            "recent_positive_item_sequence": ["target", "seed", "target"],
            "recent_positive_timestamp_sequence": [1, 2, 4],
            "recent_strong_positive_item_sequence": ["target", "other", "target"],
            "recent_strong_positive_timestamp_sequence": [1, 3, 4],
            "sequence_len": 4,
            "positive_sequence_len": 3,
            "strong_positive_sequence_len": 3,
        }
    ])

    assert holdout == [{"user_id": "u1", "parent_asin": "target", "label_binary": 1}]
    assert stats["lopo_eligible_users"] == 1
    assert sequences[0]["recent_item_sequence"] == ["seed"]
    assert sequences[0]["recent_timestamp_sequence"] == [2]
    assert sequences[0]["recent_positive_item_sequence"] == ["seed"]
    assert sequences[0]["recent_positive_timestamp_sequence"] == [2]
    assert sequences[0]["recent_strong_positive_item_sequence"] == ["other"]
    assert sequences[0]["recent_strong_positive_timestamp_sequence"] == [3]
    assert sequences[0]["sequence_len"] == 1
    assert sequences[0]["positive_sequence_len"] == 1
    assert sequences[0]["strong_positive_sequence_len"] == 1



def test_workflow_writes_outputs_report_and_metrics(tmp_path: Path):
    clean = tmp_path / "clean"
    views = tmp_path / "views"
    out = tmp_path / "out"
    report = tmp_path / "report.md"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [
        {
            "user_id": "u1",
            "recent_item_sequence": ["seed"],
            "recent_positive_item_sequence": ["seed"],
            "recent_strong_positive_item_sequence": [],
        }
    ])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "rec", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "pop", "category": "cat", "pop_score": 2, "recent_pop_score": 1, "verified_pop_score": 1, "time_decay_pop_score": 1.0}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [{"src_item": "seed", "dst_item": "rec", "score": 3.0}])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [{"parent_asin": "seed", "main_category": "cat"}, {"parent_asin": "rec", "main_category": "cat"}])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::cat", "top_items": [{"parent_asin": "rec", "score": 1.0}]}])
    config_path = tmp_path / "config.yaml"
    config_path.write_text(json.dumps({"clean_dir": str(clean), "views_dir": str(views), "output_dir": str(out), "report_path": str(report), "top_k": 2}), encoding="utf-8")

    result = run_hybrid_demo(config_path)

    assert Path(result["recommendations_path"]).exists()
    assert Path(result["metrics_path"]).exists()
    assert Path(result["ranking_cases_path"]).exists()
    assert Path(result["ranking_case_summary_path"]).exists()
    assert report.exists()
    ranking_cases = [json.loads(line) for line in Path(result["ranking_cases_path"]).read_text(encoding="utf-8").splitlines()]
    assert ranking_cases[0]["user_id"] == "u1"
    assert ranking_cases[0]["target_item"] == "rec"
    assert ranking_cases[0]["target_rank"] == 1
    assert ranking_cases[0]["target_sources"] == ["itemcf_weak", "category"]
    assert ranking_cases[0]["target_source_scores"] == {"category": 1.0, "itemcf_weak": 3.0}
    ranking_case_summary = json.loads(Path(result["ranking_case_summary_path"]).read_text(encoding="utf-8"))
    assert ranking_case_summary["total_hit_cases"] == 1
    assert ranking_case_summary["topk_hit_cases"] == 1
    assert ranking_case_summary["missed_topk_cases"] == 0
    metrics = json.loads(Path(result["metrics_path"]).read_text(encoding="utf-8"))
    assert metrics["evaluation_mode"] == "valid_test"
    assert metrics["config_summary"]["evaluation_mode"] == "valid_test"
    assert metrics["hybrid_hit_rate_at_k"] == 1.0
    assert metrics["candidate_hit_users"] == 1
    assert metrics["candidate_hit_source_coverage"]["itemcf_weak"] == 1
    assert "topk_source_coverage" in metrics
    report_text = report.read_text(encoding="utf-8")
    assert "Metrics and Ablation" in report_text
    assert "topk_source_coverage" in report_text
    assert "Recall Bottleneck Diagnostics" in report_text
    assert "candidate_hit_source_coverage" in report_text
    assert "Ranking Case Summary" in report_text


class FakeHarnessQwenClient:
    def rerank(self, **kwargs):
        return RerankPolicyResult(
            QWEN_POLICY_TYPE,
            [RerankSignal("speaker_1", 0.4, confidence=1.0, reason="matches bluetooth audio")],
            {"raw_policy_notes": "fake harness signal"},
        )


class FailingHarnessQwenClient:
    def rerank(self, **kwargs):
        raise ModelUnavailableError("Qwen model unavailable in test")


def _write_qwen_harness_fixture(root: Path, output_name: str) -> tuple[Path, Path]:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{
        "user_id": "u1",
        "recent_item_sequence": ["seed_audio"],
        "recent_positive_item_sequence": ["seed_audio"],
        "recent_strong_positive_item_sequence": [],
    }])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5, "title_clean": "USB wall charger"}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [{"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "title_clean": "Bluetooth speaker"}])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [{"parent_asin": "speaker_1", "score": 1.0, "title_clean": "Bluetooth speaker", "category": "Audio"}]}])
    config_path = root / "config.yaml"
    config_path.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "itemcf_weak": 1.0, "category": 1.0},
    }), encoding="utf-8")
    return config_path, root / output_name


def test_qwen_evaluation_harness_writes_three_mode_comparison(tmp_path: Path):
    config_path, out = _write_qwen_harness_fixture(tmp_path, "harness")

    result = run_qwen_evaluation_harness(
        config_path,
        inference_client=FakeHarnessQwenClient(),
        feedback_text="I prefer Audio and bluetooth",
        output_dir=out,
    )

    comparison = json.loads(Path(result["comparison_path"]).read_text(encoding="utf-8"))
    assert comparison["mode_order"] == ["deterministic_baseline", "rule_feedback_rerank", "qwen_feedback_rerank"]
    assert comparison["modes"]["qwen_feedback_rerank"]["inference_policy"]["accepted_signal_count"] == 1
    assert comparison["modes"]["qwen_feedback_rerank"]["inference_policy"]["routes"] == {"qwen_local": 1}
    assert comparison["rank_delta"]["comparable_cases"] == 1
    assert comparison["rank_delta"]["target_rank_improved_count"] == 1
    assert comparison["rank_delta"]["target_rank_delta_avg"] == 1.0
    assert comparison["rank_delta"]["qwen_signal_on_target_count"] == 1
    assert comparison["rank_delta"]["qwen_signal_on_non_target_count"] == 0
    assert comparison["rank_delta"]["examples"][0]["deterministic_rank"] == 2
    assert comparison["rank_delta"]["examples"][0]["qwen_rank"] == 1
    assert comparison["rank_delta"]["examples"][0]["rank_improvement_delta"] == 1
    qwen_recs = [json.loads(line) for line in (out / "qwen_feedback_rerank" / "recommendations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert qwen_recs[0]["final_items"][0]["rerank_events"][0]["type"] == "qwen_rerank_signal"
    report_text = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Qwen Evaluation Harness Comparison" in report_text
    assert "Rank Delta Summary" in report_text
    assert "qwen_feedback_rerank" in report_text


def test_qwen_evaluation_harness_writes_fallback_comparison_without_model_dependencies(tmp_path: Path):
    config_path, out = _write_qwen_harness_fixture(tmp_path, "harness_fallback")

    result = run_qwen_evaluation_harness(
        config_path,
        inference_client=FailingHarnessQwenClient(),
        feedback_text="I prefer Audio and bluetooth",
        output_dir=out,
    )

    comparison = json.loads(Path(result["comparison_path"]).read_text(encoding="utf-8"))
    assert comparison["mode_order"] == ["deterministic_baseline", "rule_feedback_rerank", "qwen_feedback_rerank"]
    assert set(comparison["modes"]) == {"deterministic_baseline", "rule_feedback_rerank", "qwen_feedback_rerank"}
    assert "rank_delta" in comparison
    qwen_policy = comparison["modes"]["qwen_feedback_rerank"]["inference_policy"]
    assert qwen_policy["fallback_count"] == 1
    assert qwen_policy["accepted_signal_count"] == 0
    assert qwen_policy["routes"] == {"qwen_local": 1}
    assert comparison["modes"]["qwen_feedback_rerank"]["paths"]["ranking_cases_path"].endswith("ranking_hit_cases.jsonl")
    assert Path(result["comparison_path"]).exists()
    assert Path(result["report_path"]).exists()
    report_text = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "Qwen Evaluation Harness Comparison" in report_text
    assert "fallback_count" in report_text


def test_workflow_lopo_uses_train_holdout_and_excludes_target_from_seen_sequence(tmp_path: Path):
    clean = tmp_path / "clean"
    views = tmp_path / "views"
    out = tmp_path / "out"
    report = tmp_path / "report.md"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [
        {
            "user_id": "u1",
            "recent_item_sequence": ["seed", "target"],
            "recent_timestamp_sequence": [1, 2],
            "recent_positive_item_sequence": ["seed", "target"],
            "recent_positive_timestamp_sequence": [1, 2],
            "recent_strong_positive_item_sequence": [],
            "recent_strong_positive_timestamp_sequence": [],
        },
        {
            "user_id": "u2",
            "recent_item_sequence": ["only"],
            "recent_positive_item_sequence": ["only"],
            "recent_strong_positive_item_sequence": [],
        },
    ])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "pop", "category": "cat", "pop_score": 2}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [{"src_item": "seed", "dst_item": "target", "score": 3.0}])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [{"parent_asin": "seed", "main_category": "cat"}, {"parent_asin": "target", "main_category": "cat"}])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::cat", "top_items": [{"parent_asin": "target", "score": 1.0}]}])
    config_path = tmp_path / "config.yaml"
    config_path.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "output_dir": str(out),
        "report_path": str(report),
        "evaluation_mode": "leave_one_positive_out",
        "top_k": 2,
    }), encoding="utf-8")

    result = run_hybrid_demo(config_path)

    metrics = json.loads(Path(result["metrics_path"]).read_text(encoding="utf-8"))
    assert metrics["evaluation_mode"] == "leave_one_positive_out"
    assert metrics["config_summary"]["evaluation_mode"] == "leave_one_positive_out"
    assert metrics["lopo_input_users"] == 2
    assert metrics["lopo_eligible_users"] == 1
    assert metrics["lopo_skipped_users_fewer_than_2_positives"] == 1
    assert metrics["config_summary"]["lopo_input_users"] == 2
    assert metrics["config_summary"]["lopo_eligible_users"] == 1
    assert metrics["config_summary"]["lopo_skipped_users_fewer_than_2_positives"] == 1
    assert metrics["users_total"] == 1
    assert metrics["users_with_holdout"] == 1
    assert metrics["candidate_hit_users"] == 1
    assert metrics["hybrid_hit_rate_at_k"] == 1.0
    assert any("Leave-one-positive-out" in item for item in metrics["sample_limitations"])
    assert any("evaluated 1 of 2 input users" in item for item in metrics["sample_limitations"])
    recommendations = [json.loads(line) for line in Path(result["recommendations_path"]).read_text(encoding="utf-8").splitlines()]
    assert recommendations[0]["user_id"] == "u1"
    assert recommendations[0]["final_items"][0]["parent_asin"] == "target"
    report_text = report.read_text(encoding="utf-8")
    assert "leave_one_positive_out" in report_text
    assert "lopo_skipped_users_fewer_than_2_positives" in report_text
    assert "evaluated 1 of 2 input users" in report_text


def test_config_loads_json_compatible_yaml():
    config = load_config("D:/sinrotic_code/python_project/summer/RS_agent/configs/hybrid_demo_small.yaml")
    assert config["top_k"] == 5


def test_config_rejects_yaml_sequence_syntax(tmp_path: Path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text("sources:\n  - popular\n", encoding="utf-8")
    try:
        load_config(config_path)
    except ValueError as error:
        assert "supports maps and scalars only" in str(error)
    else:
        raise AssertionError("Expected unsupported YAML sequence syntax to raise ValueError")
