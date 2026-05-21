from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rs_lab.experiments.recall.pool500.fallback_completion.config import Pool500FallbackCompletionConfig
from rs_lab.experiments.recall.pool500.fallback_completion.types import FallbackCompletionContext

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]{3,}")


def build_fallback_completion_context(
    *,
    batch_sequences: list[dict[str, Any]],
    clean_manifest: dict[str, Any],
    view_outputs: dict[str, Any],
    config: Pool500FallbackCompletionConfig,
) -> FallbackCompletionContext:
    paths = _resolve_input_paths(clean_manifest, view_outputs, config)
    seed_items_by_user = {str(row.get("user_id") or row.get("reviewer_id") or ""): _seed_items(row) for row in batch_sequences}
    seed_item_ids = {item_id for items in seed_items_by_user.values() for item_id in items}

    seed_meta_by_item, seed_keys_by_user, scanned_items = _build_seed_metadata(paths["canonical_items"], seed_items_by_user)
    seed_keys = _merge_seed_keys(seed_keys_by_user.values())
    token_keys = _tokens_for_seed_meta(seed_meta_by_item, config)

    category_recall_index, scanned_category_rows = _build_category_recall_index(paths["category_recall_items"], seed_keys, config)
    category_top_index, scanned_top_rows = _build_category_top_index(paths["category_top_items"], seed_keys, config)
    metadata_neighbor_index, metadata_scanned_rows = _build_metadata_neighbor_index(paths["category_recall_items"], seed_keys, seed_item_ids, config)
    semantic_token_index, scanned_semantic_rows = _build_semantic_token_index(paths.get("semantic_inverted_index") or paths.get("semantic_recall_inputs"), token_keys, seed_meta_by_item, config)
    global_popular_items, scanned_popular_rows = _read_bounded_rows(paths["popular_recall"], config.target_candidate_count * 4)

    return FallbackCompletionContext(
        seed_meta_by_item=seed_meta_by_item,
        seed_keys_by_user=seed_keys_by_user,
        category_recall_index=category_recall_index,
        category_top_index=category_top_index,
        metadata_neighbor_index=metadata_neighbor_index,
        semantic_token_index=semantic_token_index,
        global_popular_items=global_popular_items,
        resource_audit={
            "scanned_files": {name: str(path) for name, path in paths.items() if path is not None},
            "read_rows": {
                "canonical_items": scanned_items,
                "category_recall_items": scanned_category_rows + metadata_scanned_rows,
                "category_top_items": scanned_top_rows,
                "popular_recall": scanned_popular_rows,
                "semantic": scanned_semantic_rows,
            },
            "index_sizes": {
                "seed_meta_by_item": len(seed_meta_by_item),
                "seed_keys_by_user": len(seed_keys_by_user),
                "category_recall_index": sum(len(rows) for rows in category_recall_index.values()),
                "category_top_index": sum(len(rows) for rows in category_top_index.values()),
                "metadata_neighbor_index": sum(len(rows) for rows in metadata_neighbor_index.values()),
                "semantic_token_index": sum(len(rows) for rows in semantic_token_index.values()),
                "global_popular_items": len(global_popular_items),
            },
            "heavy_job": False,
        },
    )


def _resolve_input_paths(clean_manifest: dict[str, Any], view_outputs: dict[str, Any], config: Pool500FallbackCompletionConfig) -> dict[str, Path | None]:
    paths = {
        "canonical_items": _path_from(clean_manifest, "canonical_items_path") or _path_from(clean_manifest, "canonical_items"),
        "category_recall_items": _path_from(view_outputs, "category_recall_items"),
        "category_top_items": _path_from(view_outputs, "category_top_items"),
        "popular_recall": _path_from(view_outputs, "popular_recall"),
        "semantic_inverted_index": _path_from(view_outputs, "semantic_inverted_index"),
        "semantic_recall_inputs": _path_from(view_outputs, "semantic_recall_inputs") or _path_from(view_outputs, "semantic_path"),
    }
    required = ("canonical_items", "category_recall_items", "category_top_items", "popular_recall")
    missing = [name for name in required if paths[name] is None]
    if missing:
        raise ValueError(f"missing fallback completion inputs: {', '.join(missing)}")
    for name, path in paths.items():
        if path is None:
            continue
        path_parts = {part.lower() for part in path.parts}
        if any(marker.lower() in path_parts for marker in config.forbidden_data_markers):
            raise ValueError(f"forbidden fallback completion input path for {name}: {path}")
    return paths


