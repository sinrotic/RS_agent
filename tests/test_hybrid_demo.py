from __future__ import annotations

import pytest

pytestmark = [pytest.mark.experiment, pytest.mark.slow]

import hashlib
import json
from pathlib import Path

import yaml

from rs_core.common.config import load_config
from rs_core.common.io import write_jsonl
from rs_core.recsys.candidate_merge import RecallCandidate, graph_walk_seed_candidates_for_user, item_graph_candidates_for_user, load_graph_walk_seed_recall, load_item_graph_recall, load_semantic_index, load_two_tower_index, load_two_tower_seed_recall, merge_candidates, merge_for_user, semantic_candidates_for_user, two_tower_candidates_for_user, two_tower_seed_candidates_for_user
from rs_core.recsys.evaluation import build_ranking_experiment_registry_entry, build_ranking_feature_contract, build_ranking_gpu_resource_summary, build_ranking_method_registry_entry, compare_frozen_candidate_artifacts, compare_frozen_candidate_signatures, evaluate, frozen_candidate_artifact, inspect_ranking_run_artifacts, strict_ranking_promotion_status, terminal_ranking_promotion_gate
from rs_core.recsys.ranking import phase_1_25_weight_grid, rank_candidates
from rs_core.rsagent.decision import make_agent_decision
from rs_core.rsagent.inference_policy import ModelUnavailableError, QWEN_POLICY_TYPE, RerankPolicyResult, RerankSignal
from rs_core.workflow.hybrid_demo import _diagnostic_gate, _frozen_candidate_export_rows, _leave_one_positive_out_sequences, _ranking_case_summary, _ranking_stage_summary, _ranking_stage_trace_rows, _recall_registry_artifact, run_hybrid_demo, run_qwen_evaluation_harness
from rs_lab.experiments.recall.run_phase_1_18_recall_gate import _phase_1_18_gate
from rs_lab.experiments.recall.run_phase_1_19_graph_walk_seed_gate import REQUIRED_DIAGNOSTIC_FIELDS, _phase_1_19_gate
import rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation as phase_1_23_runner
from rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import VARIANTS as PHASE_1_23_VARIANTS, _status_and_drift
from rs_lab.experiments.ranking.run_phase_1_24_pool200_semantic_rescue import VARIANTS as PHASE_1_24_VARIANTS
import rs_lab.experiments.ranking.run_phase_1_25_pool200_normalized_additive as phase_1_25_runner
import rs_lab.experiments.ranking.run_phase_1_26_real_ranking_experiments as phase_1_26_runner
import rs_lab.experiments.ranking.run_phase_1_26_real_learned_gbdt_ranker as phase_1_26_learned_gbdt_runner
import rs_lab.experiments.ranking.run_phase_1_28_lightweight_learned_ranker as phase_1_28_runner
import rs_lab.experiments.ranking.run_phase_1_29_terminal_ranking_route as phase_1_29_runner
import rs_lab.experiments.ranking.run_phase_1_30_physical_ranking_pipeline as phase_1_30_runner
import rs_lab.experiments.ranking.run_phase_1_rule_ranking_champion as phase_1_rule_runner
import rs_lab.experiments.ranking.run_phase_2_shallow_learned_ranker as phase_2_runner
import rs_lab.experiments.ranking.run_phase_3_tree_ranker as phase_3_runner
import rs_lab.experiments.ranking.run_phase_4_neural_ranker as phase_4_runner
import rs_lab.experiments.ranking.run_phase_5_sequence_ranker as phase_5_runner
import rs_lab.experiments.ranking.run_phase_6_semantic_two_tower_ranker as phase_6_runner
import rs_lab.experiments.ranking.run_phase_7_8_future_online_gate as phase_7_8_runner
import scripts.data.validate_recall_registry as recall_registry_validator
from rs_lab.experiments.ranking.run_phase_1_25_pool200_normalized_additive import VARIANTS as PHASE_1_25_VARIANTS, _row_is_valid



