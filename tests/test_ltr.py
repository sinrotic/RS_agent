from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.ltr import (
    build_ltr_feature_contract_gate_summary,
    build_ltr_leakage_gate_summary,
    extract_ltr_features,
    load_ltr_model,
    save_ltr_model,
    score_ltr,
    train_pairwise_perceptron,
    train_pointwise_logistic,
    validate_ltr_feature_contract_gate,
    validate_ltr_leakage_gate,
)
from rs_core.recsys.types import MergedCandidate


def test_extract_ltr_features_includes_source_scores_interactions_and_metadata():
    candidate = MergedCandidate(
        item_id="item1",
        sources=["itemcf_weak", "semantic", "feedback_keyword"],
        source_scores={"itemcf_weak": 0.7, "semantic": 0.4, "feedback_keyword": 2.0},
        metadata={"recent_pop_score": 0.3, "verified_pop_score": 0.2, "time_decay_pop_score": 0.1},
    )

    features = extract_ltr_features(candidate)

    assert features["has_itemcf_weak"] == 1.0
    assert features["has_semantic"] == 1.0
    assert features["has_popular"] == 0.0
    assert features["score_itemcf_weak"] == 0.7
    assert features["score_semantic"] == 0.4
    assert features["has_two_tower"] == 0.0
    assert features["score_two_tower"] == 0.0
    assert features["multi_source"] == 1.0
    assert features["itemcf_source"] == 1.0
    assert features["itemcf_multi_source"] == 1.0
    assert features["semantic_only"] == 0.0
    assert features["recent_pop_score"] == 0.3
    assert features["verified_pop_score"] == 0.2
    assert features["time_decay_pop_score"] == 0.1


def test_extract_ltr_features_can_exclude_metadata():
    candidate = MergedCandidate(
        item_id="item1",
        sources=["popular"],
        source_scores={"popular": 1.0},
        metadata={"recent_pop_score": 0.3},
    )

    features = extract_ltr_features(candidate, {"include_metadata": False})

    assert features["popular_only"] == 1.0
    assert "recent_pop_score" not in features


def test_extract_ltr_features_keeps_ranking_v2_default_off():
    candidate = MergedCandidate(
        item_id="item1",
        sources=["two_tower", "semantic"],
        source_scores={"two_tower": 0.9, "semantic": 0.3},
    )

    features = extract_ltr_features(candidate)

    assert "source_count" not in features
    assert "score_two_tower_semantic_gap" not in features


def test_extract_ltr_features_includes_ranking_v2_when_enabled():
    candidate = MergedCandidate(
        item_id="item1",
        sources=["two_tower", "semantic", "itemcf_strong"],
        source_scores={"two_tower": 0.9, "semantic": 0.3, "itemcf_strong": 0.6, "popular": 0.2},
        metadata={"two_tower_seed_rank": 2, "two_tower_overlap": 4, "average_rating": "4.5", "rating_number": "120"},
    )

    features = extract_ltr_features(candidate, {"include_ranking_v2": True})

    assert features["source_count"] == 3.0
    assert round(features["source_score_sum"], 6) == 1.8
    assert round(features["source_score_gap"], 6) == 0.6
    assert features["semantic_itemcf_source"] == 1.0
    assert features["itemcf_semantic_source"] == 1.0
    assert features["itemcf_two_tower_source"] == 1.0
    assert features["two_tower_semantic_itemcf_source"] == 1.0
    assert features["itemcf_two_tower_semantic_source"] == 1.0
    assert round(features["score_two_tower_semantic_gap"], 6) == 0.6
    assert features["score_itemcf_semantic_ratio"] == 2.0
    assert features["score_non_popular_minus_popular"] == 0.7
    assert features["two_tower_seed_rank"] == 2.0
    assert features["two_tower_overlap"] == 4.0
    assert features["average_rating"] == 4.5
    assert features["rating_number"] == 120.0


