from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.candidate_merge import RecallCandidate, merge_candidates, metadata_neighbor_candidates_for_user, two_tower_candidates_for_user
from rs_core.recsys.ranking import rank_candidates
from rs_core.recsys.types import MergedCandidate
from rs_core.recsys.vector_index import VectorIndex


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


def test_vector_two_tower_applies_user_tower_projection_to_realtime_history():
    index = VectorIndex(
        items={
            "seed": {"embedding": [1.0, 0.0]},
            "raw_match": {"embedding": [1.0, 0.0]},
            "projected_match": {"embedding": [0.0, 1.0]},
        },
        user_embeddings={"u1": [1.0, 0.0]},
        source_name="two_tower_youtube_dnn",
        model_metadata={
            "model_parameters": {
                "user_tower.0.weight": [[1.0, 0.0], [1.0, 0.0]],
                "user_tower.0.bias": [0.0, 0.0],
                "user_tower.2.weight": [[-1.0, 0.0], [0.0, 1.0]],
                "user_tower.2.bias": [0.0, 0.0],
            }
        },
    )

    rows = two_tower_candidates_for_user(
        {"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]},
        index,
        {"two_tower_enabled": True, "two_tower_per_user": 1, "two_tower_artifact_user_embedding_first": False},
    )

    assert [row.item_id for row in rows] == ["projected_match"]


def test_ranking_weights_and_tie_break_order():
    candidates = merge_candidates(
        [
            RecallCandidate("b", "popular", 1.0),
            RecallCandidate("a", "itemcf_weak", 1.0),
            RecallCandidate("c", "popular", 1.0),
        ]
    )

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 3, "rank_weights": {"popular": 1.0, "itemcf_weak": 3.0}},
    )

    assert [item["parent_asin"] for item in result.items] == ["a", "b", "c"]


def test_ranking_emits_three_stage_contract_and_rank_movement():
    candidates = [
        MergedCandidate("i1", ["popular"], {"popular": 0.9}, metadata={"category": "cat_a"}, category="cat_a"),
        MergedCandidate("i2", ["semantic", "itemcf_strong"], {"semantic": 0.5, "itemcf_strong": 0.6}, metadata={"category": "cat_b"}, category="cat_b"),
        MergedCandidate("i3", ["popular"], {"popular": 0.1}, metadata={"category": "cat_c"}, category="cat_c"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 2, "rank_weights": {"popular": 1.0, "semantic": 1.0, "itemcf_strong": 1.0}, "coarse_top_n": 2},
    )

    assert len(result.items) == 2
    for item in result.items:
        assert {stage["stage"] for stage in item["score_trace"]} == {"coarse", "fine", "rerank"}
        assert isinstance(item["coarse_rank"], int)
        assert isinstance(item["fine_rank"], int)
        assert isinstance(item["final_rank"], int)
        assert set(item["rank_movement"]) >= {"coarse_to_fine", "fine_to_final", "coarse_to_final"}
        assert "coarse_score" in item
        assert "fine_score" in item
        assert "final_score" in item
    assert {item["parent_asin"] for item in result.items} == {"i1", "i2"}



def test_ranking_ltr_disabled_or_empty_model_has_no_rerank_delta():
    candidates = [MergedCandidate("i1", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat"}, category="cat")]

    disabled = rank_candidates("u1", candidates, {"top_k": 1, "ltr_model": {"enabled": False, "model": {"weights": {"score_semantic": 10.0}}}}).items[0]
    empty_model = rank_candidates("u1", candidates, {"top_k": 1, "ltr_model": {"enabled": True, "model": {"weights": {}}}}).items[0]

    assert disabled["ltr_score"] == 0.0
    assert disabled["deepfm_score"] == 0.0
    assert disabled["rerank_score"] == 0.0
    assert disabled["score"] == disabled["fine_score"]
    assert empty_model["ltr_score"] == 0.0
    assert empty_model["deepfm_score"] == 0.0
    assert empty_model["score"] == empty_model["fine_score"]



def test_ranking_deepfm_model_reranks_only_with_candidate_features():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 2.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [
        MergedCandidate("weak", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 0.1}}, category="cat"),
        MergedCandidate("strong", ["semantic"], {"semantic": 0.5}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 2, "rank_weights": {"semantic": 1.0}, "deepfm_model": {"enabled": True, "model": model, "score_scale": 1.0, "ranking_input_replacement_allowed": True, "ranking_effect_conclusion_allowed": True}},
    )

    assert [item["parent_asin"] for item in result.items] == ["strong", "weak"]
    strong = result.items[0]
    assert strong["deepfm_score"] == 2.0
    assert any(event.get("type") == "diagnostic_deepfm_rerank" and event.get("diagnostic_only") is True for event in strong["rerank_events"])
    assert "diagnostic_deepfm_rerank" in strong["score_trace"][-1]["reason_codes"]



