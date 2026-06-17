from __future__ import annotations

from typing import Any

CANONICAL_SOURCES = {
    "popular",
    "category",
    "semantic",
    "semantic_title_category_expansion",
    "itemcf_weak",
    "itemcf_strong",
    "co_visit_fallback_repair",
    "usercf_recall",
    "swing_recall",
    "two_tower",
}
SOURCE_ALIASES = {
    "popular_recall": "popular",
    "category_top_items": "category",
    "category_recall_items": "category",
    "category_long_tail_recall": "category",
    "semantic_recall": "semantic",
    "metadata_neighbor_recall": "co_visit_fallback_repair",
    "co_visit": "co_visit_fallback_repair",
    "co_visit_repair": "co_visit_fallback_repair",
    "co_visit_fallback": "co_visit_fallback_repair",
    "usercf": "usercf_recall",
    "swing": "swing_recall",
    "youtube_dnn": "two_tower",
    "two_tower_youtube_dnn": "two_tower",
    "two_tower_recall": "two_tower",
}
GROUP_SOURCE_EXPANSIONS = {
    "itemcf": {"itemcf_weak", "itemcf_strong"},
}
FORBIDDEN_SOURCE_LABELS = {"itemcf", "two_tower_seed", "final_two_tower_seed"}
FINAL_SOURCE_WHITELIST = CANONICAL_SOURCES


def canonicalize_source_label(source: Any) -> str:
    label = str(source).strip().lower().replace("-", "_")
    return SOURCE_ALIASES.get(label, label)


def canonicalize_source_set(sources: Any) -> set[str]:
    canonical_sources: set[str] = set()
    for source in _as_list(sources):
        if not str(source).strip():
            continue
        label = canonicalize_source_label(source)
        canonical_sources.update(GROUP_SOURCE_EXPANSIONS.get(label, {label}))
    return canonical_sources


def unknown_source_labels(sources: Any, allowed_sources: set[str] | None = None) -> set[str]:
    allowed = allowed_sources or CANONICAL_SOURCES
    return canonicalize_source_set(sources) - allowed - forbidden_source_labels(sources)


def forbidden_source_labels(sources: Any, forbidden_sources: set[str] | None = None) -> set[str]:
    forbidden = forbidden_sources or FORBIDDEN_SOURCE_LABELS
    raw_sources = {str(source).strip().lower().replace("-", "_") for source in _as_list(sources) if str(source).strip()}
    return raw_sources & forbidden


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        return [item for item in value.values() if item is not None]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item is not None]
    return [value]
