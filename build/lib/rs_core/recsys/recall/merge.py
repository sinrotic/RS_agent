from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

from rs_core.recsys.types import MergedCandidate

T = TypeVar("T")


@dataclass(frozen=True)
class MergeResult:
    candidates: list[MergedCandidate]
    added_candidates: list[MergedCandidate]
    source_used: dict[str, int]


def merge_candidates_with_fallback(
    *,
    existing_candidates: Iterable[MergedCandidate],
    fallback_candidates: Iterable[T],
    target_count: int,
    history_items: set[str],
    fallback_item_id: Callable[[T], str],
    fallback_source: Callable[[T], str],
    to_merged_candidate: Callable[[T], MergedCandidate],
    source_caps: dict[str, int] | None = None,
) -> MergeResult:
    candidates: list[MergedCandidate] = []
    added_candidates: list[MergedCandidate] = []
    seen: set[str] = set()
    source_used: dict[str, int] = {}

    for candidate in existing_candidates:
        item_id = str(candidate.item_id)
        if item_id in seen or item_id in history_items:
            continue
        candidates.append(candidate)
        seen.add(item_id)
        if len(candidates) >= target_count:
            return MergeResult(candidates=candidates, added_candidates=added_candidates, source_used=source_used)

    caps = source_caps or {}
    for fallback in fallback_candidates:
        if len(candidates) >= target_count:
            break
        item_id = fallback_item_id(fallback)
        if not item_id or item_id in seen or item_id in history_items:
            continue
        source = fallback_source(fallback)
        if source_used.get(source, 0) >= caps.get(source, target_count):
            continue
        merged = to_merged_candidate(fallback)
        candidates.append(merged)
        added_candidates.append(merged)
        seen.add(item_id)
        source_used[source] = source_used.get(source, 0) + 1

    return MergeResult(candidates=candidates, added_candidates=added_candidates, source_used=source_used)


def duplicate_count(values: Iterable[Any]) -> int:
    items = [str(value) for value in values]
    return len(items) - len(set(items))