def _path_from(payload: dict[str, Any], key: str) -> Path | None:
    value = payload.get(key)
    if isinstance(value, dict):
        value = value.get("output_path") or value.get("path")
    if value is None:
        outputs = payload.get("outputs")
        if isinstance(outputs, dict):
            value = outputs.get(key)
            if isinstance(value, dict):
                value = value.get("output_path") or value.get("path")
    return Path(value) if value else None


def _build_seed_metadata(path: Path | None, seed_items_by_user: dict[str, list[str]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, set[str]]], int]:
    wanted = {item_id for items in seed_items_by_user.values() for item_id in items}
    seed_meta_by_item: dict[str, dict[str, Any]] = {}
    scanned = 0
    if path is not None:
        for row in _iter_jsonl(path):
            scanned += 1
            item_id = _item_id(row)
            if item_id in wanted:
                seed_meta_by_item[item_id] = row
    seed_keys_by_user: dict[str, dict[str, set[str]]] = {}
    for user_id, item_ids in seed_items_by_user.items():
        seed_keys_by_user[user_id] = _keys_for_metas(seed_meta_by_item.get(item_id, {}) for item_id in item_ids)
    return seed_meta_by_item, seed_keys_by_user, scanned


def _build_category_recall_index(path: Path | None, seed_keys: dict[str, set[str]], config: Pool500FallbackCompletionConfig) -> tuple[dict[str, list[dict[str, Any]]], int]:
    index: dict[str, list[dict[str, Any]]] = {}
    wanted = _category_keys(seed_keys)
    scanned = 0
    if path is None:
        return index, scanned
    for row in _iter_jsonl(path):
        scanned += 1
        for key in _row_category_keys(row):
            if key in wanted:
                _append_bounded(index, key, row, config.max_index_bucket_size)
    return index, scanned


def _build_category_top_index(path: Path | None, seed_keys: dict[str, set[str]], config: Pool500FallbackCompletionConfig) -> tuple[dict[str, list[dict[str, Any]]], int]:
    index: dict[str, list[dict[str, Any]]] = {}
    wanted = _category_keys(seed_keys)
    scanned = 0
    if path is None:
        return index, scanned
    for row in _iter_jsonl(path):
        scanned += 1
        bucket = str(row.get("bucket") or "")
        bucket_key = bucket.split("::", 1)[1] if "::" in bucket else bucket
        if bucket_key not in wanted:
            continue
        for item in row.get("top_items", []) or []:
            candidate = dict(item)
            candidate.setdefault("category", bucket_key)
            _append_bounded(index, bucket_key, candidate, config.max_index_bucket_size)
            _append_bounded(index, bucket, candidate, config.max_index_bucket_size)
    return index, scanned


def _build_metadata_neighbor_index(path: Path | None, seed_keys: dict[str, set[str]], seed_item_ids: set[str], config: Pool500FallbackCompletionConfig) -> tuple[dict[str, list[dict[str, Any]]], int]:
    index: dict[str, list[dict[str, Any]]] = {}
    scanned = 0
    if path is None:
        return index, scanned
    for row in _iter_jsonl(path):
        scanned += 1
        if _item_id(row) in seed_item_ids:
            continue
        for field in ("brand", "store", "category", "main_category"):
            value = str(row.get(field) or "").strip()
            if value and value in seed_keys.get(field, set()):
                enriched = dict(row)
                enriched["matched_field"] = field
                enriched["matched_value"] = value
                _append_bounded(index, f"{field}::{value}", enriched, config.max_index_bucket_size)
    return index, scanned


