from __future__ import annotations

import pytest

from rs_lab.experiments.recall.pool500.methods.semantic.builder import _candidate_rows, _semantic_score_config

pytestmark = pytest.mark.unit


def test_semantic_bm25f_prefers_title_category_match_over_generic_overlap() -> None:
    semantic_index = {
        "seed": {
            "parent_asin": "seed",
            "title_clean": "wireless mouse",
            "main_category": "Electronics",
            "semantic_tokens": {"wireless", "mouse", "electronics"},
        },
        "title_category_hit": {
            "parent_asin": "title_category_hit",
            "title_clean": "wireless mouse ergonomic",
            "main_category": "Electronics",
            "description_text": "office accessory",
            "semantic_tokens": {"wireless", "mouse", "ergonomic", "electronics", "product"},
        },
        "generic_hit": {
            "parent_asin": "generic_hit",
            "title_clean": "desk mat",
            "main_category": "Office",
            "description_text": "wireless product item mouse electronics " * 20,
            "semantic_tokens": {"wireless", "product", "item", "mouse", "electronics"},
        },
    }

    rows = _candidate_rows(
        [{"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}],
        {"u1": ["seed"]},
        semantic_index,
        2,
        1,
        per_token_item_limit=10,
        max_candidate_items=10,
        candidate_metadata_policy="lean_reference",
        semantic_score_config=_semantic_score_config({
            "semantic_score_mode": "bm25f",
            "generic_tokens": ["product", "item"],
            "field_weights": {"title_clean": 4.0, "main_category": 3.0, "description_text": 0.2},
        }),
    )

    assert [row["item_id"] for row in rows] == ["title_category_hit", "generic_hit"]
    assert rows[0]["bm25f_score"] > rows[1]["bm25f_score"]
    assert rows[0]["semantic_token_overlap"] >= 1
    assert "title_clean" in rows[0]["field_scores"]
    assert "category_channel_boost" in rows[0]["field_scores"]
