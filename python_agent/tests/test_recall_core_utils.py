from __future__ import annotations

import pytest

from rs_core.online.recall import (
    CANONICAL_SOURCES,
    canonicalize_source_label,
    canonicalize_source_set,
    duplicate_count,
    forbidden_source_labels,
    merge_candidates_with_fallback,
    unknown_source_labels,
)
from rs_core.common.recsys_types import MergedCandidate

pytestmark = pytest.mark.unit


def test_core_canonical_source_label_normalizes_aliases_and_hyphens() -> None:
    assert canonicalize_source_label("popular_recall") == "popular"
    assert canonicalize_source_label("category-top-items") == "category"
    assert canonicalize_source_label("co_visit") == "co_visit_fallback_repair"
    assert canonicalize_source_label("usercf") == "usercf_recall"
    assert canonicalize_source_label("swing") == "swing_recall"
    assert canonicalize_source_label("youtube_dnn") == "two_tower"
    assert canonicalize_source_label("two-tower-recall") == "two_tower"


def test_core_canonicalize_source_set_expands_groups_and_drops_blank_values() -> None:
    sources = canonicalize_source_set(["popular_recall", "itemcf", "", None, "semantic_recall"])

    assert sources == {"popular", "itemcf_weak", "itemcf_strong", "semantic"}


def test_core_source_validation_reports_forbidden_before_group_expansion_and_unknown_after_normalization() -> None:
    sources = ["itemcf", "legacy_probe", "two_tower_seed", "popular_recall"]

    assert forbidden_source_labels(sources) == {"itemcf", "two_tower_seed"}
    assert unknown_source_labels(sources) == {"legacy_probe"}
    assert unknown_source_labels(CANONICAL_SOURCES) == set()


def test_core_merge_preserves_existing_candidates_first_dedupes_truncates_and_excludes_history() -> None:
    existing = [
        MergedCandidate("existing_1", ["popular"], {"popular": 1.0}),
        MergedCandidate("existing_1", ["category"], {"category": 0.9}),
        MergedCandidate("seen_existing", ["popular"], {"popular": 0.8}),
        MergedCandidate("existing_2", ["semantic"], {"semantic": 0.7}),
    ]
    fallback_rows = [
        {"item_id": "existing_2", "source": "fallback_category", "score": 0.6},
        {"item_id": "seen_fallback", "source": "fallback_category", "score": 0.5},
        {"item_id": "fallback_1", "source": "fallback_category", "score": 0.4},
        {"item_id": "fallback_2", "source": "fallback_category", "score": 0.3},
        {"item_id": "fallback_3", "source": "fallback_popular", "score": 0.2},
    ]

    result = merge_candidates_with_fallback(
        existing_candidates=existing,
        fallback_candidates=fallback_rows,
        target_count=4,
        history_items={"seen_existing", "seen_fallback"},
        fallback_item_id=lambda row: str(row["item_id"]),
        fallback_source=lambda row: str(row["source"]),
        to_merged_candidate=lambda row: MergedCandidate(
            str(row["item_id"]),
            [str(row["source"])],
            {str(row["source"]): float(row["score"])},
        ),
        source_caps={"fallback_category": 1},
    )

    assert [candidate.item_id for candidate in result.candidates] == ["existing_1", "existing_2", "fallback_1", "fallback_3"]
    assert [candidate.item_id for candidate in result.added_candidates] == ["fallback_1", "fallback_3"]
    assert result.source_used == {"fallback_category": 1, "fallback_popular": 1}
    assert duplicate_count(candidate.item_id for candidate in result.candidates) == 0


def test_core_merge_truncates_existing_candidates_without_consuming_fallback() -> None:
    existing = [MergedCandidate(f"existing_{index}", ["popular"], {"popular": 1.0}) for index in range(3)]

    result = merge_candidates_with_fallback(
        existing_candidates=existing,
        fallback_candidates=[{"item_id": "fallback_1", "source": "fallback_popular", "score": 1.0}],
        target_count=2,
        history_items=set(),
        fallback_item_id=lambda row: str(row["item_id"]),
        fallback_source=lambda row: str(row["source"]),
        to_merged_candidate=lambda row: MergedCandidate(str(row["item_id"]), [str(row["source"])], {str(row["source"]): float(row["score"])}),
    )

    assert [candidate.item_id for candidate in result.candidates] == ["existing_0", "existing_1"]
    assert result.added_candidates == []
    assert result.source_used == {}