def test_ranking_records_three_stage_score_trace_without_coarse_shrinking():
    candidates = merge_candidates([
        RecallCandidate("fine_win", "popular", 1.0),
        RecallCandidate("fine_win", "semantic", 0.0),
        RecallCandidate("coarse_win", "popular", 2.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "semantic": 1.0},
        "item_feature_rerank": {"enabled": True, "weights": {"multi_source": 2.0}},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["fine_win", "coarse_win"]
    assert len(result.items) == 2
    by_id = {item["parent_asin"]: item for item in result.items}
    assert by_id["fine_win"]["coarse_score"] == 1.0
    assert by_id["fine_win"]["fine_score"] == 3.0
    assert by_id["fine_win"]["rerank_score"] == 0.0
    assert by_id["fine_win"]["final_score"] == 3.0
    assert by_id["fine_win"]["score"] == by_id["fine_win"]["final_score"]
    assert by_id["fine_win"]["score_trace"][0]["stage"] == "coarse"
    assert by_id["fine_win"]["score_trace"][1]["stage"] == "fine"
    assert by_id["fine_win"]["score_trace"][2]["stage"] == "rerank"
    assert by_id["fine_win"]["coarse_rank"] == 2
    assert by_id["fine_win"]["final_rank"] == 1
    assert by_id["fine_win"]["rank_movement"]["coarse_to_final"] == 1
    assert "source:popular" in by_id["fine_win"]["score_trace"][0]["reason_codes"]
    assert "item_feature:multi_source" in by_id["fine_win"]["score_trace"][1]["reason_codes"]


def test_physical_stage_artifacts_preserve_scores_order_and_full_pass_through(tmp_path):
    candidates_by_user = {
        "u1": merge_candidates([
            RecallCandidate("fine_win", "popular", 1.0),
            RecallCandidate("fine_win", "semantic", 0.0),
            RecallCandidate("coarse_win", "popular", 2.0),
            RecallCandidate("tail", "popular", 0.5),
        ])
    }
    config = {
        "top_k": 2,
        "candidate_pool_size": 200,
        "rank_weights": {"popular": 1.0, "semantic": 1.0},
        "item_feature_rerank": {"enabled": True, "weights": {"multi_source": 2.0}},
    }
    expected_full = rank_candidates("u1", candidates_by_user["u1"], config, top_k=len(candidates_by_user["u1"])).items

    trace_rows = _ranking_stage_trace_rows(candidates_by_user, config)
    summary = _ranking_stage_summary(trace_rows, config, tmp_path / "ranking_stage_trace.jsonl", tmp_path / "ranking_stage_summary.json")

    assert [row["item_id"] for row in trace_rows] == [item["parent_asin"] for item in expected_full]
    assert [row["final_score"] for row in trace_rows] == [item["final_score"] for item in expected_full]
    assert [row["final_rank"] for row in trace_rows] == [item["final_rank"] for item in expected_full]
    assert len(trace_rows) == 3
    assert summary["stage_counts"] == {"coarse": 3, "fine": 3, "rerank": 3}
    assert summary["pass_through_stage_counts"] == {"coarse": 3, "fine": 3, "rerank": 3}
    assert summary["total_ranked_items"] == 3
    assert summary["candidate_pool_size"] == 200
    assert summary["top_k"] == 2


def test_normalized_additive_ranking_records_component_diagnostics_and_missing_flags():
    candidates = merge_candidates([
        RecallCandidate("a", "popular", 10.0, metadata={"recent_pop_score": 2.0}),
        RecallCandidate("b", "popular", 5.0),
        RecallCandidate("c", "popular", 5.0),
        RecallCandidate("c", "semantic", 5.0),
    ])
    config = {
        "top_k": 3,
        "rank_weights": {"popular": 0.0, "semantic": 0.0},
        "normalized_additive_ranking": {"enabled": True, "weights": {"source_signal": 0.4, "freshness_quality": 0.2, "item_feature": 0.4}},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["a", "c", "b"]
    by_id = {item["parent_asin"]: item for item in result.items}
    assert by_id["a"]["score_components"]["source_signal"] == {"raw": 10.0, "normalized": 1.0, "missing": False, "weight": 0.4, "contribution": 0.4}
    assert by_id["b"]["score_components"]["freshness_quality"]["missing"] is True
    assert by_id["b"]["score_components"]["freshness_quality"]["raw"] == 0.0
    assert by_id["b"]["score_components"]["freshness_quality"]["normalized"] == 0.0
    assert by_id["c"]["score_components"]["item_feature"]["normalized"] == 1.0
    assert by_id["c"]["normalized_additive_score"] == 0.4
    assert any(event["type"] == "normalized_additive_score" for event in by_id["a"]["rerank_events"])


def test_normalized_additive_ranking_uses_zero_when_component_has_no_variance_and_records_stable_ties():
    candidates = merge_candidates([
        RecallCandidate("b", "popular", 1.0),
        RecallCandidate("a", "popular", 1.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 0.0},
        "normalized_additive_ranking": {"enabled": True, "weights": {"source_signal": 0.4}},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["a", "b"]
    assert all(item["score_components"]["source_signal"]["normalized"] == 0.0 for item in result.items)
    assert all(any(event["type"] == "stable_tie_break" for event in item["rerank_events"]) for item in result.items)


def test_phase_1_25_weight_grid_rejects_unbounded_values():
    assert len(phase_1_25_weight_grid()) == 4 * 4 * 3 * 3
    candidates = merge_candidates([RecallCandidate("a", "popular", 1.0)])

    try:
        rank_candidates("u1", candidates, {"normalized_additive_ranking": {"enabled": True, "weights": {"source_signal": 0.3}}})
    except ValueError as exc:
        assert "finite Phase 1.25 grid" in str(exc)
    else:
        raise AssertionError("unbounded additive weight was not rejected")


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


def test_source_aware_fusion_is_disabled_by_default():
    candidates = merge_candidates([
        RecallCandidate("semantic_only", "semantic", 10.0),
        RecallCandidate("itemcf", "itemcf_strong", 3.0),
    ])

    result = rank_candidates("u1", candidates, {"top_k": 2, "rank_weights": {"semantic": 1.0, "itemcf_strong": 1.0}})

    assert [item["parent_asin"] for item in result.items] == ["semantic_only", "itemcf"]
    assert all(event["type"] != "source_aware_fusion" for item in result.items for event in item["rerank_events"])


def test_source_aware_fusion_protects_itemcf_against_semantic_only():
    candidates = merge_candidates([
        RecallCandidate("semantic_only", "semantic", 10.0),
        RecallCandidate("itemcf", "itemcf_strong", 8.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"semantic": 1.0, "itemcf_strong": 1.0},
        "source_aware_fusion": {"enabled": True, "itemcf_source_boost": 3.0, "semantic_only_penalty": 1.0},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["itemcf", "semantic_only"]
    assert {event["feature"] for event in result.items[0]["rerank_events"] if event["type"] == "source_aware_fusion"} == {"itemcf_source"}
    assert {event["feature"] for event in result.items[1]["rerank_events"] if event["type"] == "source_aware_fusion"} == {"semantic_only"}


def test_source_aware_fusion_boosts_itemcf_multi_source_candidates():
    candidates = merge_candidates([
        RecallCandidate("itemcf_single", "itemcf_weak", 5.0),
        RecallCandidate("itemcf_multi", "itemcf_weak", 5.0),
        RecallCandidate("itemcf_multi", "semantic", 0.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"itemcf_weak": 1.0, "semantic": 1.0},
        "source_aware_fusion": {"enabled": True, "itemcf_source_boost": 1.0, "itemcf_multi_source_boost": 2.0},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["itemcf_multi", "itemcf_single"]
    assert {event["feature"] for event in result.items[0]["rerank_events"] if event["type"] == "source_aware_fusion"} == {"itemcf_source", "itemcf_multi_source"}


def test_source_aware_fusion_boosts_two_tower_multi_source_candidates():
    candidates = merge_candidates([
        RecallCandidate("two_tower_only", "two_tower", 10.0),
        RecallCandidate("two_tower_itemcf", "two_tower", 8.0),
        RecallCandidate("two_tower_itemcf", "itemcf_strong", 0.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"two_tower": 1.0, "itemcf_strong": 1.0},
        "source_aware_fusion": {"enabled": True, "two_tower_multi_source_boost": 1.0, "two_tower_itemcf_source_boost": 2.0, "two_tower_only_penalty": 1.0},
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["two_tower_itemcf", "two_tower_only"]
    assert result.items[0]["item_features"]["two_tower_itemcf_source"] == 1
    assert {event["feature"] for event in result.items[0]["rerank_events"] if event["type"] == "source_aware_fusion"} == {"two_tower_multi_source", "two_tower_itemcf_source"}
    assert [event for event in result.items[1]["rerank_events"] if event["feature"] == "two_tower_only"] == [{"type": "source_aware_fusion", "feature": "two_tower_only", "delta": -1.0}]



def test_source_aware_fusion_penalizes_semantic_only_and_popular_only():
    candidates = merge_candidates([
        RecallCandidate("semantic_only", "semantic", 10.0),
        RecallCandidate("popular_only", "popular", 9.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"semantic": 1.0, "popular": 1.0},
        "source_aware_fusion": {"enabled": True, "semantic_only_penalty": 2.0, "popular_only_penalty": 1.0},
    }

    result = rank_candidates("u1", candidates, config)

    events_by_item = {
        item["parent_asin"]: [event for event in item["rerank_events"] if event["type"] == "source_aware_fusion"]
        for item in result.items
    }
    assert events_by_item["semantic_only"] == [{"type": "source_aware_fusion", "feature": "semantic_only", "delta": -2.0}]
    assert events_by_item["popular_only"] == [{"type": "source_aware_fusion", "feature": "popular_only", "delta": -1.0}]


def test_source_aware_configs_are_isolated_from_semantic_title_baselines():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title.yaml")
    source_aware = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_source_aware.yaml")
    lopo_baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml")
    lopo_source_aware = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_source_aware.yaml")

    assert not baseline.get("source_aware_fusion", {}).get("enabled", False)
    assert not lopo_baseline.get("source_aware_fusion", {}).get("enabled", False)
    assert source_aware["source_aware_fusion"]["enabled"] is True
    assert lopo_source_aware["source_aware_fusion"]["enabled"] is True
    assert source_aware["rank_weights"] == baseline["rank_weights"]
    assert lopo_source_aware["rank_weights"] == lopo_baseline["rank_weights"]
    assert source_aware["output_dir"] != baseline["output_dir"]
    assert lopo_source_aware["output_dir"] != lopo_baseline["output_dir"]


def test_ltr_model_is_disabled_by_default():
    candidates = merge_candidates([
        RecallCandidate("popular", "popular", 10.0),
        RecallCandidate("itemcf", "itemcf_strong", 1.0),
    ])

    result = rank_candidates("u1", candidates, {"top_k": 2, "rank_weights": {"popular": 1.0, "itemcf_strong": 1.0}})

    assert [item["parent_asin"] for item in result.items] == ["popular", "itemcf"]
    assert all(item["ltr_score"] == 0.0 for item in result.items)
    assert all(event["type"] != "ltr_model" for item in result.items for event in item["rerank_events"])


def test_ltr_model_can_rerank_candidates_with_inline_model():
    candidates = merge_candidates([
        RecallCandidate("popular", "popular", 10.0),
        RecallCandidate("itemcf", "itemcf_strong", 1.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "itemcf_strong": 1.0},
        "ltr_model": {
            "enabled": True,
            "score_scale": 1.0,
            "model": {
                "model_type": "pairwise_perceptron_ltr_v1",
                "weights": {"itemcf_source": 10.0, "popular_only": -1.0},
                "bias": 0.0,
            },
        },
    }

    result = rank_candidates("u1", candidates, config)

    assert [item["parent_asin"] for item in result.items] == ["itemcf", "popular"]
    assert result.items[0]["ltr_score"] == 10.0
    assert [event for event in result.items[0]["rerank_events"] if event["type"] == "ltr_model"] == [
        {"type": "ltr_model", "model_type": "pairwise_perceptron_ltr_v1", "delta": 10.0}
    ]


def test_ranking_score_trace_records_coarse_fine_and_rerank_stages():
    candidates = merge_candidates([
        RecallCandidate("popular", "popular", 10.0),
        RecallCandidate("itemcf", "itemcf_strong", 1.0),
    ])
    config = {
        "top_k": 2,
        "rank_weights": {"popular": 1.0, "itemcf_strong": 1.0},
        "ltr_model": {
            "enabled": True,
            "score_scale": 1.0,
            "model": {
                "model_type": "pairwise_perceptron_ltr_v1",
                "weights": {"itemcf_source": 10.0, "popular_only": -1.0},
                "bias": 0.0,
            },
        },
    }

    result = rank_candidates("u1", candidates, config)
    by_id = {item["parent_asin"]: item for item in result.items}
    itemcf = by_id["itemcf"]

    assert {row["stage"] for row in itemcf["score_trace"]} == {"coarse", "fine", "rerank"}
    assert itemcf["coarse_score"] == 1.0
    assert itemcf["fine_score"] == 1.0
    assert itemcf["rerank_score"] == 10.0
    assert itemcf["final_score"] == 11.0
    assert itemcf["coarse_rank"] == 2
    assert itemcf["fine_rank"] == 2
    assert itemcf["final_rank"] == 1
    assert itemcf["rank_movement"] == {"coarse_to_fine": 0, "fine_to_final": 1, "coarse_to_final": 1}
    assert [row["rank"] for row in itemcf["score_trace"]] == [2, 2, 1]


def test_ltr_configs_are_isolated_from_semantic_title_baselines():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title.yaml")
    ltr = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_ltr.yaml")
    lopo_baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml")
    lopo_ltr = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_ltr.yaml")

    assert not baseline.get("ltr_model", {}).get("enabled", False)
    assert not lopo_baseline.get("ltr_model", {}).get("enabled", False)
    assert ltr["ltr_model"]["enabled"] is True
    assert lopo_ltr["ltr_model"]["enabled"] is True
    assert ltr["rank_weights"] == baseline["rank_weights"]
    assert lopo_ltr["rank_weights"] == lopo_baseline["rank_weights"]
    assert ltr["output_dir"] != baseline["output_dir"]
    assert lopo_ltr["output_dir"] != lopo_baseline["output_dir"]
    assert lopo_ltr["ltr_training"]["output_dir"] != lopo_ltr["output_dir"]


def test_phase_1_11_configs_are_isolated_from_semantic_title_baselines():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title.yaml")
    phase_1_11 = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_phase_1_11.yaml")
    lopo_baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml")
    lopo_phase_1_11 = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_phase_1_11.yaml")

    assert baseline.get("candidate_pool_strategy") != "balanced_source_budget"
    assert lopo_baseline.get("candidate_pool_strategy") != "balanced_source_budget"
    assert baseline.get("popular_fill_policy") != "capped_remainder"
    assert lopo_baseline.get("popular_fill_policy") != "capped_remainder"
    assert baseline.get("semantic_score_mode") != "idf_seed_aware"
    assert lopo_baseline.get("semantic_score_mode") != "idf_seed_aware"
    assert phase_1_11["candidate_pool_strategy"] == "balanced_source_budget"
    assert lopo_phase_1_11["candidate_pool_strategy"] == "balanced_source_budget"
    assert phase_1_11["popular_fill_policy"] == "capped_remainder"
    assert lopo_phase_1_11["popular_fill_policy"] == "capped_remainder"
    assert phase_1_11["semantic_score_mode"] == "idf_seed_aware"
    assert lopo_phase_1_11["semantic_score_mode"] == "idf_seed_aware"
    assert phase_1_11["ltr_model"]["enabled"] is False
    assert lopo_phase_1_11["ltr_model"]["enabled"] is False
    assert phase_1_11["rank_weights"] == baseline["rank_weights"]
    assert lopo_phase_1_11["rank_weights"] == lopo_baseline["rank_weights"]
    assert phase_1_11["output_dir"] != baseline["output_dir"]
    assert phase_1_11["report_path"] != baseline["report_path"]
    assert lopo_phase_1_11["output_dir"] != lopo_baseline["output_dir"]
    assert lopo_phase_1_11["report_path"] != lopo_baseline["report_path"]


def test_two_tower_configs_are_isolated_from_semantic_title_baselines():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title.yaml")
    two_tower = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_two_tower_poc.yaml")
    lopo_baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml")
    lopo_two_tower = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_two_tower_poc.yaml")

    assert baseline.get("two_tower_enabled") is not True
    assert lopo_baseline.get("two_tower_enabled") is not True
    assert two_tower["two_tower_enabled"] is True
    assert lopo_two_tower["two_tower_enabled"] is True
    assert two_tower["two_tower_artifact_name"] == "semantic_recall_inputs.jsonl"
    assert lopo_two_tower["two_tower_artifact_name"] == "semantic_recall_inputs.jsonl"
    assert two_tower["ltr_model"]["enabled"] is False
    assert lopo_two_tower["ltr_model"]["enabled"] is False
    assert two_tower["output_dir"] != baseline["output_dir"]
    assert two_tower["report_path"] != baseline["report_path"]
    assert lopo_two_tower["output_dir"] != lopo_baseline["output_dir"]
    assert lopo_two_tower["report_path"] != lopo_baseline["report_path"]


def test_two_tower_variant_configs_are_isolated_and_default_off():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title.yaml")
    lopo_baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml")
    config_names = [
        "hybrid_demo_electronics_10000_semantic_title_two_tower_dssm.yaml",
        "hybrid_demo_electronics_10000_lopo_semantic_title_two_tower_dssm.yaml",
        "hybrid_demo_electronics_10000_semantic_title_two_tower_youtube_dnn.yaml",
        "hybrid_demo_electronics_10000_lopo_semantic_title_two_tower_youtube_dnn.yaml",
    ]

    output_dirs = set()
    report_paths = set()
    for name in config_names:
        config = load_config(root / "configs" / name)
        baseline_config = lopo_baseline if "_lopo_" in name else baseline
        assert baseline_config.get("two_tower_enabled") is not True
        assert baseline_config.get("ltr_model", {}).get("enabled") is not True
        assert baseline_config.get("item_feature_rerank", {}).get("enabled") is not True
        assert baseline_config.get("source_aware_fusion", {}).get("enabled") is not True
        assert config["two_tower_enabled"] is True
        assert config["two_tower_artifact_path"].endswith("artifact_manifest.json")
        assert config.get("two_tower_artifact_name") != "semantic_recall_inputs.jsonl"
        assert config["strict_promotion_gate"]["enabled"] is True
        assert "paired_lopo_no_regression" not in config["strict_promotion_gate"]
        assert config["strict_promotion_gate"]["paired_valid_test_metrics_path"].endswith("metrics.json")
        assert config["strict_promotion_gate"]["paired_lopo_metrics_path"].endswith("metrics.json")
        assert config["ltr_model"]["enabled"] is False
        assert config.get("item_feature_rerank", {}).get("enabled") is not True
        assert config.get("source_aware_fusion", {}).get("enabled") is not True
        assert config["output_dir"] != baseline_config["output_dir"]
        assert config["report_path"] != baseline_config["report_path"]
        output_dirs.add(config["output_dir"])
        report_paths.add(config["report_path"])

    assert len(output_dirs) == len(config_names)
    assert len(report_paths) == len(config_names)


def test_phase_1_13_youtube_dnn_configs_use_isolated_outputs_and_training_artifacts():
    root = Path(__file__).resolve().parents[1]
    valid_test = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_two_tower_youtube_dnn.yaml")
    lopo = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_two_tower_youtube_dnn.yaml")

    assert valid_test["strategy_name"] == "phase_1_13_two_tower_youtube_dnn_10000_valid_test"
    assert lopo["strategy_name"] == "phase_1_13_two_tower_youtube_dnn_10000_lopo"
    for config in (valid_test, lopo):
        assert config["two_tower_enabled"] is True
        assert config["two_tower_variant"] == "youtube_dnn"
        assert config["two_tower_training"]["variant"] == "youtube_dnn"
        assert config["two_tower_training"]["source_name"] == "two_tower_youtube_dnn"
        assert config["two_tower_artifact_path"] == "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json"
        assert config["two_tower_training"]["output_dir"] == "outputs/training/two_tower/two_tower_training/youtube_dnn"
        assert config["ltr_model"]["enabled"] is False
        assert config.get("item_feature_rerank", {}).get("enabled") is not True
        assert config.get("source_aware_fusion", {}).get("enabled") is not True

    assert valid_test["output_dir"] != lopo["output_dir"]
    assert valid_test["report_path"] != lopo["report_path"]
    assert valid_test["output_dir"] != valid_test["two_tower_training"]["output_dir"]
    assert lopo["output_dir"] != lopo["two_tower_training"]["output_dir"]


def test_phase_1_14_ranking_v2_ltr_v2_configs_are_isolated_and_use_pool100_youtube_dnn():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title.yaml")
    lopo_baseline = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml")
    phase_1_13 = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_phase_1_13_two_tower_youtube_dnn_rerank_ltr.yaml")
    lopo_phase_1_13 = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_phase_1_13_two_tower_youtube_dnn_rerank_ltr.yaml")
    valid_test = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_semantic_title_phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2.yaml")
    lopo = load_config(root / "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title_phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2.yaml")

    assert baseline.get("ranking_v2", {}).get("enabled") is not True
    assert lopo_baseline.get("ranking_v2", {}).get("enabled") is not True
    assert phase_1_13.get("ranking_v2", {}).get("enabled") is not True
    assert lopo_phase_1_13.get("ranking_v2", {}).get("enabled") is not True
    for config in (valid_test, lopo):
        assert config["candidate_pool_size"] == 100
        assert config["semantic_enabled"] is True
        assert config["semantic_text_fields"] == ["title_clean", "main_category", "categories_flat"]
        assert config["two_tower_enabled"] is True
        assert config["two_tower_variant"] == "youtube_dnn"
        assert config["two_tower_artifact_path"] == "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json"
        assert config["ranking_v2"] == {
            "enabled": True,
            "feature_version": "ranking_v2",
            "preserve_candidate_pool": True,
            "weights": {
                "itemcf_semantic_source": 1.0,
                "itemcf_two_tower_source": 1.2,
                "itemcf_two_tower_semantic_source": 1.5,
                "semantic_only": -0.5,
                "popular_only": -0.5,
            },
        }
        assert config["ltr_training"]["features"] == {"version": "ltr_v2", "include_metadata": True}
        assert config["ltr_model"]["enabled"] is True
        assert config["ltr_model"]["features"] == {"version": "ltr_v2", "include_metadata": True}
        assert config["output_dir"] != config["ltr_training"]["output_dir"]
        assert config["strict_promotion_gate"]["paired_valid_test_metrics_path"].endswith("phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2/metrics.json")
        assert config["strict_promotion_gate"]["paired_lopo_metrics_path"].endswith("lopo_semantic_title_phase_1_14_pool100_youtube_dnn_ranking_v2_ltr_v2/metrics.json")

    assert valid_test.get("evaluation_mode") != "leave_one_positive_out"
    assert lopo["evaluation_mode"] == "leave_one_positive_out"
    assert valid_test["output_dir"] not in {baseline["output_dir"], phase_1_13["output_dir"], lopo["output_dir"]}
    assert lopo["output_dir"] not in {lopo_baseline["output_dir"], lopo_phase_1_13["output_dir"], valid_test["output_dir"]}
    assert valid_test["report_path"] not in {baseline["report_path"], phase_1_13["report_path"], lopo["report_path"]}
    assert lopo["report_path"] not in {lopo_baseline["report_path"], lopo_phase_1_13["report_path"], valid_test["report_path"]}


def test_phase_1_16_item_graph_configs_are_isolated_and_keep_sorting_disabled():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml")
    lopo_baseline = load_config(root / "configs/ranking/phase_1_15/phase_1_15_lopo_sanity.yaml")
    valid_test = load_config(root / "configs/recall/phase_1_16/phase_1_16_item_graph_pool100.yaml")
    lopo = load_config(root / "configs/recall/phase_1_16/phase_1_16_lopo_item_graph_pool100.yaml")

    assert baseline.get("item_graph_enabled") is not True
    assert lopo_baseline.get("item_graph_enabled") is not True
    for config, baseline_config in ((valid_test, baseline), (lopo, lopo_baseline)):
        assert config["candidate_pool_size"] == 100
        assert config["semantic_enabled"] is True
        assert config["two_tower_enabled"] is True
        assert config["two_tower_variant"] == "youtube_dnn"
        assert config["item_graph_enabled"] is True
        assert config["item_graph_artifact_name"] == "item_graph_recall.jsonl"
        assert config["item_graph_per_seed"] == 20
        assert config["item_graph_per_user"] == 30
        assert config["ltr_model"]["enabled"] is False
        assert config["ranking_v2"]["enabled"] is False
        assert config["item_feature_rerank"]["enabled"] is False
        assert config["source_aware_fusion"]["enabled"] is False
        assert "item_graph" not in baseline_config["rank_weights"]
        assert config["rank_weights"] == baseline_config["rank_weights"] | {"item_graph": 1.4}
        assert config["output_dir"] != baseline_config["output_dir"]
        assert config["report_path"] != baseline_config["report_path"]

    assert valid_test.get("evaluation_mode") != "leave_one_positive_out"
    assert lopo["evaluation_mode"] == "leave_one_positive_out"
    assert valid_test["output_dir"] != lopo["output_dir"]
    assert valid_test["report_path"] != lopo["report_path"]



def test_phase_1_17_rank_weight_configs_are_isolated_from_frozen_baseline():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml")
    configs = sorted(path for path in (root / "configs").glob("phase_1_17_rank_weight_*.yaml") if "baseline_same_run" not in path.name)
    assert len(configs) == 9

    required_same_fields = {
        "top_k",
        "candidate_pool_size",
        "popular_fallback_count",
        "candidate_source_minimums",
        "topk_source_minimums",
        "semantic_enabled",
        "semantic_per_user",
        "semantic_per_seed",
        "semantic_seed_window",
        "semantic_min_overlap",
        "semantic_text_fields",
        "two_tower_enabled",
        "two_tower_variant",
        "two_tower_artifact_path",
        "two_tower_per_user",
        "two_tower_seed_window",
        "ltr_model",
        "ranking_v2",
        "item_feature_rerank",
        "source_aware_fusion",
    }
    seen_strategy_names = set()
    seen_output_dirs = set()
    seen_report_paths = set()

    for config_path in configs:
        config = load_config(config_path)
        changed_top_level_fields = {key for key in baseline.keys() | config.keys() if baseline.get(key) != config.get(key)}
        assert changed_top_level_fields == {"rank_weights", "strategy_name", "output_dir", "report_path"}

        changed_rank_weights = {
            key for key in baseline["rank_weights"].keys() | config["rank_weights"].keys()
            if baseline["rank_weights"].get(key) != config["rank_weights"].get(key)
        }
        assert len(changed_rank_weights) == 1
        assert changed_rank_weights <= {"popular", "semantic", "two_tower"}

        for field in required_same_fields:
            assert config[field] == baseline[field]

        assert config["ltr_model"]["enabled"] is False
        assert config["ranking_v2"]["enabled"] is False
        assert config["item_feature_rerank"]["enabled"] is False
        assert config["source_aware_fusion"]["enabled"] is False
        assert config["phase_1_15_gate"]["sorting_disabled_required"] is True
        assert config["phase_1_15_gate"]["promotion_scope"] == "recall_candidate_pool_only"

        assert config["strategy_name"] not in seen_strategy_names
        assert config["output_dir"] not in seen_output_dirs
        assert config["report_path"] not in seen_report_paths
        seen_strategy_names.add(config["strategy_name"])
        seen_output_dirs.add(config["output_dir"])
        seen_report_paths.add(config["report_path"])


def test_phase_1_18_recall_gate_requires_same_run_lift_source_contribution_and_disabled_sorting():
    baseline = {
        "candidate_hit_users": 10,
        "candidate_hit_rate_at_pool": 0.1,
        "recall_at_pool": 0.05,
        "fallback_rate": 0.0,
        "latency": {"candidate_generation_p95_seconds": 0.1},
    }
    experiment = {
        "candidate_hit_users": 11,
        "candidate_hit_rate_at_pool": 0.11,
        "recall_at_pool": 0.06,
        "fallback_rate": 0.0,
        "latency": {"candidate_generation_p95_seconds": 0.2},
        "candidate_hit_source_coverage": {"two_tower_seed": 1},
    }
    config = {
        "phase_1_18_gate": {"thresholds": {"max_candidate_generation_p95_seconds": 0.543559, "min_candidate_hit_users_lift": 1}},
        "ltr_model": {"enabled": False},
        "ranking_v2": {"enabled": False},
        "item_feature_rerank": {"enabled": False},
        "source_aware_fusion": {"enabled": False},
    }

    passed = _phase_1_18_gate(baseline, experiment, config)
    no_source = _phase_1_18_gate(baseline, experiment | {"candidate_hit_source_coverage": {}}, config)
    sorting_enabled = _phase_1_18_gate(baseline, experiment, config | {"ranking_v2": {"enabled": True}})

    assert passed["passed"] is True
    assert no_source["checks"]["two_tower_seed_hit_contribution"] is False
    assert no_source["passed"] is False
    assert sorting_enabled["checks"]["sorting_disabled"] is False
    assert sorting_enabled["passed"] is False



def test_phase_1_18_two_tower_seed_configs_are_isolated_and_keep_sorting_disabled():
    root = Path(__file__).resolve().parents[1]
    baseline = load_config(root / "configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml")
    lopo_baseline = load_config(root / "configs/ranking/phase_1_15/phase_1_15_lopo_sanity.yaml")
    valid_test = load_config(root / "configs/recall/phase_1_18/phase_1_18_two_tower_seed_pool100.yaml")
    lopo = load_config(root / "configs/recall/phase_1_18/phase_1_18_lopo_two_tower_seed_pool100.yaml")

    assert baseline.get("two_tower_seed_enabled") is not True
    assert lopo_baseline.get("two_tower_seed_enabled") is not True
    for config, baseline_config in ((valid_test, baseline), (lopo, lopo_baseline)):
        assert config["candidate_pool_size"] == 100
        assert config["semantic_enabled"] is True
        assert config["two_tower_enabled"] is True
        assert config["two_tower_variant"] == "youtube_dnn"
        assert config["two_tower_artifact_path"] == "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json"
        assert config["two_tower_seed_enabled"] is True
        assert config["two_tower_seed_artifact_path"] == "outputs/training/two_tower/two_tower_training/youtube_dnn/two_tower_seed_neighbors.jsonl"
        assert config["two_tower_seed_manifest_path"] == "outputs/training/two_tower/two_tower_training/youtube_dnn/two_tower_seed_manifest.json"
        assert config["two_tower_seed_sidecar"] == {
            "embedding_input_path": "outputs/training/two_tower/two_tower_training/youtube_dnn/item_embeddings.jsonl",
            "sidecar_path": "outputs/training/two_tower/two_tower_training/youtube_dnn/two_tower_seed_neighbors.jsonl",
            "manifest_path": "outputs/training/two_tower/two_tower_training/youtube_dnn/two_tower_seed_manifest.json",
            "neighbor_k": 100,
        }
        assert config["fail_on_missing_sidecar"] is True
        assert config["ltr_model"]["enabled"] is False
        assert config["ranking_v2"]["enabled"] is False
        assert config["item_feature_rerank"]["enabled"] is False
        assert config["source_aware_fusion"]["enabled"] is False
        assert "two_tower_seed" not in baseline_config["rank_weights"]
        assert config["rank_weights"] == baseline_config["rank_weights"] | {"two_tower_seed": 1.2}
        assert config["output_dir"] != baseline_config["output_dir"]
        assert config["report_path"] != baseline_config["report_path"]
        assert config["phase_1_18_gate"]["sorting_disabled_required"] is True

    assert valid_test.get("evaluation_mode") != "leave_one_positive_out"
    assert lopo["evaluation_mode"] == "leave_one_positive_out"
    assert valid_test["phase_1_18_gate"]["promotion_scope"] == "recall_candidate_pool_only"
    assert lopo["phase_1_18_gate"]["promotion_scope"] == "sanity_only_not_promotion_evidence"
    assert valid_test["output_dir"] != lopo["output_dir"]
    assert valid_test["report_path"] != lopo["report_path"]



def test_phase_1_15_configs_match_recall_mainline_plan_and_keep_sorting_disabled():
    root = Path(__file__).resolve().parents[1]
    expected_configs = {
        "phase_1_15_frozen_youtubednn_pool100.yaml": (
            "phase_1_15_frozen_youtubednn_pool100",
            "outputs/ranking/phase_1_15_frozen_youtubednn_pool100",
            "dic/PHASE_1_15_FROZEN_YOUTUBEDNN_POOL100.md",
        ),
        "phase_1_15_valid_final_candidate.yaml": (
            "phase_1_15_valid_final_candidate",
            "outputs/ranking/phase_1_15_valid_final_candidate",
            "dic/PHASE_1_15_VALID_FINAL_CANDIDATE.md",
        ),
        "phase_1_15_test_final_candidate.yaml": (
            "phase_1_15_test_final_candidate",
            "outputs/ranking/phase_1_15_test_final_candidate",
            "dic/PHASE_1_15_TEST_FINAL_CANDIDATE.md",
        ),
        "phase_1_15_lopo_sanity.yaml": (
            "phase_1_15_lopo_sanity",
            "outputs/ranking/phase_1_15_lopo_sanity",
            "dic/PHASE_1_15_LOPO_SANITY.md",
        ),
        "phase_1_15_ablation_no_popular.yaml": (
            "phase_1_15_ablation_no_popular",
            "outputs/ranking/phase_1_15_ablation_no_popular",
            "dic/PHASE_1_15_ABLATION_NO_POPULAR.md",
        ),
        "phase_1_15_ablation_no_category.yaml": (
            "phase_1_15_ablation_no_category",
            "outputs/ranking/phase_1_15_ablation_no_category",
            "dic/PHASE_1_15_ABLATION_NO_CATEGORY.md",
        ),
        "phase_1_15_ablation_no_itemcf_weak.yaml": (
            "phase_1_15_ablation_no_itemcf_weak",
            "outputs/ranking/phase_1_15_ablation_no_itemcf_weak",
            "dic/PHASE_1_15_ABLATION_NO_ITEMCF_WEAK.md",
        ),
        "phase_1_15_ablation_no_itemcf_strong.yaml": (
            "phase_1_15_ablation_no_itemcf_strong",
            "outputs/ranking/phase_1_15_ablation_no_itemcf_strong",
            "dic/PHASE_1_15_ABLATION_NO_ITEMCF_STRONG.md",
        ),
        "phase_1_15_ablation_no_semantic.yaml": (
            "phase_1_15_ablation_no_semantic",
            "outputs/ranking/phase_1_15_ablation_no_semantic",
            "dic/PHASE_1_15_ABLATION_NO_SEMANTIC.md",
        ),
        "phase_1_15_ablation_no_two_tower.yaml": (
            "phase_1_15_ablation_no_two_tower",
            "outputs/ranking/phase_1_15_ablation_no_two_tower",
            "dic/PHASE_1_15_ABLATION_NO_TWO_TOWER.md",
        ),
        "phase_1_15_ablation_semantic_idf_budget.yaml": (
            "phase_1_15_ablation_semantic_idf_budget",
            "outputs/ranking/phase_1_15_ablation_semantic_idf_budget",
            "dic/PHASE_1_15_ABLATION_SEMANTIC_IDF_BUDGET.md",
        ),
        "phase_1_15_ablation_balanced_budget_caps.yaml": (
            "phase_1_15_ablation_balanced_budget_caps",
            "outputs/ranking/phase_1_15_ablation_balanced_budget_caps",
            "dic/PHASE_1_15_ABLATION_BALANCED_BUDGET_CAPS.md",
        ),
    }
    expected_ablation_names = {
        "no_popular",
        "no_category",
        "no_itemcf_weak",
        "no_itemcf_strong",
        "no_semantic",
        "no_two_tower",
        "semantic_idf_budget",
        "balanced_budget_caps",
    }

    strategy_names = set()
    output_dirs = set()
    report_paths = set()
    ablation_names = set()
    for name, (strategy_name, output_dir, report_path) in expected_configs.items():
        config_path = root / "configs" / name
        assert config_path.exists()
        config = load_config(config_path)
        assert config["strategy_name"] == strategy_name
        assert config["output_dir"] == output_dir
        assert config["report_path"] == report_path
        assert config["candidate_pool_size"] == 100
        assert config["ltr_model"]["enabled"] is False
        assert config["ranking_v2"]["enabled"] is False
        assert config["item_feature_rerank"]["enabled"] is False
        assert config.get("source_aware_fusion", {}).get("enabled") is False
        assert config["phase_1_15_gate"]["baseline_metrics"]
        assert config["phase_1_15_gate"]["thresholds"]
        assert config["phase_1_15_gate"]["sorting_disabled_required"] is True
        assert config["phase_1_15_gate"]["promotion_scope"] == "recall_candidate_pool_only"
        strategy_names.add(config["strategy_name"])
        output_dirs.add(config["output_dir"])
        report_paths.add(config["report_path"])
        if strategy_name.startswith("phase_1_15_ablation_"):
            ablation_names.add(strategy_name.removeprefix("phase_1_15_ablation_"))
        if name == "phase_1_15_ablation_no_two_tower.yaml":
            assert config["two_tower_enabled"] is False
        else:
            assert config["two_tower_enabled"] is True
            assert config["two_tower_variant"] == "youtube_dnn"

    lopo = load_config(root / "configs/ranking/phase_1_15/phase_1_15_lopo_sanity.yaml")
    assert lopo["evaluation_mode"] == "leave_one_positive_out"
    assert lopo["phase_1_15_lopo_gate"]["baseline_metrics"]
    assert lopo["phase_1_15_lopo_gate"]["thresholds"]
    assert lopo["phase_1_15_lopo_gate"]["promotion_scope"] == "sanity_only_not_promotion_evidence"
    assert len(strategy_names) == len(expected_configs)
    assert len(output_dirs) == len(expected_configs)
    assert len(report_paths) == len(expected_configs)
    assert ablation_names == expected_ablation_names



def test_ranking_v2_config_does_not_change_candidate_count():
    candidates = merge_candidates([
        RecallCandidate("popular", "popular", 10.0),
        RecallCandidate("semantic", "semantic", 9.0),
        RecallCandidate("multi", "semantic", 2.0),
        RecallCandidate("multi", "itemcf_strong", 2.0),
    ])
    config = {
        "top_k": 10,
        "rank_weights": {"popular": 1.0, "semantic": 1.0, "itemcf_strong": 1.0},
        "ranking_v2": {"enabled": True, "preserve_candidate_pool": True, "weights": {"semantic_itemcf_source": 10.0}},
    }

    result = rank_candidates("u1", candidates, config)

    assert {item["parent_asin"] for item in result.items} == {candidate.item_id for candidate in candidates}
    assert len(result.items) == len(candidates)


def test_two_tower_strict_gate_requires_valid_test_baseline_lopo_and_latency():
    metrics = {
        "evaluation_mode": "valid_test",
        "candidate_hit_rate_at_pool": 0.2,
        "recall_at_pool": 0.2,
        "hit_rate_at_k": 0.1,
        "candidate_hit_users": 2,
        "latency": {"candidate_generation_p95_seconds": 0.01},
        "recall_source_coverage": {"two_tower": 5},
        "per_source_candidate_contribution": {"two_tower": 1},
        "source_overlap": {"multi_source_candidate_rate": 0.2},
    }
    config = {
        "two_tower_enabled": True,
        "strict_promotion_gate": {
            "enabled": True,
            "variant": "dssm",
            "candidate_generation_p95_seconds_budget": 0.05,
            "semantic_title_baseline_metrics": {
                "candidate_hit_rate_at_pool": 0.2,
                "recall_at_pool": 0.2,
                "hit_rate_at_k": 1.0,
                "candidate_hit_users": 2,
            },
            "semantic_title_lopo_baseline_metrics": {
                "candidate_hit_rate_at_pool": 0.2,
                "recall_at_pool": 0.2,
                "hit_rate_at_k": 1.0,
                "candidate_hit_users": 2,
            },
            "paired_lopo_metrics": {
                "candidate_hit_rate_at_pool": 0.2,
                "recall_at_pool": 0.2,
                "hit_rate_at_k": 0.0,
                "candidate_hit_users": 2,
            },
        },
    }

    gate = _diagnostic_gate(metrics, config)["two_tower_strict_promotion_gate"]
    assert gate["promotable"] is True
    assert gate["decision"] == "eligible_for_manual_promotion_review"
    assert "hit_rate_at_k" not in gate["checks"]["valid_test_metrics_not_below_semantic_title_baseline"]
    assert gate["evidence"]["diagnostic_excluded_metrics"]["hit_rate_at_k"] == 0.1

    slow_metrics = metrics | {"latency": {"candidate_generation_p95_seconds": 0.1}}
    slow_gate = _diagnostic_gate(slow_metrics, config)["two_tower_strict_promotion_gate"]
    assert slow_gate["promotable"] is False
    assert slow_gate["decision"] == "default_off_side_lane_only"

    lopo_gate = _diagnostic_gate(metrics | {"evaluation_mode": "leave_one_positive_out"}, config)["two_tower_strict_promotion_gate"]
    assert lopo_gate["promotable"] is False
    assert lopo_gate["decision"] == "lopo_sanity_only_no_promotion"


def test_topk_source_minimum_forces_itemcf_candidate_into_topk():
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


def test_empty_pool_recovers_seen_popular_candidates_with_config_caps():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["p1", "p2", "p3", "seen", "seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    candidates, fallback_used = merge_for_user(
        sequence,
        [
            RecallCandidate("p1", "popular", 3.0),
            RecallCandidate("p2", "popular", 2.0),
            RecallCandidate("p3", "popular", 1.0),
        ],
        {"seed": [RecallCandidate("seen", "itemcf_weak", 4.0)]},
        {},
        {},
        {},
        {"popular_fallback_count": 3, "candidate_pool_size": 5, "top_k": 2},
    )

    assert fallback_used is True
    assert [candidate.item_id for candidate in candidates] == ["p1", "p2"]
    assert all(candidate.metadata["_internal_fallback_source"] == "popular" for candidate in candidates)


def test_normal_non_empty_pool_keeps_seen_filtering_strict():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seen_pop", "seen_cf", "seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    candidates, fallback_used = merge_for_user(
        sequence,
        [RecallCandidate("seen_pop", "popular", 10.0), RecallCandidate("fresh_pop", "popular", 1.0)],
        {"seed": [RecallCandidate("seen_cf", "itemcf_weak", 20.0), RecallCandidate("fresh_cf", "itemcf_weak", 2.0)]},
        {},
        {},
        {},
        {"popular_fallback_count": 2, "candidate_pool_size": 5, "top_k": 3},
    )

    assert fallback_used is False
    assert [candidate.item_id for candidate in candidates] == ["fresh_cf", "fresh_pop"]
    assert not any(candidate.metadata.get("_internal_fallback_source") for candidate in candidates)


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


def test_item_graph_candidates_are_default_off_and_keep_seed_metadata(tmp_path: Path):
    graph_path = tmp_path / "item_graph_recall.jsonl"
    write_jsonl(graph_path, [
        {"src_item": "strong_seed", "dst_item": "graph_rec", "score": 3.0},
        {"src_item": "positive_seed", "dst_item": "seen", "score": 4.0},
    ])
    item_graph = load_item_graph_recall(graph_path)
    sequence = {
        "recent_item_sequence": ["strong_seed", "positive_seed", "seen"],
        "recent_positive_item_sequence": ["positive_seed"],
        "recent_strong_positive_item_sequence": ["strong_seed"],
    }

    assert item_graph_candidates_for_user(sequence, item_graph, {}) == []
    raw_candidates = item_graph_candidates_for_user(
        sequence,
        item_graph,
        {"item_graph_enabled": True, "item_graph_per_seed": 2, "item_graph_per_user": 5},
    )
    merged, fallback_used = merge_for_user(
        sequence,
        [],
        {},
        {},
        {},
        {},
        {"candidate_pool_size": 5, "item_graph_enabled": True, "item_graph_per_seed": 2},
        item_graph=item_graph,
    )

    assert [candidate.item_id for candidate in raw_candidates] == ["graph_rec"]
    assert raw_candidates[0].source == "item_graph"
    assert raw_candidates[0].metadata["item_graph_seed_item"] == "strong_seed"
    assert raw_candidates[0].metadata["item_graph_score"] == 3.0
    assert fallback_used is False
    assert [candidate.item_id for candidate in merged] == ["graph_rec"]
    assert merged[0].sources == ["item_graph"]



def test_graph_walk_seed_candidates_are_default_off_source_isolated_and_filter_seen_items(tmp_path: Path):
    sidecar_path = tmp_path / "graph_walk_seed_neighbors.jsonl"
    manifest_path = tmp_path / "graph_walk_seed_manifest.json"
    rows = [
        {"src_item": "strong_seed", "dst_item": "seen", "score": 4.0, "rank": 1, "source": "graph_walk_seed", "algorithm": "deepwalk"},
        {"src_item": "strong_seed", "dst_item": "strong_rec", "score": 3.0, "rank": 2, "source": "graph_walk_seed", "algorithm": "deepwalk"},
        {"src_item": "positive_seed", "dst_item": "positive_rec", "score": 4.0, "rank": 1, "source": "graph_walk_seed", "algorithm": "deepwalk"},
    ]
    write_jsonl(sidecar_path, rows)
    manifest_path.write_text(json.dumps({
        "phase": "1.19",
        "source": "graph_walk_seed",
        "schema_version": "graph_walk_seed_pairs_v1",
        "algorithm": "deepwalk",
        "sidecar_hash": _sha256_file(sidecar_path),
    }), encoding="utf-8")
    sidecar = load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)
    sequence = {
        "recent_item_sequence": ["strong_seed", "positive_seed", "seen"],
        "recent_positive_item_sequence": ["positive_seed"],
        "recent_strong_positive_item_sequence": ["strong_seed"],
    }

    assert graph_walk_seed_candidates_for_user(sequence, sidecar, {"item_graph_enabled": True}) == []
    candidates = graph_walk_seed_candidates_for_user(
        sequence,
        sidecar,
        {
            "graph_walk_seed_enabled": True,
            "item_graph_enabled": False,
            "graph_walk_seed_per_seed": 2,
            "graph_walk_seed_per_user": 5,
            "graph_walk_seed_recency_decay": 0.5,
            "graph_walk_seed_score_floor": 1.0,
        },
    )

    assert [candidate.item_id for candidate in candidates] == ["strong_rec", "positive_rec"]
    assert all(candidate.source == "graph_walk_seed" for candidate in candidates)
    assert "seen" not in {candidate.item_id for candidate in candidates}
    assert candidates[0].metadata["graph_walk_seed_item"] == "strong_seed"
    assert candidates[0].metadata["graph_walk_seed_score"] == 3.0
    assert candidates[1].metadata["graph_walk_seed_item"] == "positive_seed"
    assert candidates[1].score == 2.0


def test_merge_for_user_preserves_graph_walk_seed_separately_from_item_graph():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["strong_seed", "positive_seed"],
        "recent_positive_item_sequence": ["positive_seed"],
        "recent_strong_positive_item_sequence": ["strong_seed"],
    }
    item_graph = {"strong_seed": [RecallCandidate("rec", "item_graph", 2.0)]}
    graph_walk_seed = {
        "strong_seed": [RecallCandidate("rec", "graph_walk_seed", 5.0), RecallCandidate("other", "graph_walk_seed", 1.0)]
    }

    disabled, disabled_fallback = merge_for_user(
        sequence,
        [],
        {"positive_seed": [RecallCandidate("cf", "itemcf_weak", 3.0)]},
        {},
        {},
        {},
        {"candidate_pool_size": 5},
        item_graph=item_graph,
        graph_walk_seed=graph_walk_seed,
    )
    candidates, fallback_used = merge_for_user(
        sequence,
        [],
        {"positive_seed": [RecallCandidate("cf", "itemcf_weak", 3.0)]},
        {},
        {},
        {},
        {"candidate_pool_size": 5, "item_graph_enabled": True, "graph_walk_seed_enabled": True, "graph_walk_seed_per_seed": 2},
        item_graph=item_graph,
        graph_walk_seed=graph_walk_seed,
    )

    assert disabled_fallback is False
    assert [(candidate.item_id, candidate.sources) for candidate in disabled] == [("cf", ["itemcf_weak"])]
    assert fallback_used is False
    assert [candidate.item_id for candidate in candidates] == ["rec", "cf", "other"]
    assert candidates[0].sources == ["item_graph", "graph_walk_seed"]
    assert candidates[0].source_scores == {"item_graph": 2.0, "graph_walk_seed": 5.0}


def test_phase_1_19_gate_requires_diagnostics_lift_source_isolation_and_disabled_sorting():
    baseline = {
        "candidate_hit_users": 10,
        "candidate_hit_rate_at_pool": 0.1,
        "recall_at_pool": 0.05,
        "fallback_rate": 0.0,
        "latency": {"candidate_generation_p95_seconds": 0.1},
    }
    experiment = {
        "candidate_hit_users": 11,
        "candidate_hit_rate_at_pool": 0.11,
        "recall_at_pool": 0.06,
        "fallback_rate": 0.0,
        "latency": {"candidate_generation_p95_seconds": 0.2},
        "candidate_hit_source_coverage": {"graph_walk_seed": 1},
    }
    diagnostics = {field: {} for field in REQUIRED_DIAGNOSTIC_FIELDS}
    diagnostics.update({
        "source_overlap": {"graph_walk_seed_with_item_graph": 0},
        "candidate_share": {"share": 0.1},
        "budget": {"users_exceeding_cap": []},
    })
    config = {
        "phase_1_19_gate": {"thresholds": {"max_candidate_generation_p95_seconds": 0.543559, "max_graph_walk_seed_candidate_share": 0.15}},
        "ltr_model": {"enabled": False},
        "ranking_v2": {"enabled": False},
        "item_feature_rerank": {"enabled": False},
        "source_aware_fusion": {"enabled": False},
    }

    passed = _phase_1_19_gate(baseline, baseline, experiment, None, config, diagnostics)
    missing_diagnostics = _phase_1_19_gate(baseline, baseline, experiment, None, config, {"budget": {}, "candidate_share": {"share": 0.1}, "source_overlap": {"graph_walk_seed_with_item_graph": 0}})
    mixed_source = _phase_1_19_gate(baseline, baseline, experiment, None, config, diagnostics | {"source_overlap": {"graph_walk_seed_with_item_graph": 1}})
    sorting_enabled = _phase_1_19_gate(baseline, baseline, experiment, None, config | {"ranking_v2": {"enabled": True}}, diagnostics)

    assert passed["passed"] is True
    assert passed["checks"]["required_diagnostics_present"] is True
    assert missing_diagnostics["checks"]["required_diagnostics_present"] is False
    assert missing_diagnostics["passed"] is False
    assert mixed_source["checks"]["source_identity_not_mixed_with_item_graph"] is False
    assert mixed_source["passed"] is False
    assert sorting_enabled["checks"]["sorting_disabled"] is False
    assert sorting_enabled["passed"] is False


def test_two_tower_seed_candidates_are_default_off_independent_and_filter_seen_items(tmp_path: Path):
    sidecar_path = tmp_path / "two_tower_seed_recall.jsonl"
    write_jsonl(sidecar_path, [
        {"item_id": "strong_seed", "neighbors": [{"item_id": "seen", "score": 4.0, "rank": 1}, {"item_id": "strong_rec", "score": 3.0, "rank": 2}]},
        {"item_id": "positive_seed", "neighbors": [{"item_id": "positive_rec", "score": 4.0, "rank": 1}, {"item_id": "low", "score": 0.1, "rank": 2}]},
    ])
    sidecar = load_two_tower_seed_recall(sidecar_path)
    sequence = {
        "recent_item_sequence": ["strong_seed", "positive_seed", "seen"],
        "recent_positive_item_sequence": ["positive_seed"],
        "recent_strong_positive_item_sequence": ["strong_seed"],
    }

    assert two_tower_seed_candidates_for_user(sequence, sidecar, {"two_tower_enabled": True}) == []
    candidates = two_tower_seed_candidates_for_user(
        sequence,
        sidecar,
        {
            "two_tower_seed_enabled": True,
            "two_tower_enabled": False,
            "two_tower_seed_per_seed": 2,
            "two_tower_seed_per_user": 5,
            "two_tower_seed_recency_decay": 0.5,
            "two_tower_seed_score_floor": 1.0,
        },
    )

    assert [candidate.item_id for candidate in candidates] == ["strong_rec", "positive_rec"]
    assert all(candidate.source == "two_tower_seed" for candidate in candidates)
    assert "seen" not in {candidate.item_id for candidate in candidates}
    assert candidates[0].metadata["two_tower_seed_item"] == "strong_seed"
    assert candidates[0].metadata["two_tower_seed_neighbor_rank"] == 2
    assert candidates[1].metadata["two_tower_seed_item"] == "positive_seed"
    assert candidates[1].metadata["two_tower_seed_neighbor_rank"] == 1
    assert candidates[1].score == 2.0


def test_merge_for_user_preserves_two_tower_seed_source_and_dedupes_best_score():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["strong_seed", "positive_seed"],
        "recent_positive_item_sequence": ["positive_seed"],
        "recent_strong_positive_item_sequence": ["strong_seed"],
    }
    two_tower_seed = {
        "strong_seed": [RecallCandidate("rec", "two_tower_seed", 2.0), RecallCandidate("other", "two_tower_seed", 1.0)],
        "positive_seed": [RecallCandidate("rec", "two_tower_seed", 5.0)],
    }

    candidates, fallback_used = merge_for_user(
        sequence,
        [],
        {"positive_seed": [RecallCandidate("rec", "itemcf_weak", 3.0)]},
        {},
        {},
        {},
        {"candidate_pool_size": 5, "two_tower_seed_enabled": True, "two_tower_seed_per_seed": 2, "two_tower_seed_per_user": 5},
        two_tower_seed=two_tower_seed,
    )

    assert fallback_used is False
    assert [candidate.item_id for candidate in candidates] == ["rec", "other"]
    assert candidates[0].sources == ["itemcf_weak", "two_tower_seed"]
    assert candidates[0].source_scores == {"itemcf_weak": 3.0, "two_tower_seed": 5.0}


def test_two_tower_candidates_are_default_off_and_exclude_seen_items(tmp_path: Path):
    two_tower_path = tmp_path / "two_tower.jsonl"
    write_jsonl(two_tower_path, [
        {"parent_asin": "seed", "title_clean": "wireless bluetooth earbuds", "main_category": "Audio"},
        {"parent_asin": "rec", "title_clean": "wireless bluetooth headphones", "main_category": "Audio"},
        {"parent_asin": "seen", "title_clean": "wireless bluetooth speaker", "main_category": "Audio"},
    ])
    two_tower_index = load_two_tower_index(two_tower_path, ["title_clean"])
    sequence = {"recent_item_sequence": ["seed", "seen"], "recent_positive_item_sequence": ["seed"]}

    assert two_tower_candidates_for_user(sequence, two_tower_index, {}) == []
    candidates = two_tower_candidates_for_user(sequence, two_tower_index, {"two_tower_enabled": True, "two_tower_per_user": 5, "two_tower_text_fields": ["title_clean"]})

    assert [candidate.item_id for candidate in candidates] == ["rec"]
    assert candidates[0].source == "two_tower"


def test_vector_two_tower_index_uses_manifest_artifacts_and_excludes_seen_items(tmp_path: Path):
    recall_index_path = tmp_path / "two_tower_recall_index.jsonl"
    user_embeddings_path = tmp_path / "user_embeddings.jsonl"
    model_path = tmp_path / "two_tower_model.json"
    manifest_path = tmp_path / "artifact_manifest.json"
    write_jsonl(recall_index_path, [
        {"parent_asin": "seen", "embedding": [1.0, 0.0], "main_category": "Audio"},
        {"parent_asin": "best", "embedding": [0.9, 0.1], "main_category": "Audio"},
        {"parent_asin": "weak", "embedding": [0.0, 1.0], "main_category": "Audio"},
    ])
    write_jsonl(user_embeddings_path, [{"user_id": "u1", "embedding": [1.0, 0.0]}])
    model_path.write_text(json.dumps({"model_type": "dssm_two_tower_v1", "variant": "dssm", "source_name": "two_tower_dssm"}), encoding="utf-8")
    manifest_path.write_text(
        json.dumps({
            "artifact_type": "two_tower_training_artifacts_v1",
            "variant": "dssm",
            "source_name": "two_tower_dssm",
            "contract": {
                "recall_index": str(recall_index_path),
                "user_embeddings": str(user_embeddings_path),
                "model": str(model_path),
            },
        }),
        encoding="utf-8",
    )
    two_tower_index = load_two_tower_index(manifest_path)
    sequence = {"user_id": "u1", "recent_item_sequence": ["seen"], "recent_positive_item_sequence": ["seen"]}

    candidates = two_tower_candidates_for_user(sequence, two_tower_index, {"two_tower_enabled": True, "two_tower_per_user": 2})

    assert [candidate.item_id for candidate in candidates] == ["best"]
    assert candidates[0].source == "two_tower"
    assert candidates[0].metadata["source_name"] == "two_tower_dssm"
    assert candidates[0].metadata["two_tower_score_mode"] == "vector_dot"


def test_vector_two_tower_index_can_fallback_to_seed_embeddings(tmp_path: Path):
    recall_index_path = tmp_path / "two_tower_recall_index.jsonl"
    write_jsonl(recall_index_path, [
        {"parent_asin": "seed", "embedding": [1.0, 0.0], "main_category": "Audio"},
        {"parent_asin": "best", "embedding": [0.8, 0.2], "main_category": "Audio"},
        {"parent_asin": "weak", "embedding": [0.0, 1.0], "main_category": "Audio"},
    ])
    two_tower_index = load_two_tower_index(recall_index_path)
    sequence = {"user_id": "missing", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}

    candidates = two_tower_candidates_for_user(sequence, two_tower_index, {"two_tower_enabled": True, "two_tower_per_user": 1})

    assert [candidate.item_id for candidate in candidates] == ["best"]


def test_merge_for_user_is_unchanged_when_two_tower_is_default_off():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    two_tower_index = {
        "seed": {"parent_asin": "seed", "two_tower_tokens": {"wireless", "audio"}},
        "two_tower_rec": {"parent_asin": "two_tower_rec", "two_tower_tokens": {"wireless", "audio"}},
    }

    baseline, baseline_fallback = merge_for_user(sequence, [], {"seed": [RecallCandidate("cf", "itemcf_weak", 2.0)]}, {}, {}, {}, {"candidate_pool_size": 5})
    with_index, with_index_fallback = merge_for_user(sequence, [], {"seed": [RecallCandidate("cf", "itemcf_weak", 2.0)]}, {}, {}, {}, {"candidate_pool_size": 5}, two_tower_index=two_tower_index)

    assert baseline_fallback is False
    assert with_index_fallback is False
    assert [(candidate.item_id, candidate.sources, candidate.source_scores) for candidate in with_index] == [
        (candidate.item_id, candidate.sources, candidate.source_scores) for candidate in baseline
    ]


def test_merge_for_user_deduplicates_two_tower_and_preserves_source_scores():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    two_tower_index = {
        "seed": {"parent_asin": "seed", "two_tower_tokens": {"wireless", "audio"}},
        "rec": {"parent_asin": "rec", "two_tower_tokens": {"wireless", "audio"}},
    }

    candidates, fallback_used = merge_for_user(
        sequence,
        [],
        {"seed": [RecallCandidate("rec", "itemcf_weak", 2.0)]},
        {},
        {},
        {},
        {"candidate_pool_size": 5, "two_tower_enabled": True, "two_tower_per_user": 2},
        two_tower_index=two_tower_index,
    )

    assert fallback_used is False
    assert [candidate.item_id for candidate in candidates] == ["rec"]
    assert candidates[0].sources == ["itemcf_weak", "two_tower"]
    assert candidates[0].source_scores == {"itemcf_weak": 2.0, "two_tower": 1.0}


def test_balanced_source_budget_can_reserve_two_tower_candidates():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    candidates, fallback_used = merge_for_user(
        sequence,
        [RecallCandidate("pop1", "popular", 100.0), RecallCandidate("pop2", "popular", 99.0)],
        {"seed": [RecallCandidate("cf", "itemcf_weak", 10.0)]},
        {},
        {},
        {},
        {
            "candidate_pool_size": 2,
            "popular_fallback_count": 2,
            "two_tower_enabled": True,
            "two_tower_per_user": 2,
            "candidate_pool_strategy": "balanced_source_budget",
            "candidate_source_minimums": {"two_tower": 1},
            "candidate_fill_order": ["popular", "itemcf", "two_tower"],
        },
        two_tower_index={
            "seed": {"parent_asin": "seed", "two_tower_tokens": {"rare", "audio"}},
            "two_tower_rec": {"parent_asin": "two_tower_rec", "two_tower_tokens": {"rare", "audio"}},
        },
    )

    assert fallback_used is False
    assert {candidate.item_id for candidate in candidates} == {"pop1", "two_tower_rec"}


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


def test_balanced_source_budget_preserves_itemcf_and_semantic_minimums_and_caps_popular():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    candidates, fallback_used = merge_for_user(
        sequence,
        [
            RecallCandidate("pop1", "popular", 100.0),
            RecallCandidate("pop2", "popular", 99.0),
            RecallCandidate("pop3", "popular", 98.0),
        ],
        {"seed": [RecallCandidate("cf", "itemcf_weak", 1.0)]},
        {},
        {},
        {},
        {
            "candidate_pool_size": 4,
            "popular_fallback_count": 3,
            "popular_fill_policy": "capped_remainder",
            "popular_max_in_pool": 1,
            "semantic_enabled": True,
            "candidate_pool_strategy": "balanced_source_budget",
            "candidate_source_minimums": {"itemcf": 1, "semantic": 1},
            "candidate_source_maximums": {"popular": 1},
            "candidate_fill_order": ["itemcf", "semantic", "popular"],
        },
        {
            "seed": {"parent_asin": "seed", "main_category": "Audio", "categories_flat": ["Audio"], "semantic_tokens": {"rare", "audio"}},
            "sem": {"parent_asin": "sem", "main_category": "Audio", "categories_flat": ["Audio"], "semantic_tokens": {"rare", "audio"}},
        },
    )

    assert fallback_used is False
    assert {candidate.item_id for candidate in candidates} == {"cf", "sem", "pop1"}


def test_popular_capped_fill_caps_only_when_non_popular_candidates_exist():
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": ["seed"],
        "recent_positive_item_sequence": ["seed"],
        "recent_strong_positive_item_sequence": [],
    }
    popular = [
        RecallCandidate("pop1", "popular", 3.0),
        RecallCandidate("pop2", "popular", 2.0),
        RecallCandidate("pop3", "popular", 1.0),
    ]
    config = {
        "candidate_pool_size": 4,
        "popular_fallback_count": 3,
        "popular_fill_policy": "capped_remainder",
        "popular_max_in_pool": 1,
    }

    mixed_candidates, mixed_fallback_used = merge_for_user(
        sequence,
        popular,
        {"seed": [RecallCandidate("cf", "itemcf_weak", 1.0)]},
        {},
        {},
        {},
        config,
    )
    fallback_candidates, fallback_used = merge_for_user(
        {**sequence, "recent_positive_item_sequence": []},
        popular,
        {},
        {},
        {},
        {},
        config,
    )

    assert mixed_fallback_used is False
    assert [candidate.item_id for candidate in mixed_candidates] == ["pop1", "cf"]
    assert fallback_used is True
    assert [candidate.item_id for candidate in fallback_candidates] == ["pop1", "pop2", "pop3"]


def test_semantic_idf_seed_aware_prefers_rare_seed_overlap_and_filters_seen_items(tmp_path: Path):
    semantic_path = tmp_path / "semantic.jsonl"
    write_jsonl(semantic_path, [
        {"parent_asin": "seed", "title_clean": "common audio rareterm", "main_category": "Audio"},
        {"parent_asin": "rare_match", "title_clean": "rareterm studio monitor", "main_category": "Audio"},
        {"parent_asin": "generic_match", "title_clean": "audio wireless", "main_category": "Audio"},
        {"parent_asin": "seen_candidate", "title_clean": "common audio", "main_category": "Audio"},
        {"parent_asin": "common_doc_1", "title_clean": "common cable", "main_category": "Audio"},
        {"parent_asin": "common_doc_2", "title_clean": "common charger", "main_category": "Audio"},
        {"parent_asin": "common_doc_3", "title_clean": "common adapter", "main_category": "Audio"},
    ])
    semantic_index = load_semantic_index(semantic_path, ["title_clean"])
    sequence = {"recent_item_sequence": ["seed", "seen_candidate"], "recent_positive_item_sequence": ["seed"]}

    candidates = semantic_candidates_for_user(
        sequence,
        semantic_index,
        {
            "semantic_enabled": True,
            "semantic_per_user": 3,
            "semantic_min_overlap": 1,
            "semantic_score_mode": "idf_seed_aware",
            "semantic_max_df_ratio": 1.0,
            "semantic_category_weight": 0.0,
        }
    )

    assert [candidate.item_id for candidate in candidates[:2]] == ["rare_match", "generic_match"]
    assert "seen_candidate" not in {candidate.item_id for candidate in candidates}


def test_itemcf_seed_window_includes_older_seeds_and_decay_prefers_recent_seed_scores():
    seed_items = [f"seed_{index}" for index in range(12)]
    sequence = {
        "user_id": "u1",
        "recent_item_sequence": seed_items,
        "recent_positive_item_sequence": seed_items,
        "recent_strong_positive_item_sequence": [],
    }
    itemcf_weak = {
        "seed_0": [RecallCandidate("old_rec", "itemcf_weak", 10.0)],
        "seed_11": [RecallCandidate("recent_rec", "itemcf_weak", 10.0)],
    }

    default_candidates, _ = merge_for_user(sequence, [], itemcf_weak, {}, {}, {}, {"candidate_pool_size": 5})
    expanded_candidates, fallback_used = merge_for_user(
        sequence,
        [],
        itemcf_weak,
        {},
        {},
        {},
        {
            "candidate_pool_size": 5,
            "itemcf_recent_positive_window": 12,
            "itemcf_seed_decay_enabled": True,
            "itemcf_seed_decay_base": 0.5,
        }
    )

    assert [candidate.item_id for candidate in default_candidates] == ["recent_rec"]
    assert fallback_used is False
    assert [candidate.item_id for candidate in expanded_candidates] == ["recent_rec", "old_rec"]
    assert expanded_candidates[0].source_scores["itemcf_weak"] > expanded_candidates[1].source_scores["itemcf_weak"]


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
        "empty_candidate_users",
        "empty_candidate_rate",
        "user_candidate_coverage_rate",
        "candidate_count_min",
        "candidate_count_p50",
        "candidate_count_p90",
        "candidate_count_max",
        "candidate_hit_rate_at_cutoffs",
        "candidate_recall_at_cutoffs",
        "catalog_candidate_coverage_count",
        "catalog_candidate_coverage_rate",
        "source_user_coverage",
        "source_item_coverage",
        "source_marginal_candidate_hit_users",
        "source_marginal_candidate_hit_rate",
        "recall_source_coverage",
        "topk_source_coverage",
        "source_diagnostics",
        "candidate_hit_rate_at_pool",
        "candidate_hit_users",
        "candidate_hit_source_coverage",
        "candidate_hit_rank_min",
        "candidate_hit_rank_avg",
        "candidate_hit_rank_p50",
        "candidate_hit_rank_p90",
        "candidate_hit_missed_topk_users",
        "ranked_hit_users",
        "fallback_rate",
        "recall_at_k",
        "recall_at_pool",
        "ndcg_at_k",
        "mrr_at_k",
        "map_at_k",
        "hit_rate_at_k",
        "per_source_candidate_contribution",
        "per_source_topk_contribution",
        "source_overlap",
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
    assert summary["empty_candidate_users"] == 0
    assert summary["empty_candidate_rate"] == 0.0
    assert summary["user_candidate_coverage_rate"] == 1.0
    assert summary["candidate_count_min"] == 2
    assert summary["candidate_count_p50"] == 2.0
    assert summary["candidate_count_p90"] == 2.0
    assert summary["candidate_count_max"] == 2
    assert summary["candidate_hit_rate_at_cutoffs"] == {"20": 1.0, "50": 1.0, "100": 1.0, "200": 1.0}
    assert summary["candidate_recall_at_cutoffs"] == {"20": 1.0, "50": 1.0, "100": 1.0, "200": 1.0}
    assert summary["catalog_candidate_coverage_count"] == 2
    assert summary["catalog_candidate_coverage_rate"] is None
    assert summary["source_user_coverage"] == {"itemcf_weak": 1, "popular": 1}
    assert summary["source_item_coverage"] == {"itemcf_weak": 1, "popular": 1}
    assert summary["source_marginal_candidate_hit_users"] == {"popular": 1}
    assert summary["source_marginal_candidate_hit_rate"] == {"popular": 1.0}
    assert summary["candidate_hit_users"] == 1
    assert summary["candidate_hit_source_coverage"] == {"popular": 1}
    assert summary["candidate_hit_rank_min"] == 2
    assert summary["candidate_hit_rank_avg"] == 2.0
    assert summary["candidate_hit_rank_p50"] == 2.0
    assert summary["candidate_hit_rank_p90"] == 2.0
    assert summary["candidate_hit_missed_topk_users"] == 0
    assert summary["ranked_hit_users"] == 1
    assert summary["recall_at_k"] == 1.0
    assert summary["recall_at_pool"] == 1.0
    assert summary["ndcg_at_k"] == 0.63093
    assert summary["mrr_at_k"] == 0.5
    assert summary["map_at_k"] == 0.5
    assert summary["per_source_candidate_contribution"] == {"popular": 1}
    assert summary["per_source_topk_contribution"] == {"popular": 1}
    assert summary["source_overlap"]["multi_source_candidate_rate"] == 0.0
    assert summary["popular_only_hit_rate_at_k"] == 1.0
    assert summary["topk_source_coverage"] == {"itemcf_weak": 1, "popular": 1}


def test_frozen_candidate_signature_compares_ordered_user_item_lists():
    baseline_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    same_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    drift_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "b"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "a"},
    ]

    assert compare_frozen_candidate_signatures(baseline_rows, same_rows)["status"] == "MATCH"
    drift = compare_frozen_candidate_signatures(baseline_rows, drift_rows)
    assert drift["status"] == "DRIFT"
    assert drift["hash_match"] is False
    assert drift["candidate_count_match"] is True



def test_frozen_candidate_signature_uses_candidate_rank_not_file_order():
    baseline_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
        {"user_id": "u2", "candidate_rank": 1, "item_id": "c"},
    ]
    reordered_rows = [
        {"user_id": "u2", "candidate_rank": 1, "item_id": "c", "metadata": {"ignored": True}},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b", "sources": ["semantic"]},
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a", "source_scores": {"semantic": 0.1}},
    ]

    comparison = compare_frozen_candidate_signatures(baseline_rows, reordered_rows)

    assert comparison["status"] == "MATCH"
    assert comparison["hash_match"] is True
    assert comparison["counts_by_user_match"] is True



def test_phase_1_27_feature_contract_records_allowed_and_forbidden_boundaries():
    contract = build_ranking_feature_contract()

    assert contract["version"] == "ranking_feature_contract_v1"
    assert contract["promotion_scope"] == "ranking_on_frozen_recall_pool_only"
    assert "source_features" in contract["allowed_feature_families"]
    assert "item_metadata_features" in contract["allowed_feature_families"]
    assert "candidate_rank_features" in contract["allowed_feature_families"]
    assert "source_score_features" in contract["allowed_feature_families"]
    assert "user_history_aggregate_features" in contract["allowed_feature_families"]
    assert "near_miss_diagnostics_features" in contract["diagnostic_only_feature_families"]
    assert "holdout_target_features" in contract["forbidden_feature_families"]
    assert "future_interaction_features" in contract["forbidden_feature_families"]
    assert "valid_or_test_trained_features" in contract["forbidden_feature_families"]



def test_frozen_candidate_artifact_and_registry_entry_capture_ranking_only_contract():
    rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    metrics = {
        "hit_rate_at_k": 0.1,
        "ndcg_at_k": 0.2,
        "candidate_hit_rate_at_pool": 0.5,
        "candidate_count_avg": 2.0,
    }

    artifact = frozen_candidate_artifact(rows)
    entry = build_ranking_experiment_registry_entry(
        experiment_id="phase_1_26_baseline",
        config={"strategy_name": "phase_1_26_baseline", "candidate_pool_size": 200, "top_k": 5},
        frozen_rows=rows,
        metrics=metrics,
        status={"status": "BASELINE", "promotable": False, "diagnostic_only": True, "reasons": ["same_run_baseline"]},
    )

    assert artifact["schema_version"] == "frozen_candidate_artifact_v1"
    assert compare_frozen_candidate_artifacts(artifact, entry["frozen_candidate_artifact"])["status"] == "MATCH"
    assert entry["schema_version"] == "ranking_experiment_registry_v1"
    assert entry["promotion_scope"] == "ranking_on_frozen_recall_pool_only"
    assert entry["candidate_pool_size"] == 200
    assert entry["top_k"] == 5
    assert entry["key_metrics"]["hit_rate_at_k"] == 0.1


def test_phase_1_26_real_ranking_runner_contract_keeps_pool200_and_blocks_tree_methods():
    assert phase_1_26_runner._PHASE == "phase_1_26_real_ranking_experiments"
    assert phase_1_26_runner.BASELINE_CONFIG.name == "phase_1_25_pool200_same_run_baseline.yaml"
    assert [variant["name"] for variant in phase_1_26_runner.LEARNED_VARIANTS] == [
        "pointwise_logistic_fine_ranker_lopo",
        "pairwise_perceptron_fine_ranker_lopo",
    ]

    registry_rows = phase_1_26_runner._tree_method_registry_rows()

    assert {row["state"] for row in registry_rows} == {"blocked"}
    assert {row["promotion_eligible"] for row in registry_rows} == {False}
    assert all("real_tree_serving_adapter_missing" in row["reasons"] for row in registry_rows)
    assert all(row["gpu_resource"]["status"] in {"not_required", "blocked-gpu-unavailable"} for row in registry_rows)


def test_phase_1_26_registry_entry_records_frozen_candidate_artifact_and_scope():
    rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    metrics = {
        "hit_rate_at_k": 0.1,
        "ndcg_at_k": 0.2,
        "mrr_at_k": 0.3,
        "map_at_k": 0.4,
        "candidate_hit_missed_topk_users": 2,
        "candidate_hit_rate_at_pool": 0.5,
        "fallback_rate": 0.0,
        "candidate_count_avg": 2.0,
    }

    artifact = frozen_candidate_artifact(rows)
    registry = build_ranking_experiment_registry_entry(
        experiment_id="phase_1_26_baseline",
        config={"strategy_name": "pool200_baseline", "candidate_pool_size": 200, "top_k": 5},
        frozen_rows=rows,
        metrics=metrics,
    )

    assert artifact["schema_version"] == "frozen_candidate_artifact_v1"
    assert artifact["canonical_order"] == "user_id_asc_candidate_order_item_id"
    assert registry["schema_version"] == "ranking_experiment_registry_v1"
    assert registry["promotion_scope"] == "ranking_on_frozen_recall_pool_only"
    assert registry["candidate_pool_size"] == 200
    assert registry["top_k"] == 5
    assert registry["frozen_candidate_artifact"]["hash"] == artifact["hash"]
    assert registry["key_metrics"]["hit_rate_at_k"] == 0.1
    assert registry["status"]["status"] == "BASELINE"



def test_phase_1_26_runner_contract_keeps_pool200_baseline_and_blocks_gpu_tree_methods():
    assert phase_1_26_runner._command_text(Path("outputs/ranking/phase_1_26"), 3).startswith("./.venv/Scripts/python.exe")
    assert phase_1_26_runner.BASELINE_CONFIG.name == "phase_1_25_pool200_same_run_baseline.yaml"

    tree_rows = phase_1_26_runner._tree_method_registry_rows()
    by_id = {row["method_id"]: row for row in tree_rows}

    assert {row["lane"] for row in tree_rows} == {"blocked"}
    assert by_id["sklearn_gbdt_fine_ranker"]["method_family"] == "gbdt"
    assert by_id["sklearn_gbdt_fine_ranker"]["gpu_resource"]["status"] == "not_required"
    for method_id in ["xgboost_lambdamart_fine_ranker", "lightgbm_lambdamart_fine_ranker"]:
        row = by_id[method_id]
        assert row["method_family"] == "lambdamart"
        assert row["state"] == "blocked"
        assert row["promotion_eligible"] is False
        assert "gpu_required_not_verified" in row["reasons"]
        assert row["gpu_resource"]["status"] == "blocked-gpu-unavailable"


def test_phase_1_26_learned_gbdt_contract_records_real_training_and_blocked_gpu_boundaries():
    dependency_status = {"sklearn": True, "xgboost": False, "lightgbm": False}
    tree_training = {
        "sklearn_gbdt_diagnostic": {
            "state": "diagnostic",
            "promotion_eligible": False,
            "diagnostic_only": True,
            "reasons": ["tree_serving_adapter_missing", "diagnostic_tree_training_only"],
        },
        "xgboost_lambdamart_gpu": {
            "state": "blocked",
            "promotion_eligible": False,
            "diagnostic_only": False,
            "reasons": ["gpu_unavailable", "tree_serving_adapter_missing"],
        },
        "lightgbm_lambdamart_gpu": {
            "state": "blocked",
            "promotion_eligible": False,
            "diagnostic_only": False,
            "reasons": ["gpu_unavailable", "tree_serving_adapter_missing"],
        },
    }

    rows = phase_1_26_learned_gbdt_runner._tree_method_registry_rows(tree_training, dependency_status)
    by_id = {row["method_id"]: row for row in rows}
    strategy = phase_1_26_learned_gbdt_runner._gpu_resource_strategy(dependency_status)

    assert phase_1_26_learned_gbdt_runner._command_text(Path("outputs/ranking/phase_1_26"), 2, 123).startswith("./.venv/Scripts/python.exe")
    assert phase_1_26_learned_gbdt_runner.BASELINE_CONFIG.name == "phase_1_25_pool200_same_run_baseline.yaml"
    assert strategy["current_phase_gpu_required"] is False
    assert strategy["unavailable_status"] == "blocked-gpu-unavailable"
    assert by_id["sklearn_gbdt_diagnostic"]["method_family"] == "gbdt"
    assert by_id["sklearn_gbdt_diagnostic"]["lane"] == "diagnostic"
    assert by_id["sklearn_gbdt_diagnostic"]["gpu_resource"]["status"] == "not_required"
    for method_id in ["xgboost_lambdamart_gpu", "lightgbm_lambdamart_gpu"]:
        row = by_id[method_id]
        assert row["lane"] == "blocked"
        assert row["state"] == "blocked"
        assert row["method_family"] == "lambdamart"
        assert row["gpu_resource"]["status"] == "blocked-gpu-unavailable"


def test_phase_0_method_registry_entry_records_state_and_gpu_resource():
    gpu_resource = build_ranking_gpu_resource_summary(gpu_required=True, gpu_available=True, device="cuda:0", dependency_status="torch-ok")

    entry = build_ranking_method_registry_entry(
        method_id="lambdamart_style_pairwise_rules",
        method_family="lambdamart",
        lane="promotion",
        state="challenger",
        promotion_eligible=True,
        diagnostic_only=False,
        reasons=["promotion_thresholds_met"],
        challenger_of="same_run_baseline",
        gpu_resource=gpu_resource,
    )

    assert entry["schema_version"] == "ranking_method_registry_v1"
    assert entry["state"] == "challenger"
    assert entry["challenger_of"] == "same_run_baseline"
    assert entry["gpu_resource"]["status"] == "gpu_enabled"
    assert entry["gpu_resource"]["device"] == "cuda:0"


def test_phase_0_method_registry_rejects_unknown_state():
    try:
        build_ranking_method_registry_entry(
            method_id="unknown",
            method_family="rules",
            lane="promotion",
            state="done",
            promotion_eligible=False,
            diagnostic_only=False,
        )
    except ValueError as exc:
        assert "Unsupported ranking method state" in str(exc)
    else:
        raise AssertionError("unknown ranking method state was not rejected")


def test_phase_0_gpu_resource_summary_records_blocked_and_cpu_smoke_states():
    assert build_ranking_gpu_resource_summary(gpu_required=False)["status"] == "not_required"
    assert build_ranking_gpu_resource_summary(gpu_required=True, gpu_available=True, device="cuda:0")["status"] == "gpu_enabled"
    assert build_ranking_gpu_resource_summary(gpu_required=True, gpu_available=False)["status"] == "blocked-gpu-unavailable"
    assert build_ranking_gpu_resource_summary(gpu_required=True, gpu_available=False, fallback_status="diagnostic-cpu-smoke")["status"] == "diagnostic-cpu-smoke"


def test_phase_0_artifact_inspection_enforces_paths_boundaries_and_diagnostic_scope(tmp_path):
    artifact_paths = {}
    for key, filename in {
        "metrics_path": "metrics.json",
        "recommendations_path": "recommendations.jsonl",
        "ranking_cases_path": "ranking_hit_cases.jsonl",
        "ranking_case_summary_path": "ranking_case_summary.json",
        "report_path": "report.md",
        "frozen_candidates_path": "frozen_candidates.jsonl",
    }.items():
        path = tmp_path / filename
        path.write_text("{}", encoding="utf-8")
        artifact_paths[key] = str(path)
    base_row = {
        "run_index": 0,
        "candidate_id": "same_run_baseline",
        "lane": "promotion",
        "promotion_eligible": True,
        "diagnostic_only": False,
        "ranking_experiment_registry": {"candidate_pool_size": 200, "top_k": 5},
        "frozen_candidate_comparison": {"match": True},
        **artifact_paths,
    }

    pass_summary = inspect_ranking_run_artifacts([base_row])
    diagnostic_violation = inspect_ranking_run_artifacts([base_row | {"candidate_id": "pointwise", "lane": "diagnostic", "diagnostic_only": True}])
    frozen_mismatch = inspect_ranking_run_artifacts([base_row | {"frozen_candidate_comparison": {"match": False}}])
    boundary_drift = inspect_ranking_run_artifacts([base_row | {"ranking_experiment_registry": {"candidate_pool_size": 100, "top_k": 5}}])

    assert pass_summary["schema_version"] == "ranking_artifact_inspection_v1"
    assert pass_summary["status"] == "PASS"
    assert diagnostic_violation["status"] == "INVALID"
    assert diagnostic_violation["invalid_runs"][0]["diagnostic_promotion_violation"] is True
    assert frozen_mismatch["status"] == "INVALID"
    assert frozen_mismatch["invalid_runs"][0]["frozen_candidate_match"] is False
    assert boundary_drift["status"] == "INVALID"
    assert boundary_drift["invalid_runs"][0]["candidate_pool_size"] == 100



def test_phase_1_27_registry_entry_can_record_feature_contract_without_recall_drift():
    rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    contract = build_ranking_feature_contract()

    registry = build_ranking_experiment_registry_entry(
        experiment_id="phase_1_27_feature_contract",
        config={"strategy_name": "pool200_baseline", "candidate_pool_size": 200, "top_k": 5},
        frozen_rows=rows,
        metrics={"hit_rate_at_k": 0.1},
        feature_contract=contract,
    )

    assert registry["promotion_scope"] == "ranking_on_frozen_recall_pool_only"
    assert registry["candidate_pool_size"] == 200
    assert registry["top_k"] == 5
    assert registry["feature_contract_version"] == "ranking_feature_contract_v1"
    assert registry["feature_contract"] == contract
    assert registry["frozen_candidate_artifact"]["hash"] == frozen_candidate_artifact(rows)["hash"]



def test_phase_1_26_candidate_artifact_equality_reuses_strict_signature_gate():
    baseline_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    same_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    drift_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "b"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "a"},
    ]

    assert compare_frozen_candidate_artifacts(frozen_candidate_artifact(baseline_rows), frozen_candidate_artifact(same_rows))["status"] == "MATCH"
    drift = compare_frozen_candidate_artifacts(frozen_candidate_artifact(baseline_rows), frozen_candidate_artifact(drift_rows))
    assert drift["status"] == "DRIFT"
    assert drift["hash_match"] is False
    assert drift["candidate_count_match"] is True



def test_strict_ranking_promotion_status_promote_partial_and_invalid_stop():
    baseline = {
        "hit_rate_at_k": 0.1,
        "ndcg_at_k": 0.1,
        "mrr_at_k": 0.1,
        "map_at_k": 0.1,
        "candidate_hit_missed_topk_users": 3,
        "candidate_hit_rate_at_pool": 0.5,
        "fallback_rate": 0.0,
        "candidate_count_avg": 2.0,
        "config_summary": {"candidate_pool_size": 200, "top_k": 5},
    }
    promoted = baseline | {"hit_rate_at_k": 0.2, "ndcg_at_k": 0.1, "mrr_at_k": 0.1, "map_at_k": 0.1, "candidate_hit_missed_topk_users": 2}
    partial = baseline | {"ndcg_at_k": 0.2}
    tiny_absolute_lift = baseline | {"hit_rate_at_k": 0.1005, "candidate_hit_missed_topk_users": 2}
    tiny_relative_lift = baseline | {"hit_rate_at_k": 0.102, "candidate_hit_missed_topk_users": 2}
    no_missed_topk_reduction = baseline | {"hit_rate_at_k": 0.2}
    invalid = baseline | {"fallback_rate": 0.1}
    freeze = {"match": True}

    assert strict_ranking_promotion_status(baseline, promoted, freeze)["status"] == "Promote"
    partial_status = strict_ranking_promotion_status(baseline, partial, freeze)
    assert partial_status["status"] == "PARTIAL diagnostic-only"
    assert partial_status["promotable"] is False
    assert "secondary_metric_improved_without_hit_rate_gain" in partial_status["reasons"]
    absolute_lift_status = strict_ranking_promotion_status(baseline, tiny_absolute_lift, freeze)
    assert absolute_lift_status["status"] == "PARTIAL diagnostic-only"
    assert "hit_rate_absolute_lift_below_0.001" in absolute_lift_status["reasons"]
    relative_lift_status = strict_ranking_promotion_status(baseline, tiny_relative_lift, freeze)
    assert relative_lift_status["status"] == "PARTIAL diagnostic-only"
    assert "hit_rate_relative_lift_below_3pct" in relative_lift_status["reasons"]
    missed_topk_status = strict_ranking_promotion_status(baseline, no_missed_topk_reduction, freeze)
    assert missed_topk_status["status"] == "PARTIAL diagnostic-only"
    assert "missed_topk_reduction_below_1" in missed_topk_status["reasons"]
    invalid_status = strict_ranking_promotion_status(baseline, invalid, freeze)
    assert invalid_status["status"] == "INVALID/STOP"
    assert "fallback_rate_increased" in invalid_status["reasons"]
    assert strict_ranking_promotion_status(baseline, promoted, {"match": False})["status"] == "INVALID/STOP"
    assert strict_ranking_promotion_status(baseline, promoted, freeze, ltr_enabled=True)["status"] == "PARTIAL diagnostic-only"
    contract_reject = strict_ranking_promotion_status(
        baseline,
        promoted,
        freeze,
        feature_contract_gate_summary={"status": "REJECT", "reasons": ["unknown_feature_names"]},
    )
    assert contract_reject["status"] == "INVALID/STOP"
    assert "feature_contract_gate_rejected" in contract_reject["reasons"]
    leakage_reject = strict_ranking_promotion_status(
        baseline,
        promoted,
        freeze,
        leakage_gate_summary={"status": "REJECT", "reasons": ["forbidden_feature_names"]},
    )
    assert leakage_reject["status"] == "INVALID/STOP"
    assert "leakage_gate_rejected" in leakage_reject["reasons"]


def test_terminal_ranking_promotion_gate_stability_segments_and_invalid_exclusion():
    promote = {"status": "Promote", "promotable": True, "diagnostic_only": False, "reasons": []}
    partial = {"status": "PARTIAL diagnostic-only", "promotable": False, "diagnostic_only": True, "reasons": ["hit_rate_absolute_lift_below_0.001"]}
    invalid = {"status": "INVALID/STOP", "promotable": False, "diagnostic_only": True, "reasons": ["fallback_rate_increased"]}

    gate = terminal_ranking_promotion_gate(
        [promote, promote, partial, invalid],
        segment_statuses={
            "large_segment": promote | {"user_count": 50, "positive_user_count": 8},
            "small_segment": partial | {"user_count": 12, "positive_user_count": 3},
        },
    )

    assert gate["status"] == "No-Promote"
    assert gate["valid_run_count"] == 3
    assert gate["invalid_stop_run_count"] == 1
    assert gate["consistent_promote_run_count"] == 2
    assert "invalid_stop_evidence_excluded_from_promotion" in gate["no_promote_rationale"]
    assert gate["excluded_invalid_stop_reasons"] == [["fallback_rate_increased"]]
    assert gate["segment_gate"]["segments"]["large_segment"]["promotion_eligible"] is True
    assert gate["segment_gate"]["segments"]["small_segment"]["promotion_eligible"] is False
    assert gate["segment_gate"]["segments"]["small_segment"]["underpowered"] is True
    assert gate["segment_gate"]["segments"]["small_segment"]["diagnostic_only"] is True

    stable_gate = terminal_ranking_promotion_gate([promote, promote, partial])
    assert stable_gate["status"] == "Promote"
    assert stable_gate["promotable"] is True



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
    assert summary["candidate_hit_rank_p90"] == 3.0
    assert summary["recall_at_pool"] == 1.0
    assert summary["recall_at_k"] == 0.0
    assert summary["ndcg_at_k"] == 0.0
    assert summary["mrr_at_k"] == 0.0
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



def test_workflow_two_tower_seed_is_opt_in_requires_sidecar_and_reports_contribution(tmp_path: Path):
    clean = tmp_path / "clean"
    views = tmp_path / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [
        {
            "user_id": "u1",
            "recent_item_sequence": ["strong_seed", "positive_seed", "seen"],
            "recent_positive_item_sequence": ["positive_seed"],
            "recent_strong_positive_item_sequence": ["strong_seed"],
        }
    ])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "seed_rec", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "pop", "category": "cat", "pop_score": 2}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "strong_seed", "main_category": "cat"},
        {"parent_asin": "positive_seed", "main_category": "cat"},
        {"parent_asin": "seed_rec", "main_category": "cat"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [])
    base_config = {
        "clean_dir": str(clean),
        "views_dir": str(views),
        "top_k": 2,
        "candidate_pool_size": 5,
        "popular_fallback_count": 1,
    }
    disabled_path = tmp_path / "disabled_config.yaml"
    disabled_path.write_text(json.dumps(base_config | {"output_dir": str(tmp_path / "disabled_out"), "report_path": str(tmp_path / "disabled_report.md")}), encoding="utf-8")

    disabled_result = run_hybrid_demo(disabled_path)

    disabled_metrics = json.loads(Path(disabled_result["metrics_path"]).read_text(encoding="utf-8"))
    assert disabled_metrics["config_summary"]["two_tower_seed_enabled"] is False
    assert "two_tower_seed" not in disabled_metrics["recall_source_coverage"]
    assert disabled_metrics["source_diagnostics"]["two_tower_seed_raw_candidates"] == 0
    write_jsonl(views / "two_tower_seed_recall.jsonl", [
        {"item_id": "strong_seed", "neighbors": [{"item_id": "seed_rec", "score": 3.0, "rank": 1}]},
        {"item_id": "positive_seed", "neighbors": [{"item_id": "seen", "score": 4.0, "rank": 1}]},
    ])
    (views / "two_tower_seed_manifest.json").write_text(
        json.dumps({"phase": "1.18", "source": "two_tower_seed", "schema_version": "two_tower_seed_neighbors_v1"}),
        encoding="utf-8",
    )
    enabled_path = tmp_path / "enabled_config.yaml"
    enabled_path.write_text(json.dumps(base_config | {"output_dir": str(tmp_path / "enabled_out"), "report_path": str(tmp_path / "enabled_report.md"), "two_tower_seed_enabled": True, "two_tower_enabled": False, "fail_on_missing_sidecar": True}), encoding="utf-8")

    enabled_result = run_hybrid_demo(enabled_path)

    enabled_metrics = json.loads(Path(enabled_result["metrics_path"]).read_text(encoding="utf-8"))
    assert enabled_metrics["config_summary"]["two_tower_seed_enabled"] is True
    assert enabled_metrics["config_summary"]["two_tower_enabled"] is False
    assert enabled_metrics["candidate_hit_source_coverage"] == {"two_tower_seed": 1}
    assert enabled_metrics["per_source_candidate_contribution"] == {"two_tower_seed": 1}
    assert enabled_metrics["recall_source_coverage"]["two_tower_seed"] == 1
    assert enabled_metrics["source_diagnostics"]["two_tower_seed_raw_candidates"] == 2
    assert enabled_metrics["source_diagnostics"]["two_tower_seed_raw_unseen_candidates"] == 1
    (views / "two_tower_seed_recall.jsonl").unlink()
    missing_sidecar_path = tmp_path / "missing_sidecar_config.yaml"
    missing_sidecar_path.write_text(json.dumps(base_config | {"output_dir": str(tmp_path / "missing_sidecar_out"), "report_path": str(tmp_path / "missing_sidecar_report.md"), "two_tower_seed_enabled": True, "fail_on_missing_sidecar": True}), encoding="utf-8")
    try:
        run_hybrid_demo(missing_sidecar_path)
    except FileNotFoundError as error:
        assert "two_tower_seed_recall.jsonl" in str(error)
    else:
        raise AssertionError("Expected enabled two_tower_seed config to require sidecar")
    write_jsonl(views / "two_tower_seed_recall.jsonl", [])
    (views / "two_tower_seed_manifest.json").unlink()
    missing_manifest_path = tmp_path / "missing_manifest_config.yaml"
    missing_manifest_path.write_text(json.dumps(base_config | {"output_dir": str(tmp_path / "missing_manifest_out"), "report_path": str(tmp_path / "missing_manifest_report.md"), "two_tower_seed_enabled": True, "fail_on_missing_sidecar": True}), encoding="utf-8")
    try:
        run_hybrid_demo(missing_manifest_path)
    except FileNotFoundError as error:
        assert "two_tower_seed_manifest.json" in str(error)
    else:
        raise AssertionError("Expected fail_on_missing_sidecar to require manifest")


def test_workflow_item_graph_is_opt_in_and_requires_artifact_only_when_enabled(tmp_path: Path):
    clean = tmp_path / "clean"
    views = tmp_path / "views"
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
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "graph_rec", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "pop", "category": "cat", "pop_score": 2}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [{"parent_asin": "seed", "main_category": "cat"}, {"parent_asin": "graph_rec", "main_category": "cat"}])
    write_jsonl(views / "category_top_items.jsonl", [])
    base_config = {
        "clean_dir": str(clean),
        "views_dir": str(views),
        "top_k": 2,
        "candidate_pool_size": 5,
        "popular_fallback_count": 1,
    }
    disabled_path = tmp_path / "disabled_config.yaml"
    disabled_out = tmp_path / "disabled_out"
    disabled_report = tmp_path / "disabled_report.md"
    disabled_path.write_text(json.dumps(base_config | {"output_dir": str(disabled_out), "report_path": str(disabled_report)}), encoding="utf-8")

    disabled_result = run_hybrid_demo(disabled_path)

    disabled_metrics = json.loads(Path(disabled_result["metrics_path"]).read_text(encoding="utf-8"))
    assert disabled_metrics["config_summary"]["item_graph_enabled"] is False
    assert "item_graph" not in disabled_metrics["recall_source_coverage"]
    write_jsonl(views / "item_graph_recall.jsonl", [{"src_item": "seed", "dst_item": "graph_rec", "score": 3.0}])
    enabled_path = tmp_path / "enabled_config.yaml"
    enabled_out = tmp_path / "enabled_out"
    enabled_report = tmp_path / "enabled_report.md"
    enabled_path.write_text(json.dumps(base_config | {"output_dir": str(enabled_out), "report_path": str(enabled_report), "item_graph_enabled": True, "item_graph_per_seed": 2}), encoding="utf-8")

    enabled_result = run_hybrid_demo(enabled_path)

    enabled_metrics = json.loads(Path(enabled_result["metrics_path"]).read_text(encoding="utf-8"))
    assert enabled_metrics["config_summary"]["item_graph_enabled"] is True
    assert enabled_metrics["candidate_hit_source_coverage"] == {"item_graph": 1}
    assert enabled_metrics["recall_source_coverage"]["item_graph"] == 1
    missing_graph_path = views / "item_graph_recall.jsonl"
    missing_graph_path.unlink()
    missing_path = tmp_path / "missing_config.yaml"
    missing_path.write_text(json.dumps(base_config | {"output_dir": str(tmp_path / "missing_out"), "report_path": str(tmp_path / "missing_report.md"), "item_graph_enabled": True}), encoding="utf-8")
    try:
        run_hybrid_demo(missing_path)
    except FileNotFoundError as error:
        assert "item_graph_recall.jsonl" in str(error)
    else:
        raise AssertionError("Expected enabled item_graph config to require item_graph_recall.jsonl")



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
    assert Path(result["recall_registry_artifact_path"]).exists()
    assert report.exists()
    ranking_cases = [json.loads(line) for line in Path(result["ranking_cases_path"]).read_text(encoding="utf-8").splitlines()]
    assert ranking_cases[0]["user_id"] == "u1"
    assert ranking_cases[0]["target_item"] == "rec"
    assert ranking_cases[0]["target_rank"] == 1
    assert ranking_cases[0]["target_sources"] == ["itemcf_weak", "category"]
    assert ranking_cases[0]["target_source_scores"] == {"category": 1.0, "itemcf_weak": 3.0}
    assert ranking_cases[0]["affected_user_id"] == "u1"
    assert ranking_cases[0]["target_item_id"] == "rec"
    assert ranking_cases[0]["baseline_rank"] == 1
    assert ranking_cases[0]["variant_rank"] == 1
    assert ranking_cases[0]["topk_replacement_reason"] == {"reason": "target_in_topk", "replaced_by": []}
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
    assert metrics["empty_candidate_users"] == 0
    assert 0.0 <= metrics["empty_candidate_rate"] <= 1.0
    assert 0.0 <= metrics["user_candidate_coverage_rate"] <= 1.0
    assert metrics["candidate_count_min"] <= metrics["candidate_count_p50"] <= metrics["candidate_count_p90"] <= metrics["candidate_count_max"]
    assert metrics["candidate_hit_rate_at_cutoffs"]
    assert all(0.0 <= rate <= 1.0 for rate in metrics["candidate_hit_rate_at_cutoffs"].values())
    assert all(0.0 <= rate <= 1.0 for rate in metrics["candidate_recall_at_cutoffs"].values())
    assert metrics["catalog_candidate_coverage_count"] >= 1
    assert metrics["catalog_candidate_coverage_rate"] is None or 0.0 <= metrics["catalog_candidate_coverage_rate"] <= 1.0
    assert metrics["source_user_coverage"]["itemcf_weak"] == 1
    assert metrics["source_item_coverage"]["itemcf_weak"] == 1
    assert metrics["source_marginal_candidate_hit_users"] == {}
    assert metrics["source_marginal_candidate_hit_rate"] == {}
    assert "source_pair_jaccard" in metrics["source_overlap"]
    assert metrics["source_overlap"]["source_pair_jaccard"]["category+itemcf_weak"] == 1.0
    assert metrics["recall_at_pool"] == 1.0
    recall_registry_artifact = json.loads(Path(result["recall_registry_artifact_path"]).read_text(encoding="utf-8"))
    assert metrics["recall_registry_artifact_path"] == result["recall_registry_artifact_path"]
    assert recall_registry_artifact["scope_contract"] == "recall_only"
    assert recall_registry_artifact["lane"] == "observation"
    assert recall_registry_artifact["method_family"] == "hybrid_merge"
    assert recall_registry_artifact["source_name"] == "hybrid_merge"
    assert recall_registry_artifact["gate_status"] == "INCONCLUSIVE_MISSING_ARTIFACT"
    assert "frozen_candidates" in recall_registry_artifact["missing_promotion_required_artifacts"]
    assert recall_registry_artifact["promotion_required_artifacts"]["frozen_candidates"]["available"] is False
    assert recall_registry_artifact["missing_promotion_next_actions"]["frozen_candidates"] == "Produce and attach the missing recall promotion artifact before promotion."
    assert recall_registry_artifact["missing_promotion_next_actions"]["ablation"] == "Run the dedicated recall ablation workflow and attach its evidence manifest before promotion."
    assert recall_registry_artifact["promotion_required_artifacts"]["latency"]["available"] is True
    assert recall_registry_artifact["promotion_required_artifacts"]["fallback"]["available"] is True
    assert recall_registry_artifact["promotion_required_artifacts"]["overlap_source_contribution"]["available"] is True
    assert set(metrics["recall_promotion_artifact_paths"]) == {
        "source_coverage",
        "pool_curve",
        "latency",
        "fallback",
        "overlap_source_contribution",
    }
    assert result["recall_promotion_artifact_paths"] == metrics["recall_promotion_artifact_paths"]
    for artifact_name, artifact_path_value in metrics["recall_promotion_artifact_paths"].items():
        artifact_path = Path(artifact_path_value)
        assert artifact_path.exists()
        assert out.resolve() in artifact_path.resolve().parents
        assert json.loads(artifact_path.read_text(encoding="utf-8"))
        registry_entry = recall_registry_artifact["promotion_required_artifacts"].get(artifact_name)
        if registry_entry is not None:
            assert registry_entry["path"] == artifact_path_value
            assert registry_entry["sha256"] == hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    method_card_evidence = recall_registry_artifact["method_card_evidence"]
    assert recall_registry_artifact["canonical_baseline"] == "semantic_title_category_expansion"
    assert recall_registry_artifact["baseline_vs_source"]["baseline_source_name"] == "semantic_title_category_expansion"
    assert recall_registry_artifact["baseline_vs_source"]["comparison_scope"] == "candidate_pool_recall_only"
    assert recall_registry_artifact["evidence_level"] == "observation"
    assert recall_registry_artifact["experiment_scope"] == "valid_test"
    assert recall_registry_artifact["pool_displacement_risk"] == "unknown"
    assert recall_registry_artifact["promotion_blockers"] == ["pool_displacement_risk_unknown"]
    assert method_card_evidence["source_candidate_counts"]["before_cap"]["itemcf"] == 1
    assert method_card_evidence["source_candidate_counts"]["after_cap"]["itemcf_weak"] == 1
    assert method_card_evidence["legacy_migration"]["migration_status"] == "not_declared"
    assert "hit_rate_at_k" in recall_registry_artifact["forbidden_metrics"]
    assert "ndcg" in recall_registry_artifact["forbidden_metrics"]
    assert "ctr" in recall_registry_artifact["forbidden_metrics"]
    assert set(recall_registry_artifact["allowed_metrics"]).isdisjoint(recall_registry_artifact["forbidden_metrics"])
    metrics_digest = hashlib.sha256(Path(result["metrics_path"]).read_bytes()).hexdigest()
    assert recall_registry_artifact["artifact_signature"]["metrics_json_sha256"] == metrics_digest
    assert recall_registry_artifact["artifact_signature"]["frozen_candidates_jsonl_sha256"] is None
    assert metrics["ndcg_at_k"] == 1.0
    assert metrics["mrr_at_k"] == 1.0
    assert metrics["diagnostic_gate"]["recommended_next_phase"] in {
        "phase_1_10_baseline_ready",
        "phase_1_11_recall_source_merge",
        "phase_1_12_ranking_ltr_gate",
    }
    assert "ranking_avg_seconds" in metrics["latency"]
    assert "topk_source_coverage" in metrics
    report_text = report.read_text(encoding="utf-8")
    assert "Metrics and Ablation" in report_text
    assert "topk_source_coverage" in report_text
    assert "Diagnostic Gate" in report_text
    assert "Latency Diagnostics" in report_text
    assert "Recall Bottleneck Diagnostics" in report_text
    assert "candidate_hit_source_coverage" in report_text
    assert "Ranking Case Summary" in report_text


