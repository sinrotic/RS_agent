from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from rs_lab.experiments.recall.pool500.fallback_completion.config import Pool500FallbackCompletionConfig
from rs_lab.experiments.recall.pool500.fallback_completion.types import FallbackCandidate, FallbackCompletionContext
from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import FallbackSource


def iter_source_candidates(
    *,
    user_id: str,
    seed_items: list[str],
    context: FallbackCompletionContext,
    config: Pool500FallbackCompletionConfig,
) -> Iterator[FallbackCandidate]:
    seed_keys = context.seed_keys_by_user.get(user_id, {})
    for source in config.source_ladder:
        if source is FallbackSource.PERSONALIZED_PRIMARY:
            continue
        if source is FallbackSource.SEED_CATEGORY_SIBLING:
            yield from _seed_category_sibling(seed_items, seed_keys, context, config)
        elif source is FallbackSource.SEED_METADATA_NEIGHBOR:
            yield from _seed_metadata_neighbor(seed_items, seed_keys, context, config)
        elif source is FallbackSource.SEED_SEMANTIC_TOKEN:
            yield from _seed_semantic_token(seed_items, context, config)
        elif source is FallbackSource.CATEGORY_POPULAR:
            yield from _category_popular(seed_keys, context, config)
        elif source is FallbackSource.SESSION_OR_CONTEXT_POPULAR:
            yield from _context_popular(seed_keys, context, config)
        elif source is FallbackSource.GLOBAL_DIVERSITY_POPULAR:
            yield from _global_diversity_popular(context, config)


def _seed_category_sibling(seed_items: list[str], seed_keys: dict[str, set[str]], context: FallbackCompletionContext, config: Pool500FallbackCompletionConfig) -> Iterator[FallbackCandidate]:
    fallback_source = FallbackSource.SEED_CATEGORY_SIBLING.value
    for category_key in _ordered_category_keys(seed_keys):
        for row in context.category_recall_index.get(category_key, []) + context.category_top_index.get(category_key, []):
            yield _candidate(row, fallback_source, config, {"seed_item_id": seed_items[0] if seed_items else "", "category_key": category_key})


def _seed_metadata_neighbor(seed_items: list[str], seed_keys: dict[str, set[str]], context: FallbackCompletionContext, config: Pool500FallbackCompletionConfig) -> Iterator[FallbackCandidate]:
    fallback_source = FallbackSource.SEED_METADATA_NEIGHBOR.value
    for field in ("brand", "store", "category", "main_category"):
        for value in sorted(seed_keys.get(field, set())):
            for row in context.metadata_neighbor_index.get(f"{field}::{value}", []):
                evidence = {"seed_item_id": seed_items[0] if seed_items else "", "matched_field": row.get("matched_field"), "matched_value": row.get("matched_value")}
                yield _candidate(row, fallback_source, config, evidence)


def _seed_semantic_token(seed_items: list[str], context: FallbackCompletionContext, config: Pool500FallbackCompletionConfig) -> Iterator[FallbackCandidate]:
    fallback_source = FallbackSource.SEED_SEMANTIC_TOKEN.value
    for seed_item_id in seed_items:
        for token in _tokens_for_meta(context.seed_meta_by_item.get(seed_item_id, {}), config):
            for row in context.semantic_token_index.get(token, []):
                yield _candidate(row, fallback_source, config, {"seed_item_id": seed_item_id, "matched_token": token})


def _category_popular(seed_keys: dict[str, set[str]], context: FallbackCompletionContext, config: Pool500FallbackCompletionConfig) -> Iterator[FallbackCandidate]:
    fallback_source = FallbackSource.CATEGORY_POPULAR.value
    for category_key in _ordered_category_keys(seed_keys):
        for row in context.category_top_index.get(category_key, []):
            yield _candidate(row, fallback_source, config, {"category_key": category_key, "fallback_reason": "category_popular_after_personalized_fallback_exhausted"})


def _context_popular(seed_keys: dict[str, set[str]], context: FallbackCompletionContext, config: Pool500FallbackCompletionConfig) -> Iterator[FallbackCandidate]:
    fallback_source = FallbackSource.SESSION_OR_CONTEXT_POPULAR.value
    wanted_categories = set(_ordered_category_keys(seed_keys))
    for row in context.global_popular_items:
        category = str(row.get("category") or "")
        if category in wanted_categories:
            yield _candidate(row, fallback_source, config, {"fallback_reason": "context_popular_after_seed_fallback_exhausted", "category": category})


def _global_diversity_popular(context: FallbackCompletionContext, config: Pool500FallbackCompletionConfig) -> Iterator[FallbackCandidate]:
    fallback_source = FallbackSource.GLOBAL_DIVERSITY_POPULAR.value
    per_category: dict[str, int] = {}
    cap = max(config.source_caps.get(fallback_source, config.target_candidate_count), 1)
    per_category_cap = max(1, cap // config.global_popular_category_diversity_buckets)
    for row in context.global_popular_items:
        category = str(row.get("category") or "")
        if category and per_category.get(category, 0) >= per_category_cap:
            continue
        per_category[category] = per_category.get(category, 0) + 1
        yield _candidate(row, fallback_source, config, {"fallback_reason": "global_diversity_popular_last_resort", "category": category})


def _candidate(row: dict[str, Any], fallback_source: str, config: Pool500FallbackCompletionConfig, evidence: dict[str, Any]) -> FallbackCandidate:
    item_id = _item_id(row)
    return FallbackCandidate(
        item_id=item_id,
        score=float(row.get("score") or row.get("time_decay_pop_score") or row.get("pop_score") or row.get("recent_pop_score") or 0.0),
        fallback_source=fallback_source,
        canonical_source=config.source_to_canonical_source[fallback_source],
        category=str(row.get("category") or row.get("category_key") or ""),
        evidence={key: value for key, value in evidence.items() if value is not None},
    )


def _ordered_category_keys(seed_keys: dict[str, set[str]]) -> list[str]:
    keys: list[str] = []
    for field in ("category", "main_category", "categories_flat"):
        keys.extend(sorted(seed_keys.get(field, set())))
    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def _tokens_for_meta(meta: dict[str, Any], config: Pool500FallbackCompletionConfig) -> list[str]:
    import re

    text_parts = [str(meta.get("title") or ""), str(meta.get("category") or ""), str(meta.get("main_category") or ""), str(meta.get("store") or "")]
    text_parts.extend(str(value) for value in meta.get("categories_flat", []) or [])
    stop_words = {"the", "and", "for", "with", "from", "this", "that", "your", "you", "are", "black", "white", "edition", "products", "product", "amazon", "into", "full", "size", "made", "great"}
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9]{3,}", " ".join(text_parts).lower()):
        if token in stop_words or token in seen:
            continue
        tokens.append(token)
        seen.add(token)
        if len(tokens) >= config.semantic_token_limit_per_seed:
            break
    return tokens


def _item_id(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("item_id") or row.get("parent_asin") or row.get("asin") or "").strip()
    return str(row or "").strip()
