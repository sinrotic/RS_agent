from __future__ import annotations

import json
import math

import pytest

pytestmark = pytest.mark.unit

from rs_core.workflow.pool500_ranking_adapter import (
    PASS,
    POOL500_LINEAGE_KEY,
    STOP,
    adapt_pool500_jsonl_to_candidates,
    adapt_pool500_rows_to_candidates,
)


def _row(
    user_id: str = "u1",
    item_id: str = "i1",
    source: str = "popular_recall",
    score: float = 0.9,
    rank: int = 1,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "item_id": item_id,
        "source": source,
        "score": score,
        "rank": rank,
        "metadata": {"category": "Audio", "title_clean": "headphones"} if metadata is None else metadata,
    }


def _blocker_codes(result: dict[str, object]) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}  # type: ignore[index]


def _diagnostic_codes(result: dict[str, object]) -> set[str]:
    return {diagnostic["code"] for diagnostic in result["diagnostics"]}  # type: ignore[index]


def test_pool500_adapter_merges_same_user_item_across_sources_with_lineage() -> None:
    result = adapt_pool500_rows_to_candidates(
        [
            _row(source="popular_recall", score=0.9, rank=1),
            _row(source="semantic", score=0.8, rank=3, metadata={"category": "Audio", "semantic_reason": "title match"}),
        ],
        candidate_pool_limit=500,
    )

    assert result["status"] == PASS
    candidates = result["candidates_by_user"]["u1"]  # type: ignore[index]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.item_id == "i1"
    assert candidate.sources == ["popular", "semantic"]
    assert candidate.source_scores == {"popular": 0.9, "semantic": 0.8}
    assert candidate.category == "Audio"
    assert candidate.metadata[POOL500_LINEAGE_KEY] == [
        {"source": "popular", "score": 0.9, "rank": 1, "metadata": {"category": "Audio", "title_clean": "headphones"}},
        {"source": "semantic", "score": 0.8, "rank": 3, "metadata": {"category": "Audio", "semantic_reason": "title match"}},
    ]
    assert result["blockers"] == []
    assert "POOL500_USER_CANDIDATE_POOL_UNDERFILLED" in _diagnostic_codes(result)


def test_pool500_adapter_reads_jsonl_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "pool500.jsonl"
    path.write_text(json.dumps(_row(user_id="u2", item_id="i2")) + "\n", encoding="utf-8")

    result = adapt_pool500_jsonl_to_candidates(path)

    assert result["status"] == PASS
    candidates = result["candidates_by_user"]["u2"]  # type: ignore[index]
    assert candidates[0].item_id == "i2"


@pytest.mark.parametrize(
    ("row", "expected_code"),
    [
        ({"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "metadata": {}}, "POOL500_REQUIRED_FIELD_MISSING"),
        (_row(score=math.inf), "POOL500_NON_FINITE_SCORE"),
        (_row(rank=0), "POOL500_INVALID_RANK"),
        (_row(metadata=[]), "POOL500_METADATA_OBJECT_REQUIRED"),
        (_row(source="itemcf"), "POOL500_FORBIDDEN_SOURCE_LABEL"),
        (_row(source="custom_source"), "POOL500_NON_CANONICAL_SOURCE_LABEL"),
    ],
)
def test_pool500_adapter_reports_schema_source_and_value_blockers(row: dict[str, object], expected_code: str) -> None:
    result = adapt_pool500_rows_to_candidates([row])

    assert result["status"] == STOP
    assert expected_code in _blocker_codes(result)


def test_pool500_adapter_blocks_duplicate_user_item_source() -> None:
    result = adapt_pool500_rows_to_candidates([_row(), _row(score=0.8, rank=2)])

    assert result["status"] == STOP
    assert "POOL500_DUPLICATE_USER_ITEM_SOURCE" in _blocker_codes(result)


def test_pool500_adapter_blocks_per_user_candidate_count_over_limit() -> None:
    rows = [_row(item_id=f"i{index}", rank=index + 1) for index in range(3)]

    result = adapt_pool500_rows_to_candidates(rows, candidate_pool_limit=2)

    assert result["status"] == STOP
    assert "POOL500_USER_CANDIDATE_LIMIT_EXCEEDED" in _blocker_codes(result)


def test_pool500_adapter_allows_extra_diagnostic_sources_only_when_explicit() -> None:
    row = _row(source="cold_start_category_sibling")

    blocked = adapt_pool500_rows_to_candidates([row])
    allowed = adapt_pool500_rows_to_candidates([row], extra_allowed_sources={"cold_start_category_sibling"})

    assert blocked["status"] == STOP
    assert "POOL500_NON_CANONICAL_SOURCE_LABEL" in _blocker_codes(blocked)
    assert allowed["status"] == PASS
    candidate = allowed["candidates_by_user"]["u1"][0]  # type: ignore[index]
    assert candidate.sources == ["cold_start_category_sibling"]