def test_recall_registry_artifact_marks_complete_recall_only_phase_b_contract(tmp_path):
    metrics_path = tmp_path / "metrics.json"
    frozen_candidates_path = tmp_path / "frozen_candidates.jsonl"
    metrics_path.write_text('{"ok": true}', encoding="utf-8")
    frozen_candidates_path.write_text('{"user_id": "u1", "item_id": "i1"}\n', encoding="utf-8")
    metrics = {
        "evaluation_mode": "valid_test",
        "users_total": 1,
        "users_with_holdout": 1,
        "hit_rate_denominator": "users_with_holdout",
        "fallback_rate": 0.0,
        "empty_candidate_users": 0,
        "empty_candidate_rate": 0.0,
        "frozen_candidates_signature": {"hash": "abc", "user_count": 1, "candidate_count": 1},
        "latency": {"candidate_generation_avg_seconds": 0.01, "candidate_generation_p95_seconds": 0.02},
        "candidate_hit_source_coverage": {"itemcf_weak": 1},
        "per_source_candidate_contribution": {"itemcf_weak": 1},
        "source_marginal_candidate_hit_users": {"itemcf_weak": 1},
        "source_marginal_candidate_hit_rate": {"itemcf_weak": 1.0},
        "source_overlap": {"source_pair_jaccard": {"category+itemcf_weak": 0.5}},
        "source_user_coverage": {"itemcf_weak": 1},
        "source_item_coverage": {"itemcf_weak": 1},
        "recall_source_coverage": {"itemcf_weak": 1},
    }

    artifact_paths = {
        "source_coverage": tmp_path / "recall_source_coverage.json",
        "pool_curve": tmp_path / "recall_pool_curve.json",
        "latency": tmp_path / "recall_latency_report.json",
        "fallback": tmp_path / "recall_fallback_report.json",
        "overlap_source_contribution": tmp_path / "recall_overlap_source_contribution.json",
    }
    for path in artifact_paths.values():
        path.write_text('{"ok": true}', encoding="utf-8")

    artifact = _recall_registry_artifact({"strategy_name": "phase_b", "candidate_pool_size": 200}, metrics, metrics_path, frozen_candidates_path, artifact_paths)

    assert artifact["scope_contract"] == "recall_only"
    assert artifact["promotion_scope"] == "recall_only_candidate_pool_default"
    assert artifact["gate_status"] == "INCONCLUSIVE_MISSING_ARTIFACT"
    assert artifact["missing_promotion_required_artifacts"] == ["ablation"]
    assert artifact["promotion_required_artifacts"]["frozen_candidates"]["available"] is True
    assert artifact["promotion_required_artifacts"]["latency"]["available"] is True
    assert artifact["promotion_required_artifacts"]["fallback"]["available"] is True
    assert artifact["promotion_required_artifacts"]["overlap_source_contribution"]["available"] is True
    assert artifact["promotion_required_artifacts"]["ablation"]["available"] is False
    assert artifact["promotion_required_artifacts"]["ablation"]["next_action"] == "Run the dedicated recall ablation workflow and attach its evidence manifest before promotion."
    assert artifact["missing_promotion_next_actions"] == {"ablation": "Run the dedicated recall ablation workflow and attach its evidence manifest before promotion."}
    assert artifact["method_card_evidence"]["canonical_baseline"] == "semantic_title_category_expansion"
    assert artifact["method_card_evidence"]["pool_displacement_risk"] == "unknown"
    assert artifact["method_card_evidence"]["promotion_blockers"] == ["pool_displacement_risk_unknown"]
    assert artifact["method_card_evidence"]["source_candidate_counts"]["after_cap"] == {"itemcf_weak": 1}
    assert artifact["method_card_evidence"]["legacy_migration"]["migration_status"] == "not_declared"
    assert artifact["promotion_required_artifacts"]["latency"]["metrics"]["candidate_generation_p95_seconds"] == 0.02
    for artifact_name in ["latency", "fallback", "overlap_source_contribution"]:
        artifact_entry = artifact["promotion_required_artifacts"][artifact_name]
        artifact_path = artifact_paths[artifact_name]
        assert artifact_entry["path"] == str(artifact_path)
        assert artifact_entry["sha256"] == hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert "hit_rate_at_k" in artifact["forbidden_metrics"]
    assert "topk_hit_rate" in artifact["forbidden_metrics"]
    assert "ranking_gap_pool_has_target" in artifact["diagnostic_excluded_metrics"]
    assert "hit_rate_at_k" in artifact["diagnostic_only_metrics"]
    assert "ctr" in artifact["forbidden_metrics"]
    assert set(artifact["allowed_metrics"]).isdisjoint(artifact["diagnostic_only_metrics"])
    assert set(artifact["allowed_metrics"]).isdisjoint(artifact["diagnostic_excluded_metrics"])


