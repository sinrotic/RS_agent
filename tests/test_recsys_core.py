from __future__ import annotations

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
        {"two_tower_enabled": True, "two_tower_per_user": 1},
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
    assert disabled["rerank_score"] == 0.0
    assert disabled["score"] == disabled["fine_score"]
    assert empty_model["ltr_score"] == 0.0
    assert empty_model["score"] == empty_model["fine_score"]



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