def test_extract_ltr_features_ranking_v2_flag_preserves_base_features():
    candidate = MergedCandidate(
        item_id="item1",
        sources=["itemcf_weak", "semantic"],
        source_scores={"itemcf_weak": 0.7, "semantic": 0.4},
        metadata={"recent_pop_score": 0.3},
    )

    base_features = extract_ltr_features(candidate)
    ranking_v2_features = extract_ltr_features(candidate, {"include_ranking_v2": True})

    for name, value in base_features.items():
        assert ranking_v2_features[name] == value
    assert set(ranking_v2_features) > set(base_features)


def test_extract_ltr_features_accepts_ltr_v2_version_keys():
    candidate = MergedCandidate(
        item_id="item1",
        sources=["itemcf_weak", "semantic"],
        source_scores={"itemcf_weak": 0.7, "semantic": 0.4},
    )

    assert "source_count" in extract_ltr_features(candidate, {"version": "ltr_v2"})
    assert "source_count" in extract_ltr_features(candidate, {"feature_version": "ranking_v2"})
    assert "source_count" in extract_ltr_features(candidate, {"ranking_v2": {"enabled": True}})


def test_extract_ltr_features_includes_two_tower_source_features():
    candidate = MergedCandidate(
        item_id="item1",
        sources=["two_tower", "semantic"],
        source_scores={"two_tower": 0.9, "semantic": 0.2},
    )

    features = extract_ltr_features(candidate)

    assert features["has_two_tower"] == 1.0
    assert features["score_two_tower"] == 0.9
    assert features["two_tower_source"] == 1.0
    assert features["two_tower_only"] == 0.0
    assert features["two_tower_multi_source"] == 1.0
    assert features["two_tower_semantic_source"] == 1.0
    assert features["two_tower_itemcf_source"] == 0.0
    assert features["semantic_only"] == 0.0


def test_ltr_feature_contract_gate_passes_allowed_feature_set():
    rows = [
        {"user_id": "u1", "item_id": "i1", "label": 1, "features": {"score_semantic": 0.7, "source_count": 2.0}},
        {"user_id": "u1", "item_id": "i2", "label": 0, "features": {"popular_only": 1.0, "recent_pop_score": 0.2}},
    ]

    summary = validate_ltr_feature_contract_gate(rows)

    assert summary["schema_version"] == "ranking_feature_contract_gate_v1"
    assert summary["status"] == "PASS"
    assert summary["checked_feature_count"] == 4
    assert summary["unknown_feature_names"] == []
    assert summary["reasons"] == []



def test_ltr_feature_contract_gate_rejects_unknown_and_forbidden_features():
    rows = [
        {"user_id": "u1", "item_id": "i1", "label": 1, "features": {"experimental_magic": 0.7, "future_clicks": 2.0}},
    ]

    summary = build_ltr_feature_contract_gate_summary(rows)

    assert summary["status"] == "REJECT"
    assert summary["forbidden_feature_names"] == ["future_clicks"]
    assert summary["unknown_feature_names"] == ["experimental_magic", "future_clicks"]
    assert summary["reasons"] == ["forbidden_feature_names", "unknown_feature_names"]
    with pytest.raises(ValueError, match="unknown_feature_names"):
        validate_ltr_feature_contract_gate(rows)



def test_ltr_leakage_gate_passes_allowed_train_features():
    rows = [
        {"user_id": "u1", "item_id": "i1", "label": 1, "features": {"score_semantic": 0.7, "source_count": 2.0}},
        {"user_id": "u1", "item_id": "i2", "label": 0, "features": {"score_popular": 0.2}},
    ]

    summary = validate_ltr_leakage_gate(rows, label_source="leave_one_positive_out_train", training_split="train")

    assert summary["status"] == "PASS"
    assert summary["forbidden_feature_names"] == []
    assert summary["reasons"] == []