def test_ranking_deepfm_shadow_mode_scores_without_changing_rank():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 10.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [
        MergedCandidate("base_top", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 0.0}}, category="cat"),
        MergedCandidate("shadow_high", ["semantic"], {"semantic": 0.1}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 2, "rank_weights": {"semantic": 1.0}, "deepfm_model": {"enabled": True, "model": model, "mode": "shadow", "score_scale": 1.0}},
    )

    assert [item["parent_asin"] for item in result.items] == ["base_top", "shadow_high"]
    shadow_high = result.items[1]
    event = next(event for event in shadow_high["rerank_events"] if event.get("type") == "deepfm_shadow_score")
    assert event["raw_score"] == 10.0
    assert event["delta"] == 0.0
    assert shadow_high["deepfm_score"] == 0.0



def test_ranking_deepfm_model_can_load_from_config_path(tmp_path):
    model_path = tmp_path / "deepfm_model.json"
    model_path.write_text(json.dumps({
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 1.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }), encoding="utf-8")
    candidates = [MergedCandidate("i1", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat")]

    result = rank_candidates("u1", candidates, {"top_k": 1, "deepfm_model": {"enabled": True, "model_path": str(model_path), "ranking_input_replacement_allowed": True, "ranking_effect_conclusion_allowed": True}})

    assert result.items[0]["deepfm_score"] == 1.0



def test_ranking_deepfm_skips_when_required_features_missing():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal", "missing_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 2.0, "missing_signal": 10.0},
        "fm_factors": {"strong_signal": [0.0], "missing_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [MergedCandidate("i1", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat")]

    result = rank_candidates("u1", candidates, {"top_k": 1, "deepfm_model": {"enabled": True, "model": model}})

    item = result.items[0]
    assert item["deepfm_score"] == 0.0
    event = next(event for event in item["rerank_events"] if event.get("type") == "diagnostic_deepfm_rerank")
    assert event["status"] == "skipped"
    assert event["reason"] == "missing_required_features"



def test_ranking_deepfm_ignores_forbidden_metadata_keys_and_feature_names():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal", "label_score", "valid_signal", "source_semantic"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 1.0, "label_score": 100.0, "valid_signal": 100.0, "source_semantic": 100.0},
        "fm_factors": {"strong_signal": [0.0], "label_score": [0.0], "valid_signal": [0.0], "source_semantic": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [
        MergedCandidate(
            "safe",
            ["semantic"],
            {"semantic": 1.0},
            metadata={
                "category": "cat",
                "cold_deepfm_features": {"strong_signal": 1.0, "label_score": 999.0, "valid_signal": 999.0, "source_semantic": 999.0},
                "label": {"strong_signal": 999.0},
                "valid": {"strong_signal": 999.0},
                "test": {"strong_signal": 999.0},
            },
            category="cat",
        )
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 1, "deepfm_model": {"enabled": True, "model": model, "require_all_features": False, "feature_metadata_keys": ["label", "valid", "test", "cold_deepfm_features"], "ranking_input_replacement_allowed": True, "ranking_effect_conclusion_allowed": True}},
    )

    item = result.items[0]
    assert item["deepfm_score"] == 1.0
    event = next(event for event in item["rerank_events"] if event.get("type") == "diagnostic_deepfm_rerank")
    assert event["feature_count"] == 1



def test_ranking_deepfm_ignores_top_level_metadata_feature_values():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 7.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [
        MergedCandidate(
            "top_level_poison",
            ["semantic"],
            {"semantic": 1.0},
            metadata={"category": "cat", "strong_signal": 999.0, "cold_deepfm_features": {"strong_signal": 0.0}},
            category="cat",
        )
    ]

    result = rank_candidates("u1", candidates, {"top_k": 1, "deepfm_model": {"enabled": True, "model": model}})

    item = result.items[0]
    assert item["deepfm_score"] == 0.0
    event = next(event for event in item["rerank_events"] if event.get("type") == "diagnostic_deepfm_rerank")
    assert event["feature_count"] == 1