def test_recall_registry_artifact_missing_sidecars_stays_inconclusive(tmp_path):
    metrics_path = tmp_path / "metrics.json"
    frozen_candidates_path = tmp_path / "frozen_candidates.jsonl"
    metrics_path.write_text('{"ok": true}', encoding="utf-8")
    frozen_candidates_path.write_text('{"user_id": "u1", "item_id": "i1"}\n', encoding="utf-8")
    metrics = {
        "evaluation_mode": "valid_test",
        "users_total": 1,
        "users_with_holdout": 1,
        "hit_rate_denominator": "users_with_holdout",
        "fallback_rate": 0.0,
        "empty_candidate_users": 0,
        "empty_candidate_rate": 0.0,
        "frozen_candidates_signature": {"hash": "abc", "user_count": 1, "candidate_count": 1},
        "latency": {"candidate_generation_avg_seconds": 0.01, "candidate_generation_p95_seconds": 0.02},
        "source_overlap": {"source_pair_jaccard": {"category+itemcf_weak": 0.5}},
    }
    missing_latency_path = tmp_path / "missing_latency.json"
    fallback_path = tmp_path / "recall_fallback_report.json"
    overlap_path = tmp_path / "recall_overlap_source_contribution.json"
    fallback_path.write_text('{"ok": true}', encoding="utf-8")
    overlap_path.write_text('{"ok": true}', encoding="utf-8")

    artifact = _recall_registry_artifact(
        {"strategy_name": "phase_b", "candidate_pool_size": 200},
        metrics,
        metrics_path,
        frozen_candidates_path,
        {
            "latency": missing_latency_path,
            "fallback": fallback_path,
            "overlap_source_contribution": overlap_path,
        },
    )

    assert artifact["gate_status"] == "INCONCLUSIVE_MISSING_ARTIFACT"
    assert "latency" in artifact["missing_promotion_required_artifacts"]
    assert "ablation" in artifact["missing_promotion_required_artifacts"]
    assert artifact["promotion_required_artifacts"]["latency"] == {
        "available": False,
        "path": str(missing_latency_path),
        "sha256": None,
        "metrics": {
            "candidate_generation_avg_seconds": 0.01,
            "candidate_generation_p95_seconds": 0.02,
        },
    }
    assert artifact["missing_promotion_next_actions"]["latency"] == "Produce and attach the missing recall promotion artifact before promotion."
    assert artifact["missing_promotion_next_actions"]["ablation"] == "Run the dedicated recall ablation workflow and attach its evidence manifest before promotion."


