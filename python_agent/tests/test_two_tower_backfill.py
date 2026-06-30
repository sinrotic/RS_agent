from __future__ import annotations

import pytest

from rs_core.online.recall.vectorstores.two_tower_backfill import backfill_two_tower_item_vectors

pytestmark = pytest.mark.unit


def test_backfill_two_tower_item_vectors_preserves_trained_and_fills_missing_by_category() -> None:
    existing = [
        {"parent_asin": "a", "embedding": [1.0, 0.0], "main_category": "Audio"},
        {"parent_asin": "b", "embedding": [0.0, 1.0], "main_category": "Office"},
    ]
    catalog = [
        {"parent_asin": "a", "main_category": "Audio"},
        {"parent_asin": "c", "main_category": "Audio"},
        {"parent_asin": "d", "main_category": "Unknown"},
    ]

    result = backfill_two_tower_item_vectors(existing_rows=existing, catalog_rows=catalog)

    by_item = {row["item_id"]: row for row in result.rows}
    assert by_item["a"]["vector_origin"] == "trained_two_tower"
    assert by_item["c"]["vector_origin"] == "category_centroid"
    assert by_item["c"]["embedding"] == [1.0, 0.0]
    assert by_item["d"]["vector_origin"] == "global_centroid"
    assert result.report["trained_item_count"] == 2
    assert result.report["catalog_item_count"] == 3
    assert result.report["backfilled_item_count"] == 2


def test_backfill_two_tower_item_vectors_rejects_empty_trained_vectors() -> None:
    with pytest.raises(ValueError, match="at least one trained item vector"):
        backfill_two_tower_item_vectors(
            existing_rows=[{"parent_asin": "a", "embedding": []}],
            catalog_rows=[{"parent_asin": "a"}],
        )