@pytest.mark.parametrize("feature_key", ["cold_deepfm_features", "deepfm_features", "ranking_features"])
def test_ranking_deepfm_accepts_only_allowlisted_feature_metadata_keys(feature_key):
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 3.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [MergedCandidate("i1", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", feature_key: {"strong_signal": 1.0}}, category="cat")]

    result = rank_candidates("u1", candidates, {"top_k": 1, "deepfm_model": {"enabled": True, "model": model, "feature_metadata_keys": [feature_key], "ranking_input_replacement_allowed": True, "ranking_effect_conclusion_allowed": True}})

    assert result.items[0]["deepfm_score"] == 3.0



def test_ranking_deepfm_shadow_all_zero_safe_scores_without_rank_delta():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["has_item_train_history", "has_user_train_history"],
        "bias": 1.5,
        "linear_weights": {"has_item_train_history": 10.0, "has_user_train_history": 10.0},
        "fm_factors": {"has_item_train_history": [0.0], "has_user_train_history": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    contract = {"feature_names": ["has_item_train_history", "has_user_train_history"]}
    report = {"ranking_replacement_allowed": False, "ranking_effect_conclusion_allowed": False}
    candidates = [
        MergedCandidate("base_top", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat"}, category="cat"),
        MergedCandidate("shadow_high", ["semantic"], {"semantic": 0.1}, metadata={"category": "cat"}, category="cat"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {
            "top_k": 2,
            "rank_weights": {"semantic": 1.0},
            "deepfm_shadow": {
                "enabled": True,
                "model": model,
                "feature_contract": contract,
                "artifact_report": report,
                "feature_strategy": "all_zero_safe",
                "affect_ranking": False,
            },
        },
    )

    assert [item["parent_asin"] for item in result.items] == ["base_top", "shadow_high"]
    event = next(event for event in result.items[1]["rerank_events"] if event.get("type") == "deepfm_shadow_score")
    assert event["raw_score"] == 1.5
    assert event["feature_count"] == 2
    assert event["delta"] == 0.0
    assert event["status"] == "scored_no_ranking_effect"



def test_ranking_deepfm_shadow_governance_blocks_requested_delta():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 10.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    report = {"ranking_replacement_allowed": False, "ranking_effect_conclusion_allowed": False}
    candidates = [
        MergedCandidate("base_top", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 0.0}}, category="cat"),
        MergedCandidate("blocked_high", ["semantic"], {"semantic": 0.1}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {
            "top_k": 2,
            "rank_weights": {"semantic": 1.0},
            "deepfm_shadow": {
                "enabled": True,
                "model": model,
                "artifact_report": report,
                "feature_strategy": "metadata",
                "affect_ranking": True,
                "score_scale": 1.0,
                "ranking_input_replacement_allowed": True,
                "ranking_effect_conclusion_allowed": True,
            },
        },
    )

    assert [item["parent_asin"] for item in result.items] == ["base_top", "blocked_high"]
    event = next(event for event in result.items[1]["rerank_events"] if event.get("type") == "deepfm_shadow_score")
    assert event["raw_score"] == 10.0
    assert event["delta"] == 0.0
    assert event["governance_blocked_delta"] is True
    assert event["report_ranking_replacement_allowed"] is False
    assert event["report_ranking_effect_conclusion_allowed"] is False



def test_ranking_deepfm_shadow_blocks_feature_contract_mismatch():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["model_feature"],
        "bias": 0.0,
        "linear_weights": {"model_feature": 10.0},
        "fm_factors": {"model_feature": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [MergedCandidate("i1", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat"}, category="cat")]

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 1, "deepfm_shadow": {"enabled": True, "model": model, "feature_contract": {"feature_names": ["contract_feature"]}}},
    )

    item = result.items[0]
    assert item["deepfm_score"] == 0.0
    event = next(event for event in item["rerank_events"] if event.get("type") == "deepfm_shadow_score")
    assert event["status"] == "blocked_feature_contract"
    assert event["reason"] == "model_contract_feature_mismatch"



def test_ranking_disabled_deepfm_shadow_does_not_mask_enabled_deepfm_model():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 2.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [MergedCandidate("i1", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat")]

    result = rank_candidates(
        "u1",
        candidates,
        {
            "top_k": 1,
            "deepfm_shadow": {"enabled": False},
            "deepfm_model": {"enabled": True, "model": model, "ranking_input_replacement_allowed": True, "ranking_effect_conclusion_allowed": True},
        },
    )

    assert result.items[0]["deepfm_score"] == 2.0



def test_ranking_deepfm_shadow_missing_artifact_path_skips_safely(tmp_path):
    candidates = [MergedCandidate("i1", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat"}, category="cat")]

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 1, "deepfm_shadow": {"enabled": True, "model_path": str(tmp_path / "missing_model.json")}},
    )

    item = result.items[0]
    assert item["deepfm_score"] == 0.0
    event = next(event for event in item["rerank_events"] if event.get("type") == "deepfm_shadow_score")
    assert event["status"] == "skipped"
    assert event["reason"] == "missing_model_path"



def test_ranking_deepfm_policy_diagnostic_only_blocks_requested_delta():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 10.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [
        MergedCandidate("base_top", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 0.0}}, category="cat"),
        MergedCandidate("diagnostic_high", ["semantic"], {"semantic": 0.1}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {
            "top_k": 2,
            "deepfm_model": {
                "enabled": True,
                "model": model,
                "diagnostic_only": True,
                "score_scale": 1.0,
                "ranking_input_replacement_allowed": True,
                "ranking_effect_conclusion_allowed": True,
            },
        },
    )

    assert [item["parent_asin"] for item in result.items] == ["base_top", "diagnostic_high"]
    event = next(event for event in result.items[1]["rerank_events"] if event.get("type") == "diagnostic_deepfm_rerank")
    assert event["policy_diagnostic_only"] is True
    assert event["governance_blocked_delta"] is True
    assert event["delta"] == 0.0



def test_ranking_deepfm_shadow_respects_max_scored_candidates():
    model = {
        "model_type": "deepfm_ranker_v1",
        "feature_names": ["strong_signal"],
        "bias": 0.0,
        "linear_weights": {"strong_signal": 1.0},
        "fm_factors": {"strong_signal": [0.0]},
        "deep_weights": [],
        "deep_bias": [],
        "deep_output": [],
    }
    candidates = [
        MergedCandidate("first", ["semantic"], {"semantic": 2.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat"),
        MergedCandidate("second", ["semantic"], {"semantic": 1.0}, metadata={"category": "cat", "cold_deepfm_features": {"strong_signal": 1.0}}, category="cat"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 2, "deepfm_shadow": {"enabled": True, "model": model, "feature_strategy": "metadata", "max_scored_candidates": 1}},
    )

    first_event = next(event for event in result.items[0]["rerank_events"] if event.get("type") == "deepfm_shadow_score")
    second_event = next(event for event in result.items[1]["rerank_events"] if event.get("type") == "deepfm_shadow_score")
    assert first_event["status"] == "scored_no_ranking_effect"
    assert second_event["reason"] == "max_scored_candidates_exceeded"



def test_online_service_enables_deepfm_shadow_diagnostic_only():
    config = json.loads(Path("configs/serving/online_service.yaml").read_text(encoding="utf-8"))

    assert config["deepfm_shadow"]["enabled"] is True
    assert config["deepfm_shadow"]["mode"] == "shadow_diagnostic"
    assert config["deepfm_shadow"]["affect_ranking"] is False
    assert config["deepfm_shadow"]["score_scale"] == 0.0
    assert config["deepfm_shadow"]["public_payload_allowed"] is False
    assert config["deepfm_shadow"]["ranking_input_replacement_allowed"] is False
    assert config["deepfm_shadow"]["promotion_allowed"] is False



def test_policy_rerank_guard_defers_overexposed_source_and_records_event():
    candidates = [
        MergedCandidate("a", ["popular"], {"popular": 1.0}, metadata={"category": "cat_a"}, category="cat_a"),
        MergedCandidate("b", ["popular"], {"popular": 0.9}, metadata={"category": "cat_b"}, category="cat_b"),
        MergedCandidate("c", ["semantic"], {"semantic": 0.1}, metadata={"category": "cat_c"}, category="cat_c"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {
            "top_k": 2,
            "rank_weights": {"popular": 1.0, "semantic": 1.0},
            "policy_rerank_guard": {"enabled": True, "max_per_source_topk_ratio": 0.5},
        },
    )

    assert [item["parent_asin"] for item in result.items] == ["a", "c"]
    deferred = next(item for item in rank_candidates("u1", candidates, {"top_k": 3, "rank_weights": {"popular": 1.0, "semantic": 1.0}, "policy_rerank_guard": {"enabled": True, "max_per_source_topk_ratio": 0.5}}).items if item["parent_asin"] == "b")
    assert any(event.get("rule") == "source_diversity_guard" for event in deferred["rerank_events"])



def test_policy_rerank_guard_keeps_prior_deferred_items_out_of_later_topk_refill():
    candidates = [
        MergedCandidate("a", ["popular"], {"popular": 1.0}, metadata={"category": "cat_a"}, category="cat_a"),
        MergedCandidate("b", ["popular"], {"popular": 0.9}, metadata={"category": "cat_b"}, category="cat_b"),
        MergedCandidate("missing", ["category"], {"category": 0.8}, metadata={}, category=""),
        MergedCandidate("c", ["semantic"], {"semantic": 0.1}, metadata={"category": "cat_c"}, category="cat_c"),
    ]
    config = {
        "rank_weights": {"popular": 1.0, "category": 1.0, "semantic": 1.0},
        "policy_rerank_guard": {
            "enabled": True,
            "max_category_missing_topk_ratio": 0.0,
            "max_per_source_topk_ratio": 0.34,
        },
    }

    result = rank_candidates("u1", candidates, {**config, "top_k": 3})
    full_result = rank_candidates("u1", candidates, {**config, "top_k": 4})

    assert [item["parent_asin"] for item in result.items] == ["a", "c", "b"]
    missing = next(item for item in full_result.items if item["parent_asin"] == "missing")
    assert missing["final_rank"] == 4
    assert any(event.get("rule") == "category_missing_cap" for event in missing["rerank_events"])



def test_coarse_ranking_uses_calibration_prior_rrf_and_multi_source_boost():
    candidates = [
        MergedCandidate(
            "multi",
            ["semantic", "itemcf_strong"],
            {"semantic": 0.4, "itemcf_strong": 0.4},
            metadata={"category": "cat_a", "pool500_source_lineage": [{"source": "semantic", "rank": 1}, {"source": "itemcf_strong", "rank": 2}]},
            category="cat_a",
        ),
        MergedCandidate("popular", ["popular"], {"popular": 0.9}, metadata={"category": "cat_b", "popular_rank": 1}, category="cat_b"),
    ]

    result = rank_candidates(
        "u1",
        candidates,
        {
            "top_k": 2,
            "rank_weights": {"popular": 1.0, "semantic": 1.0, "itemcf_strong": 1.0},
            "coarse_ranking": {
                "source_score_calibration": {"popular": {"scale": 0.5}, "semantic": {"scale": 1.0}, "itemcf_strong": {"scale": 1.0}},
                "source_prior": {"itemcf_strong": 0.05},
                "reciprocal_rank_fusion": {"enabled": True, "k": 60.0, "weight": 1.0},
                "multi_source_boost": 0.1,
            },
        },
    )

    assert result.items[0]["parent_asin"] == "multi"
    components = result.items[0]["coarse_components"]
    assert components["source_score_calibration"]["semantic"]["calibrated_score"] == 0.4
    assert components["source_prior"] == 0.05
    assert components["reciprocal_rank_fusion"] > 0.0
    assert components["multi_source_boost"] == 0.1
    assert set(result.items[0]["score_trace"][0]["reason_codes"]) >= {"source_prior", "reciprocal_rank_fusion", "multi_source_boost"}


def test_metadata_neighbor_recall_uses_bucketed_training_visible_metadata():
    metadata_index = {
        "seed": {"title_clean": "wireless noise cancelling headphones", "main_category": "Audio"},
        "candidate": {"title_clean": "wireless bluetooth headphones", "main_category": "Audio"},
        "unrelated": {"title_clean": "garden hose", "main_category": "Garden"},
    }

    rows = metadata_neighbor_candidates_for_user(
        {"recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]},
        metadata_index,
        {
            "metadata_neighbor_enabled": True,
            "metadata_neighbor_per_user": 5,
            "metadata_neighbor_per_seed": 5,
            "metadata_neighbor_min_token_overlap": 1,
        },
    )

    assert [row.item_id for row in rows] == ["candidate"]
    assert rows[0].source == "metadata_neighbor_recall"
    assert rows[0].metadata["metadata_neighbor_index_mode"] == "bucketed_train_visible_metadata"
