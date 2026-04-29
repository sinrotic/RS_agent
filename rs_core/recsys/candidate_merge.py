from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl
from rs_core.recsys.types import MergedCandidate, RecallCandidate


def load_popular_candidates(path: str | Path, limit: int | None = None) -> list[RecallCandidate]:
    candidates: list[RecallCandidate] = []
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin", "")
        if not item_id:
            continue
        candidates.append(
            RecallCandidate(
                item_id=item_id,
                source="popular",
                score=float(row.get("pop_score", 0.0) or 0.0),
                category=row.get("category", ""),
                metadata=row,
            )
        )
        if limit and len(candidates) >= limit:
            break
    return candidates


def load_itemcf_by_source(
    path: str | Path,
    source: str,
    allowed_src_items: set[str] | None = None,
) -> dict[str, list[RecallCandidate]]:
    by_source: dict[str, list[RecallCandidate]] = defaultdict(list)
    for row in iter_jsonl(path):
        src_item = row.get("src_item", "")
        if allowed_src_items is not None and src_item not in allowed_src_items:
            continue
        dst_item = row.get("dst_item", "")
        if not src_item or not dst_item:
            continue
        by_source[src_item].append(
            RecallCandidate(
                item_id=dst_item,
                source=source,
                score=float(row.get("score", 0.0) or 0.0),
                metadata=row,
            )
        )
    for rows in by_source.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_source


def load_category_candidates(path: str | Path) -> dict[str, list[RecallCandidate]]:
    by_bucket: dict[str, list[RecallCandidate]] = {}
    for row in iter_jsonl(path):
        bucket = row.get("bucket", "")
        by_bucket[bucket] = [
            RecallCandidate(
                item_id=item.get("parent_asin", ""),
                source="category",
                score=float(item.get("score", 0.0) or 0.0),
                metadata=item,
            )
            for item in row.get("top_items", [])
            if item.get("parent_asin")
        ]
    return by_bucket


def load_semantic_index(path: str | Path, token_fields: list[str] | None = None) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin", "")
        if not item_id:
            continue
        metadata = dict(row)
        metadata["semantic_tokens"] = _semantic_tokens(row, token_fields)
        index[item_id] = metadata
    return index