def test_ltr_leakage_gate_rejects_target_future_and_holdout_features():
    rows = [
        {
            "user_id": "u1",
            "item_id": "i1",
            "label": 1,
            "features": {
                "target_item_match": 1.0,
                "future_interaction_count": 2.0,
                "holdout_hit": 1.0,
                "label_binary_score": 1.0,
            },
        }
    ]

    summary = build_ltr_leakage_gate_summary(rows)

    assert summary["status"] == "REJECT"
    assert summary["forbidden_feature_names"] == ["future_interaction_count", "holdout_hit", "label_binary_score", "target_item_match"]
    assert summary["reasons"] == ["forbidden_feature_names"]
    with pytest.raises(ValueError, match="forbidden_feature_names"):
        validate_ltr_leakage_gate(rows)


def test_ltr_leakage_gate_rejects_valid_test_holdout_label_source():
    rows = [{"user_id": "u1", "item_id": "i1", "label": 1, "features": {"score_semantic": 0.7}}]

    summary = build_ltr_leakage_gate_summary(rows, label_source="valid_test_holdout", training_split="train")

    assert summary["status"] == "REJECT"
    assert summary["reasons"] == ["forbidden_label_source"]
    with pytest.raises(ValueError, match="forbidden_label_source"):
        validate_ltr_leakage_gate(rows, label_source="valid_test_holdout", training_split="train")


def test_ltr_leakage_gate_rejects_holdout_training_split():
    rows = [{"user_id": "u1", "item_id": "i1", "label": 1, "features": {"score_semantic": 0.7}}]

    summary = build_ltr_leakage_gate_summary(rows, label_source="leave_one_positive_out_train", training_split="test")

    assert summary["status"] == "REJECT"
    assert summary["reasons"] == ["forbidden_training_split"]


def test_pairwise_perceptron_promotes_positive_over_negative():
    rows = [
        {"user_id": "u1", "item_id": "positive", "label": 1, "features": {"itemcf_source": 1.0, "score_itemcf_strong": 1.0}},
        {"user_id": "u1", "item_id": "negative", "label": 0, "features": {"popular_only": 1.0, "score_popular": 1.0}},
    ]

    model = train_pairwise_perceptron(rows, {"epochs": 3, "learning_rate": 0.5, "negative_sample_per_positive": 1, "margin": 1.0})

    positive_score = score_ltr(rows[0]["features"], model["weights"], model["bias"])
    negative_score = score_ltr(rows[1]["features"], model["weights"], model["bias"])
    assert positive_score > negative_score
    assert model["training"]["pairs_seen"] == 3
    assert model["training"]["updates"] >= 1


def test_pointwise_logistic_promotes_positive_over_negative():
    rows = [
        {"user_id": "u1", "item_id": "positive", "label": 1, "features": {"itemcf_source": 1.0, "score_itemcf_strong": 1.0}},
        {"user_id": "u1", "item_id": "negative", "label": 0, "features": {"popular_only": 1.0, "score_popular": 1.0}},
    ]

    model = train_pointwise_logistic(rows, {"epochs": 10, "learning_rate": 0.5})

    positive_score = score_ltr(rows[0]["features"], model["weights"], model["bias"])
    negative_score = score_ltr(rows[1]["features"], model["weights"], model["bias"])
    assert positive_score > negative_score
    assert model["model_type"] == "pointwise_logistic_ltr_v1"
    assert model["training"]["updates"] == 20
    assert model["training"]["average_loss"] > 0



def test_save_and_load_ltr_model_preserves_scores(tmp_path):
    model = {
        "model_type": "pairwise_perceptron_ltr_v1",
        "weights": {"itemcf_source": 0.5, "popular_only": -0.25},
        "bias": 0.1,
        "feature_names": ["itemcf_source", "popular_only"],
    }
    path = tmp_path / "ltr_model.json"

    save_ltr_model(model, path)
    loaded = load_ltr_model(path)

    features = {"itemcf_source": 1.0, "popular_only": 0.0}
    assert loaded == model
    assert score_ltr(features, loaded["weights"], loaded["bias"]) == score_ltr(features, model["weights"], model["bias"])
