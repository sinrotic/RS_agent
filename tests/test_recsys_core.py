from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rs_core.recsys.candidate_merge import RecallCandidate, merge_candidates, metadata_neighbor_candidates_for_user
from rs_core.recsys.ranking import rank_candidates


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

    result = rank_candidates(
        "u1",
        candidates,
        {"top_k": 3, "rank_weights": {"popular": 1.0, "itemcf_weak": 3.0}},
    )

    assert [item["parent_asin"] for item in result.items] == ["a", "b", "c"]


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