def test_recall_registry_validator_accepts_source_alias_and_rejects_forbidden_metric_overlap(tmp_path, monkeypatch):
    metrics_path = tmp_path / "metrics.json"
    manifest_path = tmp_path / "manifest.yaml"
    metrics_path.write_text('{"ok": true}', encoding="utf-8")
    manifest_path.write_text("schema_version: test\n", encoding="utf-8")
    monkeypatch.setattr(recall_registry_validator, "REPO_ROOT", tmp_path)
    schema = {
        "required_fields": [
            "experiment_id",
            "source_name",
            "lane",
            "scope_contract",
            "allowed_metrics",
            "forbidden_metrics",
            "artifact_manifest_path",
            "metrics_path",
        ],
        "enums": {
            "lane": ["observation", "promotion"],
            "allowed_metric_names": ["empty_candidate_rate", "candidate_hit_rate"],
            "forbidden_metric_names": [
                "hit_rate_at_k",
                "ndcg",
                "mrr",
                "map",
                "topk_hit_rate",
                "ranking_gap_pool_has_target",
                "ltr_score",
                "rerank_score",
                "ctr",
                "cvr",
                "gmv",
            ],
        },
    }
    canonical_sources = recall_registry_validator._canonical_sources({
        "sources": [
            {"source_id": "semantic_title_category_expansion", "source_aliases": ["semantic_title"]},
        ],
    })
    base_record = {
        "experiment_id": "recall_alias_smoke",
        "source_name": "semantic_title",
        "lane": "observation",
        "scope_contract": "recall_only",
        "allowed_metrics": ["empty_candidate_rate", "candidate_hit_rate"],
        "forbidden_metrics": [
            "hit_rate_at_k",
            "ndcg",
            "mrr",
            "map",
            "topk_hit_rate",
            "ranking_gap_pool_has_target",
            "ltr_score",
            "rerank_score",
            "ctr",
            "cvr",
            "gmv",
        ],
        "diagnostic_only_metrics": ["hit_rate_at_k", "topk_hit_rate"],
        "diagnostic_excluded_metrics": ["ranking_gap_pool_has_target", "ltr_score", "rerank_score", "ctr", "cvr", "gmv"],
        "artifact_manifest_path": "manifest.yaml",
        "metrics_path": "metrics.json",
    }

    assert recall_registry_validator._validate_record(base_record, schema, canonical_sources) == []
    rejected = recall_registry_validator._validate_record(
        base_record | {"allowed_metrics": ["empty_candidate_rate", "hit_rate_at_k"]},
        schema,
        canonical_sources,
    )
    assert any("allowed_metrics and forbidden_metrics overlap" in error for error in rejected)
    assert any("diagnostic-only metrics cannot be allowed recall gate metrics" in error for error in rejected)
    diagnostic_rejected = recall_registry_validator._validate_record(
        base_record | {"allowed_metrics": ["empty_candidate_rate", "candidate_hit_rate", "ranking_gap_pool_has_target"]},
        schema,
        canonical_sources,
    )
    assert any("unknown allowed_metrics" in error for error in diagnostic_rejected)
    assert any("diagnostic-only metrics cannot be allowed recall gate metrics" in error for error in diagnostic_rejected)

    promotion_artifact_paths = {
        "source_coverage_path": "source_coverage.csv",
        "pool_curve_path": "pool_curve.csv",
        "ablation_report_path": "ablation.json",
        "overlap_report_path": "overlap.json",
        "latency_report_path": "latency.json",
        "fallback_report_path": "fallback.json",
    }
    for relative_path in promotion_artifact_paths.values():
        (tmp_path / relative_path).write_text("ok", encoding="utf-8")
    manifest_path.write_text(yaml.safe_dump({"source_artifact_paths": promotion_artifact_paths}), encoding="utf-8")
    promotion_schema = schema | {"promotion_required_paths": ["frozen_candidates_path", *promotion_artifact_paths]}
    promotion_record = base_record | {"lane": "promotion", "gate_status": "PASS_PROMOTE_DEFAULT"}

    missing_frozen = recall_registry_validator._validate_record(promotion_record, promotion_schema, canonical_sources)
    assert any("promotion lane missing required artifact frozen_candidates_path" in error for error in missing_frozen)

    missing_ablation_manifest = promotion_artifact_paths | {"frozen_candidates_path": "frozen_candidates.parquet"}
    missing_ablation_manifest.pop("ablation_report_path")
    (tmp_path / "frozen_candidates.parquet").write_text("ok", encoding="utf-8")
    manifest_path.write_text(yaml.safe_dump({"source_artifact_paths": missing_ablation_manifest}), encoding="utf-8")
    missing_ablation = recall_registry_validator._validate_record(promotion_record, promotion_schema, canonical_sources)
    assert any("promotion lane missing required artifact ablation_report_path" in error for error in missing_ablation)

    scope_drift = recall_registry_validator._validate_record(
        base_record | {"decision_reason": "promotion because ndcg improved", "gate_status": "PASS_PROMOTE_DEFAULT"},
        schema,
        canonical_sources,
    )
    assert any("decision_reason uses diagnostic-only metrics without INVALID_SCOPE_DRIFT" in error for error in scope_drift)
    gate_reason_drift = recall_registry_validator._validate_record(
        base_record | {"gate_reason": "promote due to LTR and CTR lift", "gate_status": "PASS_PROMOTE_DEFAULT"},
        schema,
        canonical_sources,
    )
    assert any("gate_reason uses diagnostic-only metrics without INVALID_SCOPE_DRIFT" in error for error in gate_reason_drift)
    promotion_evidence_drift = recall_registry_validator._validate_record(
        base_record | {
            "promotion_required_artifacts": {"ranking": {"available": True, "metrics": {"hit_rate_at_k": 0.2, "ctr": 0.1}}},
            "allowed_evidence": {"rerank_score": 0.3},
        },
        schema,
        canonical_sources,
    )
    assert any("promotion_required_artifacts contains diagnostic-only promotion evidence" in error for error in promotion_evidence_drift)
    assert any("allowed_evidence contains diagnostic-only promotion evidence" in error for error in promotion_evidence_drift)
    assert recall_registry_validator._validate_record(
        base_record | {"decision_reason": "promotion because ndcg improved", "gate_status": "INVALID_SCOPE_DRIFT"},
        schema,
        canonical_sources,
    ) == []


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