def semantic_candidates_for_user(
    user_sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("semantic_enabled") or not semantic_index:
        return []
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_items = list(dict.fromkeys(reversed(user_sequence.get("recent_positive_item_sequence", [])[-10:])))
    seed_tokens: set[str] = set()
    seed_categories: set[str] = set()
    for item_id in seed_items:
        record = semantic_index.get(item_id)
        if not record:
            continue
        seed_tokens.update(record.get("semantic_tokens", set()))
        seed_categories.update(_semantic_categories(record))
    if not seed_tokens and not seed_categories:
        return []

    limit = int(config.get("semantic_per_user", 20))
    min_overlap = int(config.get("semantic_min_overlap", 2))
    rows: list[RecallCandidate] = []
    for item_id, record in semantic_index.items():
        if item_id in seen_items:
            continue
        candidate_tokens = record.get("semantic_tokens", set())
        overlap = len(seed_tokens & candidate_tokens)
        if overlap < min_overlap:
            continue
        category_overlap = len(seed_categories & _semantic_categories(record))
        score = _semantic_score(overlap, seed_tokens, candidate_tokens, category_overlap, config)
        rows.append(
            RecallCandidate(
                item_id=item_id,
                source="semantic",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata={k: v for k, v in record.items() if k != "semantic_tokens"},
            )
        )
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def merge_for_user(
    user_sequence: dict[str, Any],
    popular: list[RecallCandidate],
    itemcf_weak: dict[str, list[RecallCandidate]],
    itemcf_strong: dict[str, list[RecallCandidate]],
    category_top: dict[str, list[RecallCandidate]],
    item_category: dict[str, str],
    config: dict,
    semantic_index: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[MergedCandidate], bool]:
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    raw: list[RecallCandidate] = []
    per_seed = int(config.get("itemcf_per_seed", 20))
    for seed in reversed(user_sequence.get("recent_positive_item_sequence", [])[-10:]):
        raw.extend(itemcf_weak.get(seed, [])[:per_seed])
    for seed in reversed(user_sequence.get("recent_strong_positive_item_sequence", [])[-10:]):
        raw.extend(itemcf_strong.get(seed, [])[:per_seed])

    buckets = _category_buckets(user_sequence, item_category)
    category_limit = int(config.get("category_per_user", 20))
    for bucket in buckets:
        raw.extend(category_top.get(bucket, [])[:category_limit])

    raw.extend(semantic_candidates_for_user(user_sequence, semantic_index or {}, config))

    fallback_used = not raw
    raw.extend(popular[: int(config.get("popular_fallback_count", 50))])
    merged = merge_candidates(raw, seen_items=seen_items)
    has_non_popular_candidate = any(
        source != "popular" for candidate in merged for source in candidate.sources
    )
    fallback_used = fallback_used or not has_non_popular_candidate
    return _limit_candidate_pool(merged, int(config.get("candidate_pool_size", 50)), config), fallback_used


def merge_candidates(candidates: list[RecallCandidate], seen_items: set[str] | None = None) -> list[MergedCandidate]:
    seen_items = seen_items or set()
    merged: dict[str, MergedCandidate] = {}
    for candidate in candidates:
        if not candidate.item_id or candidate.item_id in seen_items:
            continue
        current = merged.get(candidate.item_id)
        if current is None:
            current = MergedCandidate(
                item_id=candidate.item_id,
                sources=[],
                source_scores={},
                category=candidate.category or str(candidate.metadata.get("category", "")),
                metadata=dict(candidate.metadata),
            )
            merged[candidate.item_id] = current
        if candidate.source not in current.sources:
            current.sources.append(candidate.source)
        current.source_scores[candidate.source] = max(
            float(current.source_scores.get(candidate.source, 0.0)), candidate.score
        )
        if not current.category:
            current.category = candidate.category or str(candidate.metadata.get("category", ""))
        current.metadata.update({k: v for k, v in candidate.metadata.items() if k not in current.metadata})
    rows = list(merged.values())
    rows.sort(key=lambda item: (-sum(item.source_scores.values()), item.item_id))
    return rows


def _limit_candidate_pool(candidates: list[MergedCandidate], pool_size: int, config: dict) -> list[MergedCandidate]:
    minimums = config.get("candidate_source_minimums", {})
    if not minimums:
        return candidates[:pool_size]
    selected: dict[str, MergedCandidate] = {}
    for group, minimum in minimums.items():
        sources = _candidate_group_sources(group)
        eligible = [candidate for candidate in candidates if any(source in candidate.sources for source in sources)]
        for candidate in eligible[: int(minimum)]:
            selected[candidate.item_id] = candidate
    for candidate in candidates:
        if len(selected) >= pool_size:
            break
        selected.setdefault(candidate.item_id, candidate)
    rows = list(selected.values())[:pool_size]
    rows.sort(key=lambda item: (-sum(item.source_scores.values()), item.item_id))
    return rows


def _candidate_group_sources(group: str) -> set[str]:
    if group == "itemcf":
        return {"itemcf_weak", "itemcf_strong"}
    return {group}


def _semantic_score(
    overlap: int,
    seed_tokens: set[str],
    candidate_tokens: set[str],
    category_overlap: int,
    config: dict,
) -> float:
    if config.get("semantic_score_mode") == "normalized":
        union_size = len(seed_tokens | candidate_tokens)
        jaccard = overlap / union_size if union_size else 0.0
        return round(jaccard * 100.0 + float(category_overlap) * float(config.get("semantic_category_weight", 2.0)), 6)
    return float(overlap) + float(category_overlap) * float(config.get("semantic_category_weight", 2.0))


def _category_buckets(user_sequence: dict[str, Any], item_category: dict[str, str]) -> list[str]:
    buckets: list[str] = []
    for item_id in reversed(user_sequence.get("recent_positive_item_sequence", [])):
        category = item_category.get(item_id, "")
        if category:
            bucket = f"main::{category}"
            if bucket not in buckets:
                buckets.append(bucket)
    return buckets


def _semantic_tokens(row: dict[str, Any], token_fields: list[str] | None = None) -> set[str]:
    fields = token_fields or ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"]
    text_parts: list[str] = []
    for field in fields:
        value = row.get(field, "")
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        else:
            text_parts.append(str(value))
    return {token for token in re.findall(r"[a-z0-9]+", " ".join(text_parts).lower()) if len(token) >= 3}


def _semantic_categories(row: dict[str, Any]) -> set[str]:
    categories = {str(row.get("main_category", "")), str(row.get("category", ""))}
    categories.update(str(item) for item in row.get("categories_flat", []))
    categories.update(str(item) for item in row.get("source_categories", []))
    return {category.lower() for category in categories if category}