def _build_semantic_token_index(path: Path | None, token_keys: set[str], seed_meta_by_item: dict[str, dict[str, Any]], config: Pool500FallbackCompletionConfig) -> tuple[dict[str, list[dict[str, Any]]], int]:
    index: dict[str, list[dict[str, Any]]] = {}
    scanned = 0
    if path is None or not token_keys:
        return index, scanned
    seed_ids = set(seed_meta_by_item)
    for row in _iter_jsonl(path):
        scanned += 1
        token = str(row.get("token") or "").lower()
        if token:
            if token not in token_keys:
                continue
            for item_id in row.get("parent_asins", []) or []:
                if item_id not in seed_ids:
                    _append_bounded(index, token, {"parent_asin": item_id, "score": 0.0}, config.max_index_bucket_size)
            continue
        item_id = _item_id(row)
        if item_id in seed_ids:
            continue
        for row_token in _tokens_for_text(row):
            if row_token in token_keys:
                _append_bounded(index, row_token, row, config.max_index_bucket_size)
    return index, scanned


def _read_bounded_rows(path: Path | None, limit: int) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    scanned = 0
    if path is None:
        return rows, scanned
    for row in _iter_jsonl(path):
        scanned += 1
        if len(rows) < limit:
            rows.append(row)
    return rows, scanned


def _seed_items(sequence: dict[str, Any]) -> list[str]:
    items = sequence.get("recent_positive_item_sequence") or sequence.get("positive_item_sequence") or sequence.get("recent_item_sequence") or sequence.get("item_sequence") or []
    return [_clean_item_id(item) for item in items if _clean_item_id(item)]


def _keys_for_metas(metas: Any) -> dict[str, set[str]]:
    keys = {"brand": set(), "store": set(), "category": set(), "main_category": set(), "categories_flat": set()}
    for meta in metas:
        for field in ("brand", "store", "category", "main_category"):
            value = str(meta.get(field) or "").strip()
            if value:
                keys[field].add(value)
        for value in meta.get("categories_flat", []) or []:
            if value:
                keys["categories_flat"].add(str(value))
    return keys


def _merge_seed_keys(seed_key_dicts: Any) -> dict[str, set[str]]:
    merged = {"brand": set(), "store": set(), "category": set(), "main_category": set(), "categories_flat": set()}
    for seed_keys in seed_key_dicts:
        for key, values in seed_keys.items():
            merged.setdefault(key, set()).update(values)
    return merged


def _category_keys(seed_keys: dict[str, set[str]]) -> set[str]:
    return set(seed_keys.get("category", set())) | set(seed_keys.get("main_category", set())) | set(seed_keys.get("categories_flat", set()))


def _row_category_keys(row: dict[str, Any]) -> set[str]:
    keys = {str(row.get("category") or "").strip(), str(row.get("main_category") or "").strip()}
    keys.update(str(value).strip() for value in row.get("categories_flat", []) or [])
    return {key for key in keys if key}


def _tokens_for_seed_meta(seed_meta_by_item: dict[str, dict[str, Any]], config: Pool500FallbackCompletionConfig) -> set[str]:
    tokens: set[str] = set()
    for meta in seed_meta_by_item.values():
        for token in _tokens_for_text(meta):
            tokens.add(token)
            if len(tokens) >= config.semantic_token_limit_per_seed * max(len(seed_meta_by_item), 1):
                return tokens
    return tokens


def _tokens_for_text(row: dict[str, Any]) -> set[str]:
    text_parts = [str(row.get(field) or "") for field in ("title", "title_clean", "category", "main_category", "store", "description_text", "features_text", "item_text")]
    text_parts.extend(str(value) for value in row.get("categories_flat", []) or [])
    return {token for token in TOKEN_PATTERN.findall(" ".join(text_parts).lower())}


def _append_bounded(index: dict[str, list[dict[str, Any]]], key: str, row: dict[str, Any], limit: int) -> None:
    bucket = index.setdefault(key, [])
    if len(bucket) < limit:
        bucket.append(row)


def _iter_jsonl(path: Path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            line = line.strip()
            if line:
                yield json.loads(line)


def _item_id(row: dict[str, Any]) -> str:
    return _clean_item_id(row.get("item_id") or row.get("parent_asin") or row.get("asin"))


def _clean_item_id(value: Any) -> str:
    return str(value or "").strip()