def test_frozen_candidate_export_rows_include_user_and_candidate_fields():
    rows = _frozen_candidate_export_rows({
        "u1": merge_candidates([
            RecallCandidate(
                "item-a",
                "itemcf",
                2.5,
                category="Audio",
                metadata={"reason": "seed_overlap"},
            )
        ])
    })

    assert rows == [
        {
            "user_id": "u1",
            "candidate_rank": 1,
            "item_id": "item-a",
            "sources": ["itemcf"],
            "source_scores": {"itemcf": 2.5},
            "category": "Audio",
            "metadata": {"reason": "seed_overlap"},
        }
    ]



def test_phase_1_23_pool200_isolation_configs_keep_frozen_pool_contract():
    root = Path(__file__).resolve().parents[1]
    variant_names = [name for name, _ in PHASE_1_23_VARIANTS]

    assert variant_names[0] == "no_rerank_baseline"
    assert set(variant_names) == {"no_rerank_baseline", "ranking_v2", "item_feature_rerank", "source_aware_fusion"}
    for variant_name, config_path in PHASE_1_23_VARIANTS:
        config = load_config(config_path)
        assert config_path.exists()
        assert config["candidate_pool_size"] == 200
        assert config["pool200_fixed_baseline"]["candidate_pool_size"] == 200
        assert config["phase_1_23_isolation"]["candidate_pool_size"] == 200
        assert config["export_frozen_candidates"] is True
        assert config["pool200_fixed_baseline"]["frozen_candidate_export"] is True
        assert config["phase_1_23_isolation"]["fixed_recall_config_path"] == "configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml"
        assert str(config_path).startswith(str(root / "configs"))
        if variant_name == "no_rerank_baseline":
            assert config["ranking_v2"]["enabled"] is False
            assert config["item_feature_rerank"]["enabled"] is False
            assert config["source_aware_fusion"]["enabled"] is False
        else:
            assert config["phase_1_23_isolation"]["baseline_config_path"] == "configs/ranking/phase_1_23/phase_1_23_pool200_no_rerank_baseline.yaml"



def test_phase_1_23_runner_writes_batch0_pool200_artifact_and_registry(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    variants = [(name, tmp_path / f"{name}.yaml") for name, _ in PHASE_1_23_VARIANTS]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        return {
            "metrics": {
                "hit_rate_at_k": 0.1,
                "ndcg_at_k": 0.1,
                "mrr_at_k": 0.1,
                "recall_at_pool": 0.5,
                "users_with_holdout": 1,
                "candidate_hit_users": 1,
                "candidate_hit_rate_at_pool": 1.0,
                "candidate_count_avg": 2.0,
                "fallback_rate": 0.0,
                "config_summary": {"candidate_pool_size": 200, "top_k": 5},
            },
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    for name in ("metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"):
        for variant_name, _ in variants:
            path = tmp_path / "comparison" / variant_name / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(phase_1_23_runner, "VARIANTS", variants)
    monkeypatch.setattr(phase_1_23_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_1_23_runner, "parse_args", lambda: type("Args", (), {"output_dir": str(tmp_path / "comparison"), "limit_users": 2})())

    phase_1_23_runner.main()

    comparison = json.loads((tmp_path / "comparison" / "comparison.json").read_text(encoding="utf-8"))
    batch0 = comparison["batch0_pool200_artifact"]
    baseline_registry = comparison["variants"]["no_rerank_baseline"]["ranking_experiment_registry"]
    assert batch0["schema_version"] == "pool200_batch0_artifact_v1"
    assert batch0["candidate_pool_size"] == 200
    assert batch0["top_k"] == 5
    assert batch0["split_metadata"]["evaluation_splits"] == ["valid", "test"]
    assert batch0["pool100_reuse_policy"]["reusable_for_pool200_promotion"] is False
    assert baseline_registry["candidate_pool_size"] == 200
    assert baseline_registry["top_k"] == 5
    assert baseline_registry["frozen_candidate_artifact"]["hash"] == frozen_candidate_artifact(frozen_rows)["hash"]
    assert comparison["artifact_inspection"]["status"] == "PASS"



def test_phase_1_24_semantic_rescue_config_keeps_pool200_contract_and_isolated_positive_weight():
    root = Path(__file__).resolve().parents[1]
    variant_names = [name for name, _ in PHASE_1_24_VARIANTS]

    assert variant_names == ["no_rerank_baseline", "semantic_near_miss_rescue"]
    baseline = load_config(root / "configs/ranking/phase_1_23/phase_1_23_pool200_no_rerank_baseline.yaml")
    rescue = load_config(root / "configs/ranking/phase_1_24/phase_1_24_pool200_semantic_near_miss_rescue.yaml")

    assert rescue["candidate_pool_size"] == baseline["candidate_pool_size"] == 200
    assert rescue["pool200_fixed_baseline"]["candidate_pool_size"] == 200
    assert rescue["phase_1_24_isolation"]["fixed_recall_config_path"] == "configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml"
    assert rescue["phase_1_24_isolation"]["baseline_config_path"] == "configs/ranking/phase_1_23/phase_1_23_pool200_no_rerank_baseline.yaml"
    assert rescue["export_frozen_candidates"] is True
    assert rescue["pool200_fixed_baseline"]["frozen_candidate_export"] is True
    assert rescue["ranking_v2"]["enabled"] is False
    assert rescue["source_aware_fusion"]["enabled"] is False
    assert rescue["item_feature_rerank"]["enabled"] is True
    assert rescue["item_feature_rerank"]["weights"] == {"semantic_only": 0.8}
    assert rescue["output_dir"] != baseline["output_dir"]
    assert rescue["report_path"] != baseline["report_path"]



def test_phase_1_25_pool200_configs_use_same_frozen_pool_and_finite_additive_grid():
    root = Path(__file__).resolve().parents[1]
    variant_names = [name for name, _ in PHASE_1_25_VARIANTS]
    baseline = load_config(root / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml")
    allowed_grid = baseline["phase_1_25_isolation"]["allowed_normalized_additive_grid"]

    assert variant_names[0] == "same_run_baseline"
    assert set(variant_names) == {
        "same_run_baseline",
        "source_signal_0_2",
        "source_signal_0_4",
        "item_feature_0_2",
        "item_feature_0_4",
        "balanced_source_item_0_2",
        "freshness_quality_0_1",
        "near_miss_tiebreak_0_05",
    }
    for variant_name, config_path in PHASE_1_25_VARIANTS:
        config = load_config(config_path)
        assert config_path.exists()
        assert config["candidate_pool_size"] == baseline["candidate_pool_size"] == 200
        assert config["top_k"] == baseline["top_k"] == 5
        assert config["pool200_fixed_baseline"]["candidate_pool_size"] == 200
        assert config["pool200_fixed_baseline"]["frozen_candidate_export"] is True
        assert config["phase_1_25_isolation"]["fixed_recall_config_path"] == "configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml"
        assert config["phase_1_25_isolation"]["baseline_config_path"] == "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
        assert config["export_frozen_candidates"] is True
        assert config["ranking_v2"]["enabled"] is False
        assert config["item_feature_rerank"]["enabled"] is False
        assert config["source_aware_fusion"]["enabled"] is False
        assert config["ltr_model"]["enabled"] is False
        weights = config["normalized_additive_ranking"]["weights"]
        assert config["normalized_additive_ranking"]["enabled"] is (variant_name != "same_run_baseline")
        assert weights == config["phase_1_25_isolation"]["normalized_additive_weights"]
        for key, value in weights.items():
            assert value in allowed_grid[key]
        assert config["clean_dir"] == baseline["clean_dir"]
        assert config["views_dir"] == baseline["views_dir"]
        assert config["candidate_source_minimums"] == baseline["candidate_source_minimums"]



def test_phase_1_26_runner_writes_registry_entries_to_comparison(tmp_path, monkeypatch):
    frozen_rows_by_variant = {
        "same_run_baseline": [
            {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
            {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
        ],
        "source_signal_0_2": [
            {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
            {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
        ],
    }
    variants = [(name, tmp_path / f"{name}.yaml") for name in frozen_rows_by_variant]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        variant_name = Path(config_overrides["output_dir"]).name
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows_by_variant[variant_name])
        metrics = {
            "hit_rate_at_k": 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "candidate_hit_rate_at_pool": 0.5,
            "fallback_rate": 0.0,
            "candidate_count_avg": 2.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5, "ltr_model": {"enabled": False}},
        }
        if variant_name == "source_signal_0_2":
            metrics = metrics | {"hit_rate_at_k": 0.2, "candidate_hit_missed_topk_users": 2}
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    monkeypatch.setattr(phase_1_25_runner, "VARIANTS", variants)
    monkeypatch.setattr(phase_1_25_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_1_25_runner, "parse_args", lambda: type("Args", (), {"output_dir": str(tmp_path / "comparison"), "limit_users": 2})())

    phase_1_25_runner.main()

    comparison = json.loads((tmp_path / "comparison" / "comparison.json").read_text(encoding="utf-8"))
    registry = comparison["ranking_experiment_registry"]
    assert len(registry) == 2
    variant_entry = comparison["variants"]["source_signal_0_2"]["ranking_experiment_registry"]
    assert variant_entry["schema_version"] == "ranking_experiment_registry_v1"
    assert variant_entry["promotion_scope"] == "ranking_on_frozen_recall_pool_only"
    assert variant_entry["candidate_pool_size"] == 200
    assert variant_entry["top_k"] == 5
    assert variant_entry["feature_contract_version"] == "ranking_feature_contract_v1"
    assert variant_entry["feature_contract"]["promotion_scope"] == "ranking_on_frozen_recall_pool_only"
    assert variant_entry["feature_contract_gate_summary"]["schema_version"] == "ranking_feature_contract_gate_v1"
    assert variant_entry["feature_contract_gate_summary"]["status"] == "NOT_APPLICABLE"
    assert variant_entry["leakage_gate_summary"]["schema_version"] == "ranking_feature_leakage_gate_v1"
    assert variant_entry["leakage_gate_summary"]["status"] == "NOT_APPLICABLE"
    assert variant_entry["status"] == comparison["variants"]["source_signal_0_2"]["strict_status"]
    assert variant_entry["frozen_candidate_artifact"]["hash"] == frozen_candidate_artifact(frozen_rows_by_variant["source_signal_0_2"])["hash"]



def test_phase_1_25_runner_row_gate_requires_freeze_and_hash_match():
    valid_row = {
        "status": "VALID",
        "strict_status": {"status": "PARTIAL diagnostic-only"},
        "frozen_candidate_comparison": {"match": True},
    }
    assert _row_is_valid(valid_row) is True
    assert _row_is_valid(valid_row | {"frozen_candidate_comparison": {"match": False}}) is False
    assert _row_is_valid(valid_row | {"status": "INVALID"}) is False
    assert _row_is_valid(valid_row | {"strict_status": {"status": "INVALID/STOP"}}) is False



def test_phase_1_28_runner_writes_ltr_gate_metadata_and_diagnostic_status(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        ltr_enabled = bool(config_overrides.get("ltr_model", {}).get("enabled", False))
        metrics = {
            "hit_rate_at_k": 0.2 if ltr_enabled else 0.1,
            "ndcg_at_k": 0.2 if ltr_enabled else 0.1,
            "mrr_at_k": 0.2 if ltr_enabled else 0.1,
            "map_at_k": 0.2 if ltr_enabled else 0.1,
            "candidate_hit_missed_topk_users": 2 if ltr_enabled else 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5, "ltr_model": {"enabled": ltr_enabled}},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    def fake_train_ltr_ranker(config_path, *, output_dir=None, limit_users=None, config_overrides=None):
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        model_path = output_path / "ltr_model.json"
        metrics_path = output_path / "ltr_train_metrics.json"
        rows_path = output_path / "ltr_candidate_rows.jsonl"
        model_path.write_text("{}", encoding="utf-8")
        metrics = {
            "evaluation_mode": "leave_one_positive_out",
            "rows": 2,
            "positive_rows": 1,
            "negative_rows": 1,
            "feature_contract_gate": {
                "schema_version": "ranking_feature_contract_gate_v1",
                "status": "PASS",
                "checked_rows": 2,
                "checked_feature_count": 2,
                "reasons": [],
            },
            "leakage_gate": {
                "schema_version": "ranking_feature_leakage_gate_v1",
                "status": "PASS",
                "checked_rows": 2,
                "label_source": "leave_one_positive_out_train",
                "training_split": "train",
                "reasons": [],
            },
        }
        return {"model_path": str(model_path), "metrics_path": str(metrics_path), "candidate_rows_path": str(rows_path), "model": {}, "metrics": metrics}

    monkeypatch.setattr(phase_1_28_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_1_28_runner, "train_ltr_ranker", fake_train_ltr_ranker)
    monkeypatch.setattr(phase_1_28_runner, "parse_args", lambda: type("Args", (), {"output_dir": str(tmp_path / "comparison"), "limit_users": 2})())

    phase_1_28_runner.main()

    comparison = json.loads((tmp_path / "comparison" / "comparison.json").read_text(encoding="utf-8"))
    assert comparison["phase"] == "phase_1_28_lightweight_learned_ranker"
    assert comparison["baseline_variant"] == "same_run_baseline"
    assert comparison["ltr_variants"] == ["pointwise_logistic_lopo_ltr", "pairwise_perceptron_lopo_ltr"]
    assert comparison["all_variants_valid"] is True
    assert set(comparison["ltr_training"]) == {"pointwise_logistic_lopo_ltr", "pairwise_perceptron_lopo_ltr"}
    for variant_name in comparison["ltr_variants"]:
        ltr_entry = comparison["variants"][variant_name]["ranking_experiment_registry"]
        assert ltr_entry["schema_version"] == "ranking_experiment_registry_v1"
        assert ltr_entry["candidate_pool_size"] == 200
        assert ltr_entry["top_k"] == 5
        assert ltr_entry["feature_contract_version"] == "ranking_feature_contract_v1"
        assert ltr_entry["feature_contract_gate_summary"]["status"] == "PASS"
        assert ltr_entry["leakage_gate_summary"]["status"] == "PASS"
        assert ltr_entry["leakage_gate_summary"]["label_source"] == "leave_one_positive_out_train"
        assert ltr_entry["status"]["status"] == "PARTIAL diagnostic-only"
        assert ltr_entry["status"]["diagnostic_only"] is True
        assert ltr_entry["status"]["promotable"] is False
        assert "ltr_model_enabled" in ltr_entry["status"]["reasons"]



def test_phase_2_shallow_learned_runner_keeps_lopo_diagnostic_and_blocks_promotion(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        ltr_enabled = bool(config_overrides.get("ltr_model", {}).get("enabled", False))
        metrics = {
            "hit_rate_at_k": 0.2 if ltr_enabled else 0.1,
            "ndcg_at_k": 0.2,
            "mrr_at_k": 0.2,
            "map_at_k": 0.2,
            "candidate_hit_missed_topk_users": 2 if ltr_enabled else 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5, "ltr_model": {"enabled": ltr_enabled}},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    def fake_train_ltr_ranker(config_path, *, output_dir, limit_users=None, config_overrides=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "ltr_model.json"
        metrics_path = output_dir / "ltr_train_metrics.json"
        rows_path = output_dir / "ltr_candidate_rows.jsonl"
        model_path.write_text("{}", encoding="utf-8")
        metrics_path.write_text("{}", encoding="utf-8")
        rows_path.write_text("{}", encoding="utf-8")
        model_type = config_overrides["ltr_training"]["model_type"]
        return {
            "model_path": str(model_path),
            "metrics_path": str(metrics_path),
            "candidate_rows_path": str(rows_path),
            "model": {},
            "metrics": {
                "evaluation_mode": "leave_one_positive_out",
                "model_type": f"{model_type}_ltr_v1",
                "rows": 2,
                "positive_rows": 1,
                "negative_rows": 1,
                "feature_contract_gate": {"schema_version": "ranking_feature_contract_gate_v1", "status": "PASS", "checked_rows": 2, "checked_feature_count": 2, "reasons": []},
                "leakage_gate": {"schema_version": "ranking_feature_leakage_gate_v1", "status": "PASS", "checked_rows": 2, "label_source": "leave_one_positive_out_train", "training_split": "train", "reasons": []},
            },
        }

    monkeypatch.setattr(phase_2_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_2_runner, "train_ltr_ranker", fake_train_ltr_ranker)

    comparison = phase_2_runner.run_phase_2_shallow_learned_ranker(tmp_path / "phase2", limit_users=2)

    assert comparison["phase"] == "phase_2_shallow_learned_ranker"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["promotion_policy"]["lopo_training"] == "diagnostic_only"
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["final_decision"]["status"] == "BASELINE_FINAL_ROUTE"
    diagnostic_rows = [row for row in comparison["runs"] if row["lane"] == "diagnostic"]
    assert {row["candidate_id"] for row in diagnostic_rows} == {"pointwise_logistic_lopo_diagnostic", "pairwise_perceptron_lopo_diagnostic"}
    assert all(row["promotion_eligible"] is False and row["diagnostic_only"] is True for row in diagnostic_rows)
    assert all("lopo_training_diagnostic_only" in row["strict_status"]["reasons"] for row in diagnostic_rows)
    assert all(row["candidate_pool_size"] == 200 and row["top_k"] == 5 for row in comparison["runs"])
    assert all(row["frozen_candidate_status"] == "PASS" for row in comparison["runs"])
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    assert registry_by_method["pointwise_logistic_lopo_diagnostic"]["state"] == "diagnostic"
    assert registry_by_method["pairwise_perceptron_lopo_diagnostic"]["state"] == "diagnostic"
    assert registry_by_method["linear_ranker_valid_test_promotion"]["state"] == "blocked"
    assert "no_independent_valid_test_training_split_for_promotion" in registry_by_method["linear_ranker_valid_test_promotion"]["reasons"]
    assert comparison["ltr_training"]["pointwise_logistic_lopo_diagnostic"]["metrics"]["feature_contract_gate"]["status"] == "PASS"
    assert comparison["ltr_training"]["pairwise_perceptron_lopo_diagnostic"]["metrics"]["leakage_gate"]["status"] == "PASS"



def test_phase_5_sequence_ranker_reports_data_readiness_and_blocks_long_sequence_models(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        metrics = {
            "hit_rate_at_k": 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    readiness = {
        "schema_version": "sequence_ranker_data_readiness_v1",
        "sequence_path": "mock/user_sequences.train.jsonl",
        "users": 2340,
        "positive_len_min": 0,
        "positive_len_max": 524,
        "positive_len_avg": 5.7585,
        "sequence_len_avg": 6.8068,
        "users_with_positive_len_ge_2": 1382,
        "users_with_positive_len_ge_5": 623,
        "users_with_positive_len_ge_10": 280,
        "positive_len_ge_2_rate": 0.5906,
        "positive_len_ge_5_rate": 0.2662,
        "positive_len_ge_10_rate": 0.1197,
        "timestamp_coverage_rate": 0.9111,
        "timestamp_ordered_rate": 1.0,
        "timestamp_alignment_rate": 1.0,
        "short_sequence_diagnostic_ready": True,
        "long_sequence_model_ready": False,
        "future_interaction_policy": "leave_one_positive_out_or_train_history_only_required",
        "reasons": ["long_sequence_coverage_below_threshold"],
    }

    monkeypatch.setattr(phase_5_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_5_runner, "_sequence_data_readiness", lambda limit_users=None: readiness)

    comparison = phase_5_runner.run_phase_5_sequence_ranker(tmp_path / "phase5", limit_users=2)

    assert comparison["phase"] == "phase_5_sequence_attention_ranker"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["data_readiness"]["short_sequence_diagnostic_ready"] is True
    assert comparison["data_readiness"]["long_sequence_model_ready"] is False
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["final_decision"]["status"] == "BASELINE_FINAL_ROUTE"
    assert comparison["promotion_policy"]["long_sequence_models_blocked_until_data_ready"] is True
    assert all(row["candidate_pool_size"] == 200 and row["top_k"] == 5 for row in comparison["runs"])
    assert all(row["frozen_candidate_status"] == "PASS" for row in comparison["runs"])
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    assert registry_by_method["session_aware_reranker_short_history_diagnostic"]["state"] == "diagnostic"
    assert registry_by_method["attention_over_user_history_diagnostic"]["state"] == "diagnostic"
    assert registry_by_method["session_aware_reranker_short_history_diagnostic"]["promotion_eligible"] is False
    assert registry_by_method["din_sequence_ranker"]["state"] == "blocked"
    assert registry_by_method["dien_sequence_ranker"]["state"] == "blocked"
    assert registry_by_method["bst_sequence_ranker"]["state"] == "blocked"
    assert registry_by_method["sim_sequence_ranker"]["state"] == "blocked"
    assert "long_sequence_coverage_below_threshold" in registry_by_method["din_sequence_ranker"]["reasons"]



def test_phase_6_semantic_two_tower_ranker_preserves_frozen_pool_and_blocks_vector_adapters(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]
    calls = []

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        calls.append(config_overrides)
        variant_name = output_dir.name
        metrics = {
            "hit_rate_at_k": 0.1 if variant_name == "same_run_baseline" else 0.1001,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    monkeypatch.setattr(phase_6_runner, "run_hybrid_demo", fake_run_hybrid_demo)

    comparison = phase_6_runner.run_phase_6_semantic_two_tower_ranker(tmp_path / "phase6", limit_users=2)

    assert comparison["phase"] == "phase_6_semantic_two_tower_ranker"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["promotion_policy"]["candidate_pool_regeneration_forbidden"] is True
    assert comparison["feature_readiness"]["semantic_source_score_available"] is True
    assert comparison["feature_readiness"]["two_tower_source_score_available"] is True
    assert comparison["feature_readiness"]["candidate_level_vector_adapter_available"] is False
    assert all(row["candidate_pool_size"] == 200 and row["top_k"] == 5 for row in comparison["runs"])
    assert all(row["frozen_candidate_status"] == "PASS" for row in comparison["runs"])
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    assert registry_by_method["same_run_baseline"]["promotion_eligible"] is True
    assert registry_by_method["semantic_score_feature_rerank"]["state"] == "diagnostic"
    assert registry_by_method["two_tower_score_feature_rerank"]["state"] == "diagnostic"
    assert registry_by_method["semantic_two_tower_cross_feature_fusion"]["state"] == "diagnostic"
    assert registry_by_method["dssm_artifact_candidate_rerank"]["state"] == "blocked"
    assert registry_by_method["raw_vector_similarity_feature_fusion"]["state"] == "blocked"
    assert "candidate_level_vector_feature_adapter_missing" in registry_by_method["raw_vector_similarity_feature_fusion"]["reasons"]
    assert any(call.get("rank_weights", {}).get("semantic") == 1.3 for call in calls)
    assert any(call.get("rank_weights", {}).get("two_tower") == 1.3 for call in calls)
    assert any(call.get("source_aware_fusion", {}).get("enabled") is True for call in calls)



def test_phase_7_8_future_online_gate_blocks_online_methods_from_offline_promotion(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        metrics = {
            "hit_rate_at_k": 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    monkeypatch.setattr(phase_7_8_runner, "run_hybrid_demo", fake_run_hybrid_demo)

    comparison = phase_7_8_runner.run_phase_7_8_future_online_gate(tmp_path / "phase78", limit_users=2)

    assert comparison["phase"] == "phase_7_8_future_online_gate"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["promotion_policy"]["online_metrics_current_promotion_forbidden"] is True
    readiness = comparison["future_online_readiness"]
    assert readiness["phase_7"]["current_offline_promotion_eligible"] is False
    assert readiness["phase_8"]["current_offline_promotion_eligible"] is False
    assert {"ctr", "cvr", "gmv", "p95", "slo"}.issubset(set(readiness["forbidden_current_evidence"]))
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    for method in ["esmm_ctr_cvr_ranker", "mmoe_multi_task_ranker", "ple_multi_task_ranker", "contextual_bandit_ranker", "rl_grpo_preference_ranker"]:
        assert registry_by_method[method]["state"] == "blocked"
        assert registry_by_method[method]["promotion_eligible"] is False
        assert "online_metrics_forbidden_as_current_offline_evidence" in registry_by_method[method]["reasons"]
    assert comparison["runs"][0]["frozen_candidate_status"] == "PASS"



def test_phase_4_neural_ranker_keeps_cuda_training_diagnostic_only(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        metrics = {
            "hit_rate_at_k": 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    def fake_train_ltr_ranker(config_path, *, output_dir, limit_users=None, config_overrides=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "ltr_model.json"
        metrics_path = output_dir / "ltr_train_metrics.json"
        rows_path = output_dir / "ltr_candidate_rows.jsonl"
        model_path.write_text("{}", encoding="utf-8")
        metrics_path.write_text("{}", encoding="utf-8")
        write_jsonl(
            rows_path,
            [
                {"user_id": "u1", "item_id": "a", "label": 1, "features": {"score_semantic": 1.0, "source_count": 2.0}},
                {"user_id": "u1", "item_id": "b", "label": 0, "features": {"score_semantic": 0.2, "source_count": 1.0}},
            ],
        )
        return {
            "model_path": str(model_path),
            "metrics_path": str(metrics_path),
            "candidate_rows_path": str(rows_path),
            "model": {},
            "metrics": {
                "evaluation_mode": "leave_one_positive_out",
                "model_type": "pointwise_logistic_ltr_v1",
                "rows": 2,
                "positive_rows": 1,
                "negative_rows": 1,
                "feature_contract_gate": {"schema_version": "ranking_feature_contract_gate_v1", "status": "PASS", "checked_rows": 2, "checked_feature_count": 2, "reasons": []},
                "leakage_gate": {"schema_version": "ranking_feature_leakage_gate_v1", "status": "PASS", "checked_rows": 2, "label_source": "leave_one_positive_out_train", "training_split": "train", "reasons": []},
            },
        }

    def fake_run_neural_diagnostics(output_dir, candidate_row_export, dependency_status):
        return {
            "mlp_pointwise_cuda_diagnostic": {
                "model_path": str(tmp_path / "mlp.pt"),
                "metrics_path": str(tmp_path / "mlp.json"),
                "metrics": {"status": "PASS", "promotion_eligible": False, "diagnostic_only": True, "reasons": ["diagnostic_only", "serving_adapter_missing"], "device": "cuda", "rows": 2},
            },
            "ranknet_pairwise_cuda_diagnostic": {
                "model_path": str(tmp_path / "ranknet.pt"),
                "metrics_path": str(tmp_path / "ranknet.json"),
                "metrics": {"status": "PASS", "promotion_eligible": False, "diagnostic_only": True, "reasons": ["diagnostic_only", "promotion_adr_required"], "device": "cuda", "rows": 2},
            },
        }

    monkeypatch.setattr(phase_4_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_4_runner, "train_ltr_ranker", fake_train_ltr_ranker)
    monkeypatch.setattr(phase_4_runner, "_dependency_status", lambda: {"torch_available": True, "tensorflow_available": False, "keras_available": False, "torch_version": "2.x", "cuda_available": True, "cuda_device_count": 1, "cuda_device_name": "cuda-test"})
    monkeypatch.setattr(phase_4_runner, "_run_neural_diagnostics", fake_run_neural_diagnostics)

    comparison = phase_4_runner.run_phase_4_neural_ranker(tmp_path / "phase4", limit_users=2)

    assert comparison["phase"] == "phase_4_neural_ranker"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["final_decision"]["status"] == "BASELINE_FINAL_ROUTE"
    assert comparison["promotion_policy"]["neural_rankers_are_diagnostic_by_default"] is True
    assert comparison["candidate_row_export"]["promotion_eligible"] is False
    assert all(row["candidate_pool_size"] == 200 and row["top_k"] == 5 for row in comparison["runs"])
    assert all(row["frozen_candidate_status"] == "PASS" for row in comparison["runs"])
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    assert registry_by_method["mlp_pointwise_cuda_diagnostic"]["state"] == "diagnostic"
    assert registry_by_method["ranknet_pairwise_cuda_diagnostic"]["state"] == "diagnostic"
    assert registry_by_method["mlp_pointwise_cuda_diagnostic"]["promotion_eligible"] is False
    assert registry_by_method["mlp_pointwise_cuda_diagnostic"]["diagnostic_only"] is True
    assert registry_by_method["mlp_pointwise_cuda_diagnostic"]["gpu_resource"]["status"] == "gpu_enabled"
    assert registry_by_method["lambdarank_cuda_diagnostic"]["state"] == "blocked"
    assert registry_by_method["listnet_listmle_cuda_diagnostic"]["state"] == "blocked"
    assert registry_by_method["wide_deep_deepfm_dcn_xdeepfm_cuda_diagnostic"]["state"] == "blocked"



def test_phase_3_tree_ranker_blocks_missing_dependencies_and_exports_candidate_rows(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        metrics = {
            "hit_rate_at_k": 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    def fake_train_ltr_ranker(config_path, *, output_dir, limit_users=None, config_overrides=None):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        model_path = output_dir / "ltr_model.json"
        metrics_path = output_dir / "ltr_train_metrics.json"
        rows_path = output_dir / "ltr_candidate_rows.jsonl"
        model_path.write_text("{}", encoding="utf-8")
        metrics_path.write_text("{}", encoding="utf-8")
        rows_path.write_text('{"user_id":"u1","item_id":"a","label":1}\n', encoding="utf-8")
        return {
            "model_path": str(model_path),
            "metrics_path": str(metrics_path),
            "candidate_rows_path": str(rows_path),
            "model": {},
            "metrics": {
                "evaluation_mode": "leave_one_positive_out",
                "model_type": "pointwise_logistic_ltr_v1",
                "rows": 1,
                "positive_rows": 1,
                "negative_rows": 0,
                "feature_contract_gate": {"schema_version": "ranking_feature_contract_gate_v1", "status": "PASS", "checked_rows": 1, "checked_feature_count": 2, "reasons": []},
                "leakage_gate": {"schema_version": "ranking_feature_leakage_gate_v1", "status": "PASS", "checked_rows": 1, "label_source": "leave_one_positive_out_train", "training_split": "train", "reasons": []},
            },
        }

    monkeypatch.setattr(phase_3_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_3_runner, "train_ltr_ranker", fake_train_ltr_ranker)
    monkeypatch.setattr(phase_3_runner, "_dependency_status", lambda: {"sklearn": False, "xgboost": False, "lightgbm": False})

    comparison = phase_3_runner.run_phase_3_tree_ranker(tmp_path / "phase3", limit_users=2)

    assert comparison["phase"] == "phase_3_tree_lambdamart_ranker"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["final_decision"]["status"] == "BASELINE_FINAL_ROUTE"
    assert comparison["promotion_policy"]["stand_in_rankers_forbidden_as_promotion_evidence"] is True
    assert comparison["candidate_row_export"]["candidate_rows_path"]
    assert comparison["candidate_row_export"]["promotion_eligible"] is False
    assert "candidate_row_export_only" in comparison["candidate_row_export"]["reasons"]
    assert all(row["candidate_pool_size"] == 200 and row["top_k"] == 5 for row in comparison["runs"])
    assert all(row["frozen_candidate_status"] == "PASS" for row in comparison["runs"])
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    assert registry_by_method["sklearn_gbdt_valid_test_promotion"]["state"] == "blocked"
    assert registry_by_method["xgboost_lambdamart_gpu_promotion"]["state"] == "blocked"
    assert registry_by_method["lightgbm_lambdamart_gpu_promotion"]["state"] == "blocked"
    assert registry_by_method["sklearn_gbdt_valid_test_promotion"]["gpu_resource"]["status"] == "not_required"
    assert registry_by_method["xgboost_lambdamart_gpu_promotion"]["gpu_resource"]["status"] == "blocked-gpu-unavailable"
    assert "dependency_missing:xgboost" in registry_by_method["xgboost_lambdamart_gpu_promotion"]["reasons"]
    assert comparison["dependency_status"] == {"sklearn": False, "xgboost": False, "lightgbm": False}



def test_phase_1_rule_ranking_runner_reuses_phase_0_registry_and_artifact_base(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        strategy_name = config_overrides["strategy_name"]
        rule_variant = "same_run_baseline" not in strategy_name
        metrics = {
            "hit_rate_at_k": 0.1005 if rule_variant else 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    monkeypatch.setattr(phase_1_rule_runner, "run_hybrid_demo", fake_run_hybrid_demo)

    comparison = phase_1_rule_runner.run_phase_1_rule_ranking(tmp_path / "phase1", limit_users=2, runs=3)

    assert comparison["phase"] == "phase_1_rule_ranking_champion"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["artifact_inspection"]["schema_version"] == "ranking_artifact_inspection_v1"
    assert comparison["gpu_resource_strategy"]["current_phase_gpu_required"] is False
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["final_decision"]["status"] == "BASELINE_FINAL_ROUTE"
    assert comparison["lanes"]["promotion"]["candidate_types"] == ["baseline", "normalized_additive", "source_aware_fusion", "item_feature_rerank", "finite_grid_rules"]
    assert all(row["candidate_pool_size"] == 200 for row in comparison["runs"])
    assert all(row["top_k"] == 5 for row in comparison["runs"])
    assert all(row["frozen_candidate_status"] == "PASS" for row in comparison["runs"])
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    assert registry_by_method["normalized_additive_balanced"]["state"] == "retired"
    assert registry_by_method["source_aware_itemcf_protection"]["state"] == "retired"
    assert registry_by_method["item_feature_multi_source_rescue"]["state"] == "retired"
    assert registry_by_method["coordinate_rule_combo_conservative"]["state"] == "retired"
    assert all(entry["gpu_resource"]["status"] == "not_required" for entry in comparison["method_registry"])
    assert comparison["stability_summary"]["normalized_additive_balanced"]["runs"] == 3
    assert comparison["stability_summary"]["normalized_additive_balanced"]["consistent_runs"] == 0
    assert "hit_rate_absolute_lift_below_0.001" in comparison["stability_summary"]["normalized_additive_balanced"]["no_promote_reasons"]



def test_phase_1_29_terminal_runner_separates_lanes_and_writes_no_promote_decision(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        write_jsonl(frozen_path, frozen_rows)
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        strategy_name = config_overrides["strategy_name"]
        ltr_enabled = bool(config_overrides.get("ltr_model", {}).get("enabled", False))
        promotion_variant = "gbdt_style" in strategy_name or "lambdamart_style" in strategy_name
        metrics = {
            "hit_rate_at_k": 0.1005 if promotion_variant else 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 3,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5, "ltr_model": {"enabled": ltr_enabled}},
        }
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
        }

    def fake_train_ltr_variant(output_dir, limit_users, variant):
        output_path = Path(output_dir) / "ltr_training" / str(variant["name"])
        output_path.mkdir(parents=True, exist_ok=True)
        model_path = output_path / "ltr_model.json"
        metrics_path = output_path / "ltr_train_metrics.json"
        rows_path = output_path / "ltr_candidate_rows.jsonl"
        model_path.write_text("{}", encoding="utf-8")
        metrics = {
            "evaluation_mode": "leave_one_positive_out",
            "model_type": f"{variant['model_type']}_ltr_v1",
            "rows": 2,
            "positive_rows": 1,
            "negative_rows": 1,
            "feature_contract_gate": {"schema_version": "ranking_feature_contract_gate_v1", "status": "PASS", "checked_rows": 2, "checked_feature_count": 2, "reasons": []},
            "leakage_gate": {"schema_version": "ranking_feature_leakage_gate_v1", "status": "PASS", "checked_rows": 2, "label_source": "leave_one_positive_out_train", "training_split": "train", "reasons": []},
        }
        return {"model_path": str(model_path), "metrics_path": str(metrics_path), "candidate_rows_path": str(rows_path), "model": {}, "metrics": metrics}

    monkeypatch.setattr(phase_1_29_runner, "run_hybrid_demo", fake_run_hybrid_demo)
    monkeypatch.setattr(phase_1_29_runner, "_train_ltr_variant", fake_train_ltr_variant)

    comparison = phase_1_29_runner.run_terminal_ranking_route(tmp_path / "terminal", limit_users=2, runs=3)

    assert comparison["phase"] == "phase_1_29_terminal_ranking_route"
    assert comparison["minimum_runs"] == 3
    assert comparison["required_consistent_runs"] == 2
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["artifact_inspection"]["schema_version"] == "ranking_artifact_inspection_v1"
    assert comparison["gpu_resource_strategy"]["current_phase_gpu_required"] is False
    assert comparison["gpu_resource_strategy"]["unavailable_status"] == "blocked-gpu-unavailable"
    assert comparison["gpu_resource_strategy"]["cpu_smoke_status"] == "diagnostic-cpu-smoke"
    assert "ranknet" in comparison["gpu_resource_strategy"]["future_gpu_required_families"]
    assert comparison["method_registry"]
    registry_by_method = {entry["method_id"]: entry for entry in comparison["method_registry"]}
    assert registry_by_method["same_run_baseline"]["state"] == "champion"
    assert registry_by_method["gbdt_style_stump_rules"]["state"] == "retired"
    assert registry_by_method["pointwise_logistic_lopo_ltr"]["state"] == "diagnostic"
    assert all(entry["gpu_resource"]["status"] == "not_required" for entry in comparison["method_registry"])
    assert comparison["final_decision"]["selected_route"] == "same_run_baseline"
    assert comparison["final_decision"]["status"] == "BASELINE_FINAL_ROUTE"
    assert comparison["lanes"]["promotion"]["candidate_types"] == ["baseline", "gbdt", "lambdamart"]
    assert comparison["lanes"]["diagnostic"]["promotion_eligible"] is False
    gbdt_summary = comparison["stability_summary"]["gbdt_style_stump_rules"]
    assert gbdt_summary["runs"] == 3
    assert gbdt_summary["consistent_runs"] == 0
    assert gbdt_summary["promotable"] is False
    assert "hit_rate_absolute_lift_below_0.001" in gbdt_summary["no_promote_reasons"]
    diagnostic_rows = [row for row in comparison["runs"] if row["lane"] == "diagnostic"]
    assert diagnostic_rows
    assert all(row["promotion_eligible"] is False and row["diagnostic_only"] is True for row in diagnostic_rows)
    assert all(row["ranking_experiment_registry"]["candidate_pool_size"] == 200 for row in comparison["runs"])
    assert all(row["ranking_experiment_registry"]["top_k"] == 5 for row in comparison["runs"])
    assert all(row["candidate_pool_size"] == 200 for row in comparison["runs"])
    assert all(row["top_k"] == 5 for row in comparison["runs"])
    assert all(row["frozen_candidate_status"] == "PASS" for row in comparison["runs"])



def test_phase_1_30_runner_contract_exports_physical_stage_artifacts_and_keeps_pool200(tmp_path, monkeypatch):
    frozen_rows = [
        {"user_id": "u1", "candidate_rank": 1, "item_id": "a"},
        {"user_id": "u1", "candidate_rank": 2, "item_id": "b"},
    ]

    def fake_run_hybrid_demo(config_path, *, limit_users=None, config_overrides=None):
        output_dir = Path(config_overrides["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        frozen_path = output_dir / "frozen_candidates.jsonl"
        trace_path = output_dir / "ranking_stage_trace.jsonl"
        summary_path = output_dir / "ranking_stage_summary.json"
        write_jsonl(frozen_path, frozen_rows)
        write_jsonl(trace_path, [
            {"user_id": "u1", "item_id": "a", "stage_names": ["coarse", "fine", "rerank"]},
            {"user_id": "u1", "item_id": "b", "stage_names": ["coarse", "fine", "rerank"]},
        ])
        summary_path.write_text(json.dumps({
            "schema_version": "ranking_stage_artifact_v1",
            "trace_path": str(trace_path),
            "summary_path": str(summary_path),
            "candidate_pool_size": 200,
            "top_k": 5,
            "stage_counts": {"coarse": 2, "fine": 2, "rerank": 2},
            "pass_through_stage_counts": {"coarse": 2, "fine": 2, "rerank": 2},
            "total_ranked_items": 2,
            "online_metrics": {},
            "online_metric_claims": [],
        }), encoding="utf-8")
        for artifact_name in ["metrics.json", "recommendations.jsonl", "ranking_hit_cases.jsonl", "ranking_case_summary.json", "report.md"]:
            (output_dir / artifact_name).write_text("{}", encoding="utf-8")
        metrics = {
            "hit_rate_at_k": 0.1,
            "ndcg_at_k": 0.1,
            "mrr_at_k": 0.1,
            "map_at_k": 0.1,
            "candidate_hit_missed_topk_users": 1,
            "users_with_holdout": 1,
            "candidate_hit_users": 1,
            "candidate_hit_rate_at_pool": 1.0,
            "candidate_count_avg": 2.0,
            "fallback_rate": 0.0,
            "candidate_pool_size": 200,
            "top_k": 5,
            "config_summary": {"candidate_pool_size": 200, "top_k": 5, "export_ranking_stage_artifacts": True},
            "ranking_stage_artifact_paths": {"trace": str(trace_path), "summary": str(summary_path)},
        }
        assert config_overrides["export_ranking_stage_artifacts"] is True
        assert config_overrides["physical_ranking_pipeline"] == phase_1_30_runner.PHYSICAL_PIPELINE_OVERRIDE
        return {
            "metrics": metrics,
            "metrics_path": str(output_dir / "metrics.json"),
            "recommendations_path": str(output_dir / "recommendations.jsonl"),
            "ranking_cases_path": str(output_dir / "ranking_hit_cases.jsonl"),
            "ranking_case_summary_path": str(output_dir / "ranking_case_summary.json"),
            "report_path": str(output_dir / "report.md"),
            "frozen_candidates_path": str(frozen_path),
            "ranking_stage_trace_path": str(trace_path),
            "ranking_stage_summary_path": str(summary_path),
        }

    monkeypatch.setattr(phase_1_30_runner, "run_hybrid_demo", fake_run_hybrid_demo)

    comparison = phase_1_30_runner.run_phase_1_30_physical_ranking_pipeline(tmp_path / "phase130", limit_users=2)

    assert comparison["phase"] == "phase_1_30_physical_ranking_pipeline"
    assert comparison["candidate_pool_size"] == 200
    assert comparison["top_k"] == 5
    assert comparison["artifact_inspection"]["status"] == "PASS"
    assert comparison["physical_pipeline_inspection"]["status"] == "PASS"
    assert comparison["physical_pipeline_summary"]["trace_path"].endswith("ranking_stage_trace.jsonl")
    assert comparison["physical_pipeline_summary"]["summary_path"].endswith("ranking_stage_summary.json")
    assert comparison["promotion_policy"]["online_metrics_forbidden_as_current_offline_evidence"] is True
    assert comparison["promotion_policy"]["physical_pipeline_pass_through_only"] is True
    run = comparison["runs"][0]
    assert run["ranking_experiment_registry"]["candidate_pool_size"] == 200
    assert run["ranking_experiment_registry"]["top_k"] == 5
    assert Path(run["ranking_stage_trace_path"]).exists()
    assert Path(run["ranking_stage_summary_path"]).exists()
    assert run["candidate_pool_size"] == 200
    assert run["top_k"] == 5
    assert run["frozen_candidate_status"] == "PASS"



def test_phase_1_23_same_run_gate_marks_candidate_pool_drift_invalid_and_stable_valid():
    baseline_freeze = {
        "users_with_holdout": 138,
        "candidate_hit_users": 19,
        "candidate_hit_rate_at_pool": 0.137681,
        "candidate_count_avg": 157.112,
        "fallback_rate": 0.0,
    }

    stable_status, stable_drift = _status_and_drift(dict(baseline_freeze), baseline_freeze)
    drift_status, drift = _status_and_drift(baseline_freeze | {"candidate_count_avg": 150.0}, baseline_freeze)
    baseline_status, baseline_drift = _status_and_drift(baseline_freeze, None)

    assert stable_status == "VALID"
    assert stable_drift == {}
    assert drift_status == "INVALID"
    assert drift == {"candidate_count_avg": {"baseline": 157.112, "current": 150.0}}
    assert baseline_status == "INVALID"
    assert baseline_drift["candidate_hit_users"] == {"baseline": None, "current": 19}



def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



def test_config_loads_json_compatible_yaml():
    config = load_config("D:/sinrotic_code/python_project/summer/RS_agent/configs/demo/hybrid_demo/hybrid_demo_small.yaml")
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
