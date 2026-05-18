from __future__ import annotations

import hashlib
import heapq
import math
import re
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json
from rs_core.recsys.types import MergedCandidate, RecallCandidate
from rs_core.recsys.vector_index import VectorIndex, average_vectors, load_vector_index_artifact


_SEMANTIC_SEED_CONTEXT_CACHE_LIMIT = 4
_SEMANTIC_SEED_CONTEXT_CACHE: dict[tuple[int, tuple[str, ...], float, int], dict[str, Any]] = {}
_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE_LIMIT = 4
_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE: dict[tuple[int, tuple[str, ...], int], dict[str, Any]] = {}
_METADATA_NEIGHBOR_INDEX_CACHE_LIMIT = 4
_METADATA_NEIGHBOR_INDEX_CACHE: dict[tuple[int, tuple[str, ...]], dict[str, Any]] = {}


def unique_recent_items(items: list[str], max_items_per_user: int) -> list[str]:
    recent = deque(maxlen=max_items_per_user)
    seen: set[str] = set()
    for item_id in reversed(items):
        if item_id in seen:
            continue
        seen.add(item_id)
        recent.appendleft(item_id)
        if len(recent) >= max_items_per_user:
            break
    return list(recent)



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
    return _load_item_pair_recall(path, source, allowed_src_items)


def load_item_graph_recall(
    path: str | Path,
    allowed_src_items: set[str] | None = None,
) -> dict[str, list[RecallCandidate]]:
    return _load_item_pair_recall(path, "item_graph", allowed_src_items)


def load_usercf_recall_sidecar(manifest_path: str | Path) -> dict[str, list[RecallCandidate]]:
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    if manifest.get("source") != "usercf_recall":
        raise ValueError(f"invalid usercf_recall manifest source: {manifest.get('source')!r}")
    if manifest.get("index_scope") != "FULL_DERIVED_INDEX":
        raise ValueError(f"invalid usercf_recall index_scope: {manifest.get('index_scope')!r}")
    if manifest.get("train_only") is not True:
        raise ValueError("usercf_recall manifest must be train_only")
    outputs = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    shard_paths = outputs.get("candidate_shards") if isinstance(outputs.get("candidate_shards"), list) else []
    by_user: dict[str, list[RecallCandidate]] = defaultdict(list)
    for shard_path in shard_paths:
        for line_number, row in enumerate(iter_jsonl(_resolve_manifest_path(manifest_path, shard_path)), start=1):
            user_id = str(row.get("user_id") or "")
            if not user_id:
                raise ValueError(f"missing user_id in usercf_recall shard row {line_number}: {shard_path}")
            candidates = row.get("candidates")
            if not isinstance(candidates, list):
                raise ValueError(f"missing candidates in usercf_recall shard row {line_number}: {shard_path}")
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    raise ValueError(f"invalid usercf_recall candidate in shard row {line_number}: {shard_path}")
                item_id = str(candidate.get("item_id") or "")
                if not item_id:
                    raise ValueError(f"missing item_id in usercf_recall shard row {line_number}: {shard_path}")
                source = str(candidate.get("source") or "usercf_recall")
                if source != "usercf_recall":
                    raise ValueError(f"invalid usercf_recall candidate source in shard row {line_number}: {source!r}")
                by_user[user_id].append(
                    RecallCandidate(
                        item_id=item_id,
                        source="usercf_recall",
                        score=float(candidate.get("score", 0.0) or 0.0),
                        metadata={"usercf_rank": int(candidate.get("rank", len(by_user[user_id]) + 1)), "usercf_manifest_path": str(manifest_path)},
                    )
                )
    for rows in by_user.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_user


def load_swing_recall_sidecar(manifest_path: str | Path) -> dict[str, list[RecallCandidate]]:
    manifest_path = Path(manifest_path)
    manifest = read_json(manifest_path)
    if manifest.get("source") != "swing_recall":
        raise ValueError(f"invalid swing_recall manifest source: {manifest.get('source')!r}")
    if manifest.get("index_scope") != "FULL_DERIVED_INDEX":
        raise ValueError(f"invalid swing_recall index_scope: {manifest.get('index_scope')!r}")
    if manifest.get("train_only") is not True:
        raise ValueError("swing_recall manifest must be train_only")
    artifacts = manifest.get("required_artifacts") if isinstance(manifest.get("required_artifacts"), dict) else {}
    edges_path = artifacts.get("swing_recall_edges") or manifest.get("edges_path")
    if not edges_path:
        raise ValueError("swing_recall manifest missing required_artifacts.swing_recall_edges")
    return _load_item_pair_recall(_resolve_manifest_path(manifest_path, edges_path), "swing_recall")


def load_graph_walk_seed_recall(
    path: str | Path,
    allowed_src_items: set[str] | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, list[RecallCandidate]]:
    if manifest_path is None:
        raise ValueError("graph_walk_seed manifest_path is required")
    _validate_graph_walk_seed_manifest(manifest_path, path)
    return _load_item_pair_recall(path, "graph_walk_seed", allowed_src_items, expected_algorithm="deepwalk")


def load_two_tower_seed_recall(
    path: str | Path,
    allowed_src_items: set[str] | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, list[RecallCandidate]]:
    if manifest_path is not None:
        _validate_two_tower_seed_manifest(manifest_path)
    by_source: dict[str, list[RecallCandidate]] = defaultdict(list)
    for line_number, row in enumerate(iter_jsonl(path), start=1):
        src_item = row.get("item_id")
        if not isinstance(src_item, str) or not src_item:
            raise ValueError(f"missing item_id in two_tower_seed sidecar row {line_number}")
        include_row = allowed_src_items is None or src_item in allowed_src_items
        neighbors = row.get("neighbors")
        if not isinstance(neighbors, list):
            raise ValueError(f"missing neighbors in two_tower_seed sidecar row {line_number}")
        seen_neighbors: set[str] = set()
        for neighbor_index, neighbor in enumerate(neighbors, start=1):
            if not isinstance(neighbor, dict):
                raise ValueError(f"invalid neighbor in two_tower_seed sidecar row {line_number}")
            dst_item = neighbor.get("item_id")
            if not isinstance(dst_item, str) or not dst_item:
                raise ValueError(f"missing neighbor item_id in two_tower_seed sidecar row {line_number}")
            if dst_item == src_item:
                raise ValueError(f"self neighbor in two_tower_seed sidecar row {line_number}: {src_item}")
            if dst_item in seen_neighbors:
                raise ValueError(f"duplicate neighbor item_id in two_tower_seed sidecar row {line_number}: {dst_item}")
            seen_neighbors.add(dst_item)
            rank = neighbor.get("rank", neighbor_index)
            try:
                score = float(neighbor.get("score", 0.0) or 0.0)
                rank_int = int(rank)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid neighbor score or rank in two_tower_seed sidecar row {line_number}") from exc
            metadata = {
                "two_tower_seed_src_item": src_item,
                "two_tower_seed_neighbor_rank": rank_int,
                "two_tower_seed_neighbor_score": score,
            }
            if include_row:
                by_source[src_item].append(
                    RecallCandidate(
                        item_id=dst_item,
                        source="two_tower_seed",
                        score=score,
                        metadata=metadata,
                    )
                )
    for rows in by_source.values():
        rows.sort(key=lambda item: (-item.score, item.item_id))
    return by_source


def _validate_two_tower_seed_manifest(path: str | Path) -> None:
    manifest = read_json(path)
    expected = {
        "phase": "1.18",
        "source": "two_tower_seed",
        "schema_version": "two_tower_seed_neighbors_v1",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"invalid two_tower_seed manifest {key}: {manifest.get(key)!r}")


def _validate_graph_walk_seed_manifest(manifest_path: str | Path, sidecar_path: str | Path) -> None:
    sidecar_path = Path(sidecar_path)
    if not sidecar_path.exists():
        raise FileNotFoundError(str(sidecar_path))
    manifest = read_json(manifest_path)
    expected = {
        "phase": "1.19",
        "source": "graph_walk_seed",
        "schema_version": "graph_walk_seed_pairs_v1",
        "algorithm": "deepwalk",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"invalid graph_walk_seed manifest {key}: {manifest.get(key)!r}")
    expected_hash = manifest.get("sidecar_hash")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise ValueError("invalid graph_walk_seed manifest sidecar_hash: missing")
    actual_hash = _sha256_file(Path(sidecar_path))
    if actual_hash != expected_hash:
        raise ValueError("invalid graph_walk_seed manifest sidecar_hash: mismatch")



def _resolve_manifest_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute() or path.exists():
        return path
    return manifest_path.parent / path


def _load_item_pair_recall(
    path: str | Path,
    source: str,
    allowed_src_items: set[str] | None = None,
    expected_algorithm: str | None = None,
) -> dict[str, list[RecallCandidate]]:
    by_source: dict[str, list[RecallCandidate]] = defaultdict(list)
    for line_number, row in enumerate(iter_jsonl(path), start=1):
        row_source = row.get("source")
        if row_source is not None and row_source != source:
            raise ValueError(f"invalid {source} sidecar source in row {line_number}: {row_source!r}")
        if expected_algorithm is not None and row.get("algorithm") != expected_algorithm:
            raise ValueError(f"invalid {source} sidecar algorithm in row {line_number}: {row.get('algorithm')!r}")
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


def load_two_tower_index(path: str | Path, token_fields: list[str] | None = None) -> dict[str, dict[str, Any]] | VectorIndex:
    if _looks_like_vector_artifact(path):
        return load_vector_index_artifact(path)

    index: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        item_id = row.get("parent_asin", "")
        if not item_id:
            continue
        metadata = dict(row)
        if "embedding" in row:
            metadata.setdefault("two_tower_source_name", "two_tower")
        metadata["two_tower_tokens"] = _semantic_tokens(row, token_fields)
        index[item_id] = metadata
    if index and all("embedding" in row for row in index.values()):
        return load_vector_index_artifact(path)
    return index


def semantic_candidates_for_user(
    user_sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("semantic_enabled") or not semantic_index:
        return []
    if config.get("semantic_score_mode") == "idf_seed_aware":
        return _semantic_seed_aware_candidates_for_user(user_sequence, semantic_index, config)

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


def semantic_title_category_expansion_candidates_for_user(
    user_sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    source_config = config.get("semantic_title_category_expansion", {})
    if not isinstance(source_config, dict) or not source_config.get("enabled") or not semantic_index:
        return []

    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_window = int(source_config.get("seed_window", 20))
    per_seed = int(source_config.get("per_seed", 10))
    limit = int(source_config.get("per_user", 20))
    min_title_overlap = int(source_config.get("min_title_overlap", 1))
    category_weight = float(source_config.get("category_weight", 2.0))
    weak_category_boost = float(source_config.get("weak_category_boost", 0.5))
    weak_categories = {str(item).lower() for item in source_config.get("weak_categories", [])}
    token_fields = [str(field) for field in source_config.get("text_fields", ["title_clean", "main_category", "categories_flat"])]

    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), seed_window)
    context = _semantic_title_category_context(semantic_index, token_fields)
    item_tokens = context["item_tokens"]
    item_categories = context["item_categories"]
    inverted_index = context["inverted_index"]

    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed_item in enumerate(seed_items):
        seed_tokens = item_tokens.get(seed_item, set())
        seed_categories = item_categories.get(seed_item, set())
        if not seed_tokens and not seed_categories:
            continue
        overlap_counts: Counter[str] = Counter()
        for token in seed_tokens:
            overlap_counts.update(inverted_index.get(token, set()))
        scored: list[tuple[float, str, int, int, str]] = []
        for item_id, overlap in overlap_counts.items():
            if item_id in seen_items or item_id == seed_item or overlap < min_title_overlap:
                continue
            category_overlap = len(seed_categories & item_categories.get(item_id, set()))
            if not category_overlap and source_config.get("require_category_overlap", True):
                continue
            candidate_categories = item_categories.get(item_id, set())
            boost = weak_category_boost if candidate_categories & weak_categories else 0.0
            reason = "weak_category_boost" if boost else "category_path" if category_overlap else "title_sim"
            score = float(overlap) + float(category_overlap) * category_weight + boost
            scored.append((round(score, 6), item_id, overlap, category_overlap, reason))
        for score, item_id, overlap, category_overlap, reason in heapq.nsmallest(per_seed, scored, key=lambda item: (-item[0], item[1])):
            record = semantic_index[item_id]
            candidate = RecallCandidate(
                item_id=item_id,
                source="semantic_title_category_expansion",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata={k: v for k, v in record.items() if k != "semantic_tokens"} | {
                    "reason": reason,
                    "seed_item_id": seed_item,
                    "source_score": score,
                    "source_rank": seed_rank,
                    "title_token_overlap": overlap,
                    "category_overlap": category_overlap,
                },
            )
            current = by_item.get(candidate.item_id)
            if current is None or candidate.score > current.score:
                by_item[candidate.item_id] = candidate

    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def two_tower_candidates_for_user(
    user_sequence: dict[str, Any],
    two_tower_index: dict[str, dict[str, Any]] | VectorIndex,
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("two_tower_enabled") or not two_tower_index:
        return []
    if isinstance(two_tower_index, VectorIndex):
        return _two_tower_vector_candidates_for_user(user_sequence, two_tower_index, config)

    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_window = int(config.get("two_tower_seed_window", 10))
    limit = int(config.get("two_tower_per_user", 20))
    min_overlap = int(config.get("two_tower_min_overlap", 1))
    recency_decay = float(config.get("two_tower_recency_decay", 0.85))
    token_fields = config.get("two_tower_text_fields")
    if token_fields is not None:
        token_fields = [str(field) for field in token_fields]

    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), seed_window)
    token_df = _two_tower_token_df(two_tower_index, token_fields)
    idf = {
        token: math.log((1.0 + len(two_tower_index)) / (1.0 + df)) + 1.0
        for token, df in token_df.items()
    }

    seed_vectors: list[tuple[str, int, dict[str, float], float]] = []
    for seed_rank, seed_item in enumerate(seed_items):
        seed_record = two_tower_index.get(seed_item)
        if not seed_record:
            continue
        vector = _two_tower_vector(_record_two_tower_tokens(seed_record, token_fields), idf)
        norm = _vector_norm(vector)
        if norm:
            seed_vectors.append((seed_item, seed_rank, vector, norm))
    if not seed_vectors:
        return []

    by_item: dict[str, RecallCandidate] = {}
    for item_id, record in two_tower_index.items():
        if item_id in seen_items:
            continue
        candidate_tokens = _record_two_tower_tokens(record, token_fields)
        candidate_vector = _two_tower_vector(candidate_tokens, idf)
        candidate_norm = _vector_norm(candidate_vector)
        if not candidate_norm:
            continue
        best_score = 0.0
        best_seed = ""
        best_seed_rank = 0
        best_overlap = 0
        for seed_item, seed_rank, seed_vector, seed_norm in seed_vectors:
            overlap = len(seed_vector.keys() & candidate_vector.keys())
            if overlap < min_overlap:
                continue
            score = _cosine_score(seed_vector, seed_norm, candidate_vector, candidate_norm) * (recency_decay**seed_rank)
            if score > best_score:
                best_score = score
                best_seed = seed_item
                best_seed_rank = seed_rank
                best_overlap = overlap
        if best_score <= 0.0:
            continue
        by_item[item_id] = RecallCandidate(
            item_id=item_id,
            source="two_tower",
            score=round(best_score, 6),
            category=str(record.get("main_category") or record.get("category", "")),
            metadata={k: v for k, v in record.items() if k != "two_tower_tokens"}
            | {"two_tower_seed_item": best_seed, "two_tower_seed_rank": best_seed_rank, "two_tower_overlap": best_overlap},
        )

    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def _two_tower_vector_candidates_for_user(
    user_sequence: dict[str, Any],
    two_tower_index: VectorIndex,
    config: dict,
) -> list[RecallCandidate]:
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    limit = int(config.get("two_tower_per_user", 20))
    seed_window = int(config.get("two_tower_seed_window", 10))
    recency_decay = float(config.get("two_tower_recency_decay", 0.85))
    user_id = str(user_sequence.get("user_id", ""))
    query_vector = two_tower_index.get_user_vector(user_id)
    if not query_vector:
        seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), seed_window)
        query_vector = average_vectors([two_tower_index.get_item_vector(item_id) for item_id in seed_items], recency_decay)
    rows = []
    for result in two_tower_index.search(query_vector, limit=limit, excluded_items=seen_items):
        metadata = dict(result.metadata)
        metadata.update(two_tower_index.model_metadata)
        metadata.setdefault("two_tower_source_name", two_tower_index.source_name)
        metadata.setdefault("two_tower_score_mode", "vector_dot")
        rows.append(
            RecallCandidate(
                item_id=result.item_id,
                source="two_tower",
                score=result.score,
                category=str(metadata.get("main_category") or metadata.get("category", "")),
                metadata=metadata,
            )
        )
    return rows


def merge_for_user(
    user_sequence: dict[str, Any],
    popular: list[RecallCandidate],
    itemcf_weak: dict[str, list[RecallCandidate]],
    itemcf_strong: dict[str, list[RecallCandidate]],
    category_top: dict[str, list[RecallCandidate]],
    item_category: dict[str, str],
    config: dict,
    semantic_index: dict[str, dict[str, Any]] | None = None,
    two_tower_index: dict[str, dict[str, Any]] | VectorIndex | None = None,
    item_graph: dict[str, list[RecallCandidate]] | None = None,
    two_tower_seed: dict[str, list[RecallCandidate]] | None = None,
    graph_walk_seed: dict[str, list[RecallCandidate]] | None = None,
    usercf_recall: dict[str, list[RecallCandidate]] | None = None,
    swing_recall: dict[str, list[RecallCandidate]] | None = None,
) -> tuple[list[MergedCandidate], bool]:
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    raw: list[RecallCandidate] = []
    raw.extend(
        _itemcf_candidates_for_user(
            user_sequence,
            itemcf_weak,
            sequence_key="recent_positive_item_sequence",
            source="itemcf_weak",
            config=config,
            window_key="itemcf_recent_positive_window",
            per_seed_key="itemcf_weak_per_seed",
        )
    )
    raw.extend(
        _itemcf_candidates_for_user(
            user_sequence,
            itemcf_strong,
            sequence_key="recent_strong_positive_item_sequence",
            source="itemcf_strong",
            config=config,
            window_key="itemcf_recent_strong_window",
            per_seed_key="itemcf_strong_per_seed",
        )
    )

    raw.extend(_category_candidates_for_user(user_sequence, category_top, item_category, config))
    raw.extend(category_long_tail_candidates_for_user(user_sequence, item_category, popular, config))
    raw.extend(semantic_title_category_expansion_candidates_for_user(user_sequence, semantic_index or {}, config))
    raw.extend(semantic_candidates_for_user(user_sequence, semantic_index or {}, config))
    raw.extend(metadata_neighbor_candidates_for_user(user_sequence, semantic_index or {}, config))
    raw.extend(two_tower_candidates_for_user(user_sequence, two_tower_index or {}, config))
    raw.extend(item_graph_candidates_for_user(user_sequence, item_graph or {}, config))
    raw.extend(two_tower_seed_candidates_for_user(user_sequence, two_tower_seed or {}, config))
    raw.extend(graph_walk_seed_candidates_for_user(user_sequence, graph_walk_seed or {}, config))
    raw.extend(swing_candidates_for_user(user_sequence, swing_recall or {}, config))
    raw.extend(usercf_candidates_for_user(user_sequence, usercf_recall or {}, config))

    fallback_used = not raw
    popular_fallback = _popular_candidates_for_pool(popular, raw, config)
    raw.extend(popular_fallback)
    merged = merge_candidates(raw, seen_items=seen_items)
    if not merged and popular_fallback:
        recovered = merge_candidates(_recovery_popular_candidates(popular_fallback), seen_items=set())
        merged = _limit_candidate_pool(recovered, _recovery_pool_size(config), config)
        fallback_used = True
    has_non_popular_candidate = any(
        source != "popular" for candidate in merged for source in candidate.sources
    )
    fallback_used = fallback_used or not has_non_popular_candidate
    return _limit_candidate_pool(merged, int(config.get("candidate_pool_size", 50)), config), fallback_used


def _recovery_popular_candidates(candidates: list[RecallCandidate]) -> list[RecallCandidate]:
    return [
        RecallCandidate(
            item_id=candidate.item_id,
            source=candidate.source,
            score=candidate.score,
            category=candidate.category,
            metadata=dict(candidate.metadata) | {
                "_internal_fallback_reason": "empty_pool_seen_filtered_popular_recovery",
                "_internal_fallback_source": "popular",
            },
        )
        for candidate in candidates
    ]


def _recovery_pool_size(config: dict) -> int:
    return min(
        int(config.get("candidate_pool_size", 50)),
        int(config.get("popular_fallback_count", 50)),
        int(config.get("top_k", config.get("candidate_pool_size", 50))),
    )


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
    if config.get("candidate_pool_strategy") == "balanced_source_budget":
        return _balanced_source_budget_pool(candidates, pool_size, config)

    minimums = config.get("candidate_source_minimums", {})
    maximums = {str(k): int(v) for k, v in config.get("candidate_source_maximums", {}).items()}
    if not minimums and not maximums:
        return candidates[:pool_size]
    selected: dict[str, MergedCandidate] = {}
    group_counts: Counter[str] = Counter()
    tracked_groups = dict.fromkeys(maximums.keys(), 0)
    for group, minimum in minimums.items():
        sources = _candidate_group_sources(group)
        eligible = [candidate for candidate in candidates if any(source in candidate.sources for source in sources)]
        for candidate in eligible:
            if group_counts[group] >= int(minimum):
                break
            if _would_exceed_maximum(candidate, group_counts, maximums):
                continue
            selected[candidate.item_id] = candidate
            _increment_group_counts(group_counts, candidate, tracked_groups)
    for candidate in candidates:
        if len(selected) >= pool_size:
            break
        if candidate.item_id in selected or _would_exceed_maximum(candidate, group_counts, maximums):
            continue
        selected[candidate.item_id] = candidate
        _increment_group_counts(group_counts, candidate, tracked_groups)
    rows = list(selected.values())[:pool_size]
    rows.sort(key=lambda item: (-sum(item.source_scores.values()), item.item_id))
    return rows


def _balanced_source_budget_pool(candidates: list[MergedCandidate], pool_size: int, config: dict) -> list[MergedCandidate]:
    minimums = {str(k): int(v) for k, v in config.get("candidate_source_minimums", {}).items()}
    maximums = {str(k): int(v) for k, v in config.get("candidate_source_maximums", {}).items()}
    fill_order = [str(item) for item in config.get("candidate_fill_order", [])]
    if not fill_order:
        fill_order = list(dict.fromkeys([*minimums.keys(), *maximums.keys(), "itemcf", "semantic", "category", "popular"]))
    tracked_groups = dict.fromkeys([*minimums.keys(), *maximums.keys()], 0)

    ranked = sorted(candidates, key=lambda item: _candidate_sort_key(item, config))
    selected: dict[str, MergedCandidate] = {}
    group_counts: Counter[str] = Counter()

    for group, minimum in minimums.items():
        for candidate in ranked:
            if len(selected) >= pool_size or group_counts[group] >= minimum:
                break
            if candidate.item_id in selected or not _candidate_in_group(candidate, group):
                continue
            if _would_exceed_maximum(candidate, group_counts, maximums):
                continue
            selected[candidate.item_id] = candidate
            _increment_group_counts(group_counts, candidate, tracked_groups)

    while len(selected) < pool_size:
        added = False
        for group in fill_order:
            for candidate in ranked:
                if len(selected) >= pool_size:
                    break
                if candidate.item_id in selected or not _candidate_in_group(candidate, group):
                    continue
                if _would_exceed_maximum(candidate, group_counts, maximums):
                    continue
                selected[candidate.item_id] = candidate
                _increment_group_counts(group_counts, candidate, tracked_groups)
                added = True
                break
        if not added:
            break

    for candidate in ranked:
        if len(selected) >= pool_size:
            break
        if candidate.item_id in selected or _would_exceed_maximum(candidate, group_counts, maximums):
            continue
        selected[candidate.item_id] = candidate
        _increment_group_counts(group_counts, candidate, tracked_groups)

    rows = list(selected.values())[:pool_size]
    rows.sort(key=lambda item: _candidate_sort_key(item, config))
    return rows


def _candidate_group_sources(group: str) -> set[str]:
    if group == "itemcf":
        return {"itemcf_weak", "itemcf_strong"}
    return {group}


def item_graph_candidates_for_user(
    user_sequence: dict[str, Any],
    item_graph: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("item_graph_enabled") or not item_graph:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("item_graph_recent_positive_window", config.get("item_graph_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("item_graph_recent_strong_window", config.get("item_graph_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("item_graph_per_seed", 20))
    rows: list[RecallCandidate] = []
    for seed_rank, seed in enumerate(seeds):
        for candidate in item_graph.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({"item_graph_seed_item": seed, "item_graph_seed_rank": seed_rank, "item_graph_score": candidate.score})
            rows.append(
                RecallCandidate(
                    item_id=candidate.item_id,
                    source="item_graph",
                    score=candidate.score,
                    category=candidate.category,
                    metadata=metadata,
                )
            )
    limit = int(config.get("item_graph_per_user", len(rows) or per_seed * max(1, len(seeds))))
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def two_tower_seed_candidates_for_user(
    user_sequence: dict[str, Any],
    two_tower_seed: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("two_tower_seed_enabled") or not two_tower_seed:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("two_tower_seed_recent_positive_window", config.get("two_tower_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("two_tower_seed_recent_strong_window", config.get("two_tower_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("two_tower_seed_per_seed", 20))
    limit = int(config.get("two_tower_seed_per_user", per_seed * max(1, len(seeds))))
    recency_decay = float(config.get("two_tower_seed_recency_decay", 1.0))
    score_floor = float(config.get("two_tower_seed_score_floor", 0.0))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in two_tower_seed.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            score = candidate.score * decay
            if score < score_floor:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({
                "two_tower_seed_item": seed,
                "two_tower_seed_rank": seed_rank,
                "two_tower_seed_score": candidate.score,
                "two_tower_seed_decayed_score": round(score, 6),
            })
            row = RecallCandidate(
                item_id=candidate.item_id,
                source="two_tower_seed",
                score=round(score, 6),
                category=candidate.category,
                metadata=metadata,
            )
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def usercf_candidates_for_user(
    user_sequence: dict[str, Any],
    usercf_recall: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("usercf_enabled") or not usercf_recall:
        return []
    user_id = str(user_sequence.get("user_id") or "")
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    limit = int(config.get("usercf_per_user", len(usercf_recall.get(user_id, []))))
    rows = [candidate for candidate in usercf_recall.get(user_id, []) if candidate.item_id not in seen_items]
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def swing_candidates_for_user(
    user_sequence: dict[str, Any],
    swing_recall: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("swing_enabled") or not swing_recall:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("swing_recent_positive_window", config.get("swing_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("swing_recent_strong_window", config.get("swing_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("swing_per_seed", 20))
    limit = int(config.get("swing_per_user", per_seed * max(1, len(seeds))))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        for candidate in swing_recall.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({"swing_seed_item": seed, "swing_seed_rank": seed_rank, "swing_score": candidate.score})
            row = RecallCandidate(
                item_id=candidate.item_id,
                source="swing_recall",
                score=candidate.score,
                category=candidate.category,
                metadata=metadata,
            )
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def graph_walk_seed_candidates_for_user(
    user_sequence: dict[str, Any],
    graph_walk_seed: dict[str, list[RecallCandidate]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("graph_walk_seed_enabled") or not graph_walk_seed:
        return []
    positive_seeds = _recent_unique_seeds(
        user_sequence.get("recent_positive_item_sequence", []),
        int(config.get("graph_walk_seed_recent_positive_window", config.get("graph_walk_seed_window", 10))),
    )
    strong_seeds = _recent_unique_seeds(
        user_sequence.get("recent_strong_positive_item_sequence", []),
        int(config.get("graph_walk_seed_recent_strong_window", config.get("graph_walk_seed_window", 10))),
    )
    seeds = list(dict.fromkeys([*strong_seeds, *positive_seeds]))
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    per_seed = int(config.get("graph_walk_seed_per_seed", 20))
    limit = int(config.get("graph_walk_seed_per_user", per_seed * max(1, len(seeds))))
    recency_decay = float(config.get("graph_walk_seed_recency_decay", 1.0))
    score_floor = float(config.get("graph_walk_seed_score_floor", 0.0))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in graph_walk_seed.get(seed, [])[:per_seed]:
            if candidate.source != "graph_walk_seed":
                raise ValueError(f"invalid graph_walk_seed candidate source: {candidate.source!r}")
            if candidate.item_id in seen_items:
                continue
            score = candidate.score * decay
            if score < score_floor:
                continue
            metadata = dict(candidate.metadata)
            metadata.update({
                "graph_walk_seed_item": seed,
                "graph_walk_seed_rank": seed_rank,
                "graph_walk_seed_score": candidate.score,
                "graph_walk_seed_decayed_score": round(score, 6),
            })
            row = RecallCandidate(
                item_id=candidate.item_id,
                source="graph_walk_seed",
                score=round(score, 6),
                category=candidate.category,
                metadata=metadata,
            )
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]



def _itemcf_candidates_for_user(
    user_sequence: dict[str, Any],
    itemcf: dict[str, list[RecallCandidate]],
    sequence_key: str,
    source: str,
    config: dict,
    window_key: str,
    per_seed_key: str,
) -> list[RecallCandidate]:
    window = int(config.get(window_key, 10))
    per_seed = int(config.get(per_seed_key, config.get("itemcf_per_seed", 20)))
    seeds = _recent_unique_seeds(user_sequence.get(sequence_key, []), window)
    return _extend_itemcf_from_seeds(
        seeds,
        itemcf,
        source=source,
        per_seed=per_seed,
        decay_enabled=bool(config.get("itemcf_seed_decay_enabled", False)),
        decay_base=float(config.get("itemcf_seed_decay_base", 0.85)),
    )


def _recent_unique_seeds(items: list[str], window: int) -> list[str]:
    return list(dict.fromkeys(reversed(items[-window:])))


def _extend_itemcf_from_seeds(
    seeds: list[str],
    itemcf: dict[str, list[RecallCandidate]],
    source: str,
    per_seed: int,
    decay_enabled: bool,
    decay_base: float,
) -> list[RecallCandidate]:
    rows: list[RecallCandidate] = []
    for seed_rank, seed in enumerate(seeds):
        decay = decay_base**seed_rank if decay_enabled else 1.0
        for candidate in itemcf.get(seed, [])[:per_seed]:
            if decay == 1.0 and candidate.source == source:
                rows.append(candidate)
                continue
            metadata = dict(candidate.metadata)
            metadata.setdefault("seed_item", seed)
            rows.append(
                RecallCandidate(
                    item_id=candidate.item_id,
                    source=source,
                    score=candidate.score * decay,
                    category=candidate.category,
                    metadata=metadata,
                )
            )
    return rows


def _category_candidates_for_user(
    user_sequence: dict[str, Any],
    category_top: dict[str, list[RecallCandidate]],
    item_category: dict[str, str],
    config: dict,
) -> list[RecallCandidate]:
    use_new_budget = any(
        key in config
        for key in ("category_recent_positive_window", "category_per_bucket", "category_max_total_per_user")
    )
    if not use_new_budget:
        rows: list[RecallCandidate] = []
        buckets = _category_buckets(user_sequence, item_category)
        category_limit = int(config.get("category_per_user", 20))
        for bucket in buckets:
            rows.extend(category_top.get(bucket, [])[:category_limit])
        return rows

    window = int(config.get("category_recent_positive_window", 10))
    per_bucket = int(config.get("category_per_bucket", config.get("category_per_user", 20)))
    max_total = int(config.get("category_max_total_per_user", per_bucket * max(1, window)))
    rows = []
    for bucket in _category_buckets(user_sequence, item_category, window=window):
        rows.extend(category_top.get(bucket, [])[:per_bucket])
        if len(rows) >= max_total:
            return rows[:max_total]
    return rows[:max_total]


def category_long_tail_candidates_for_user(
    user_sequence: dict[str, Any],
    item_category: dict[str, str],
    popular: list[RecallCandidate],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("category_long_tail_enabled"):
        return []
    popular_rank = {candidate.item_id: rank for rank, candidate in enumerate(popular, start=1)}
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    long_tail_start_rank = int(config.get("category_long_tail_start_rank", len(popular) + 1))
    per_category = int(config.get("category_long_tail_per_category", config.get("category_long_tail_per_user", 20)))
    max_total = int(config.get("category_long_tail_per_user", per_category))
    categories = _seed_categories(user_sequence, item_category, int(config.get("category_long_tail_seed_window", 10)))
    by_item: dict[str, RecallCandidate] = {}
    for category_rank, category in enumerate(categories):
        category_rows = []
        for item_id, item_category_value in item_category.items():
            if item_id in seen_items or item_category_value != category:
                continue
            rank = popular_rank.get(item_id)
            if rank is not None and rank < long_tail_start_rank:
                continue
            score = 1.0 / float(1 + category_rank + (rank or long_tail_start_rank))
            category_rows.append((score, item_id, rank))
        category_rows.sort(key=lambda item: (-item[0], item[1]))
        for source_rank, (score, item_id, rank) in enumerate(category_rows[:per_category], start=1):
            by_item[item_id] = RecallCandidate(
                item_id=item_id,
                source="category_long_tail_recall",
                score=round(score, 6),
                category=category,
                metadata={
                    "reason": "category_long_tail",
                    "seed_category": category,
                    "source_rank": source_rank,
                    "popular_rank": rank,
                    "popularity_bucket": "not_in_popular_topn" if rank is None else "beyond_long_tail_start",
                },
            )
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:max_total]


def metadata_neighbor_candidates_for_user(
    user_sequence: dict[str, Any],
    metadata_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    if not config.get("metadata_neighbor_enabled") or not metadata_index:
        return []
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), int(config.get("metadata_neighbor_seed_window", 10)))
    per_seed = int(config.get("metadata_neighbor_per_seed", 20))
    max_total = int(config.get("metadata_neighbor_per_user", per_seed * max(1, len(seed_items))))
    min_overlap = int(config.get("metadata_neighbor_min_token_overlap", 1))
    category_weight = float(config.get("metadata_neighbor_category_weight", 2.0))
    bucket_index = _metadata_neighbor_bucket_index(metadata_index, config)
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed_item in enumerate(seed_items):
        seed_record = metadata_index.get(seed_item)
        if not seed_record:
            continue
        seed_tokens = _metadata_neighbor_tokens(seed_record, config)
        seed_categories = _semantic_categories(seed_record)
        if not seed_tokens and not seed_categories:
            continue
        seed_rows = []
        candidate_ids = sorted(_metadata_neighbor_bucket_candidates(bucket_index, seed_tokens, seed_categories))[: int(config.get("metadata_neighbor_max_bucket_candidates", 5000))]
        for item_id in candidate_ids:
            if item_id in seen_items or item_id == seed_item:
                continue
            record = metadata_index[item_id]
            candidate_tokens = _metadata_neighbor_tokens(record, config)
            candidate_categories = _semantic_categories(record)
            token_overlap = len(seed_tokens & candidate_tokens)
            category_overlap = len(seed_categories & candidate_categories)
            if token_overlap < min_overlap and category_overlap == 0:
                continue
            score = float(token_overlap) + float(category_overlap) * category_weight
            seed_rows.append((round(score, 6), item_id, token_overlap, category_overlap))
        seed_rows.sort(key=lambda item: (-item[0], item[1]))
        for source_rank, (score, item_id, token_overlap, category_overlap) in enumerate(seed_rows[:per_seed], start=1):
            record = metadata_index[item_id]
            metadata = {k: v for k, v in record.items() if k not in {"semantic_tokens", "two_tower_tokens"}}
            metadata.update({
                "reason": "metadata_neighbor",
                "seed_item_id": seed_item,
                "source_score": score,
                "source_rank": source_rank,
                "metadata_neighbor_seed_rank": seed_rank,
                "metadata_neighbor_token_overlap": token_overlap,
                "metadata_neighbor_category_overlap": category_overlap,
                "metadata_neighbor_index_mode": "bucketed_train_visible_metadata",
            })
            candidate = RecallCandidate(
                item_id=item_id,
                source="metadata_neighbor_recall",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata=metadata,
            )
            current = by_item.get(item_id)
            if current is None or candidate.score > current.score:
                by_item[item_id] = candidate
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:max_total]


def _popular_candidates_for_pool(
    popular: list[RecallCandidate],
    raw_non_popular: list[RecallCandidate],
    config: dict,
) -> list[RecallCandidate]:
    fallback_count = int(config.get("popular_fallback_count", 50))
    if config.get("popular_fill_policy") != "capped_remainder" or not raw_non_popular:
        return popular[:fallback_count]

    pool_size = int(config.get("candidate_pool_size", 50))
    max_in_pool = int(config.get("popular_max_in_pool", fallback_count))
    remainder = max(pool_size - len({candidate.item_id for candidate in raw_non_popular if candidate.item_id}), 0)
    return popular[: min(max_in_pool, remainder)]


def _semantic_seed_aware_candidates_for_user(
    user_sequence: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]],
    config: dict,
) -> list[RecallCandidate]:
    seen_items = set(user_sequence.get("recent_item_sequence", []))
    seed_window = int(config.get("semantic_seed_window", 10))
    per_seed = int(config.get("semantic_per_seed", config.get("semantic_per_user", 20)))
    limit = int(config.get("semantic_per_user", 20))
    min_overlap = int(config.get("semantic_min_overlap", 1))
    category_weight = float(config.get("semantic_category_weight", 2.0))
    token_fields = config.get("semantic_text_fields")
    if token_fields is not None:
        token_fields = [str(field) for field in token_fields]

    seed_items = _recent_unique_seeds(user_sequence.get("recent_positive_item_sequence", []), seed_window)
    context = _semantic_seed_aware_context(semantic_index, token_fields, float(config.get("semantic_max_df_ratio", 1.0)))
    allowed_tokens = context["allowed_tokens"]
    idf = context["idf"]
    item_tokens = context["item_tokens"]
    item_categories = context["item_categories"]
    inverted_index = context["inverted_index"]

    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed_item in enumerate(seed_items):
        seed_record = semantic_index.get(seed_item)
        if not seed_record:
            continue
        seed_tokens = item_tokens.get(seed_item, set()) & allowed_tokens
        seed_categories = item_categories.get(seed_item, set())
        if not seed_tokens and not seed_categories:
            continue
        candidate_overlap_counts: Counter[str] = Counter()
        for token in seed_tokens:
            candidate_overlap_counts.update(inverted_index.get(token, set()))
        seed_scores: list[tuple[float, str]] = []
        for item_id, overlap_count in candidate_overlap_counts.items():
            if overlap_count < min_overlap or item_id in seen_items or item_id == seed_item:
                continue
            overlap_tokens = seed_tokens & item_tokens.get(item_id, set())
            if len(overlap_tokens) < min_overlap:
                continue
            category_overlap = len(seed_categories & item_categories.get(item_id, set()))
            token_score = sum(idf.get(token, 0.0) for token in overlap_tokens) / len(overlap_tokens)
            score = token_score + category_overlap * category_weight
            seed_scores.append((round(score, 6), item_id))
        top_seed_scores = heapq.nsmallest(per_seed, seed_scores, key=lambda item: (-item[0], item[1]))
        for score, item_id in top_seed_scores:
            record = semantic_index[item_id]
            candidate = RecallCandidate(
                item_id=item_id,
                source="semantic",
                score=score,
                category=str(record.get("main_category") or record.get("category", "")),
                metadata={k: v for k, v in record.items() if k != "semantic_tokens"} | {"semantic_seed_item": seed_item, "semantic_seed_rank": seed_rank},
            )
            current = by_item.get(candidate.item_id)
            if current is None or candidate.score > current.score:
                by_item[candidate.item_id] = candidate

    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]


def _looks_like_vector_artifact(path: str | Path) -> bool:
    artifact_path = Path(path)
    if artifact_path.suffix == ".json":
        return True
    return artifact_path.name.endswith("recall_index.jsonl")


def _semantic_token_df(
    semantic_index: dict[str, dict[str, Any]],
    token_fields: list[str] | None,
) -> Counter[str]:
    token_df: Counter[str] = Counter()
    for record in semantic_index.values():
        token_df.update(_record_semantic_tokens(record, token_fields))
    return token_df


def _semantic_title_category_context(semantic_index: dict[str, dict[str, Any]], token_fields: list[str]) -> dict[str, Any]:
    normalized_fields = tuple(token_fields)
    cache_key = (id(semantic_index), normalized_fields, len(semantic_index))
    context = _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE.get(cache_key)
    if context:
        return context
    item_tokens = {item_id: _semantic_tokens(record, token_fields) for item_id, record in semantic_index.items()}
    item_categories = {item_id: _semantic_categories(record) for item_id, record in semantic_index.items()}
    inverted_index: dict[str, set[str]] = defaultdict(set)
    for item_id, tokens in item_tokens.items():
        for token in tokens:
            inverted_index[token].add(item_id)
    context = {
        "item_tokens": item_tokens,
        "item_categories": item_categories,
        "inverted_index": inverted_index,
    }
    if len(_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE) >= _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE_LIMIT:
        _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE.pop(next(iter(_SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE)))
    _SEMANTIC_TITLE_CATEGORY_CONTEXT_CACHE[cache_key] = context
    return context


def _semantic_seed_aware_context(
    semantic_index: dict[str, dict[str, Any]],
    token_fields: list[str] | None,
    max_df_ratio: float,
) -> dict[str, Any]:
    normalized_fields = tuple(token_fields or ())
    cache_key = (id(semantic_index), normalized_fields, max_df_ratio, len(semantic_index))
    context = _SEMANTIC_SEED_CONTEXT_CACHE.get(cache_key)
    if context:
        return context

    item_tokens = {
        item_id: _record_semantic_tokens(record, token_fields)
        for item_id, record in semantic_index.items()
    }
    item_categories = {
        item_id: _semantic_categories(record)
        for item_id, record in semantic_index.items()
    }
    token_df: Counter[str] = Counter()
    for tokens in item_tokens.values():
        token_df.update(tokens)
    max_df = max(1, int(len(semantic_index) * max_df_ratio))
    allowed_tokens = {token for token, df in token_df.items() if df <= max_df}
    idf = {
        token: math.log((1.0 + len(item_tokens)) / (1.0 + df)) + 1.0
        for token, df in token_df.items()
        if token in allowed_tokens
    }
    inverted_index: dict[str, set[str]] = defaultdict(set)
    for item_id, tokens in item_tokens.items():
        for token in tokens & allowed_tokens:
            inverted_index[token].add(item_id)
    context = {
        "token_fields": normalized_fields,
        "max_df_ratio": max_df_ratio,
        "allowed_tokens": allowed_tokens,
        "idf": idf,
        "item_tokens": item_tokens,
        "item_categories": item_categories,
        "inverted_index": inverted_index,
    }
    if len(_SEMANTIC_SEED_CONTEXT_CACHE) >= _SEMANTIC_SEED_CONTEXT_CACHE_LIMIT:
        _SEMANTIC_SEED_CONTEXT_CACHE.pop(next(iter(_SEMANTIC_SEED_CONTEXT_CACHE)))
    _SEMANTIC_SEED_CONTEXT_CACHE[cache_key] = context
    return context


def _two_tower_token_df(
    two_tower_index: dict[str, dict[str, Any]],
    token_fields: list[str] | None,
) -> Counter[str]:
    token_df: Counter[str] = Counter()
    for record in two_tower_index.values():
        token_df.update(_record_two_tower_tokens(record, token_fields))
    return token_df


def _record_semantic_tokens(record: dict[str, Any], token_fields: list[str] | None) -> set[str]:
    if token_fields is None:
        return set(record.get("semantic_tokens", set()))
    return _semantic_tokens(record, token_fields)


def _record_two_tower_tokens(record: dict[str, Any], token_fields: list[str] | None) -> set[str]:
    if token_fields is None:
        return set(record.get("two_tower_tokens", set()))
    return _semantic_tokens(record, token_fields)


def _two_tower_vector(tokens: set[str], idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(tokens)
    return {token: float(count) * idf.get(token, 0.0) for token, count in counts.items() if idf.get(token, 0.0) > 0.0}


def _vector_norm(vector: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vector.values()))


def _cosine_score(
    left: dict[str, float],
    left_norm: float,
    right: dict[str, float],
    right_norm: float,
) -> float:
    if not left_norm or not right_norm:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    dot = sum(value * right.get(token, 0.0) for token, value in left.items())
    return dot / (left_norm * right_norm)


def _candidate_sort_key(candidate: MergedCandidate, config: dict) -> tuple[float, str]:
    multi_source_boost = float(config.get("candidate_multi_source_boost", 0.0))
    score = sum(candidate.source_scores.values()) + max(len(candidate.sources) - 1, 0) * multi_source_boost
    return (-score, candidate.item_id)


def _candidate_in_group(candidate: MergedCandidate, group: str) -> bool:
    sources = _candidate_group_sources(group)
    return any(source in candidate.sources for source in sources)


def _would_exceed_maximum(
    candidate: MergedCandidate,
    group_counts: Counter[str],
    maximums: dict[str, int],
) -> bool:
    for group, maximum in maximums.items():
        if maximum <= 0 and _candidate_in_group(candidate, group):
            return True
        if maximum > 0 and _candidate_in_group(candidate, group) and group_counts[group] >= maximum:
            return True
    return False


def _increment_group_counts(
    group_counts: Counter[str],
    candidate: MergedCandidate,
    tracked_groups: dict[str, int],
) -> None:
    for group in tracked_groups:
        if _candidate_in_group(candidate, group):
            group_counts[group] += 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



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


def _category_buckets(user_sequence: dict[str, Any], item_category: dict[str, str], window: int | None = None) -> list[str]:
    return [f"main::{category}" for category in _seed_categories(user_sequence, item_category, window)]


def _seed_categories(user_sequence: dict[str, Any], item_category: dict[str, str], window: int | None = None) -> list[str]:
    categories: list[str] = []
    sequence = user_sequence.get("recent_positive_item_sequence", [])
    if window is not None:
        sequence = sequence[-window:]
    for item_id in reversed(sequence):
        category = item_category.get(item_id, "")
        if category and category not in categories:
            categories.append(category)
    return categories


def _metadata_neighbor_tokens(row: dict[str, Any], config: dict) -> set[str]:
    fields = config.get("metadata_neighbor_fields")
    if fields is not None:
        fields = [str(field) for field in fields]
    return _semantic_tokens(row, fields)


def _metadata_neighbor_bucket_index(metadata_index: dict[str, dict[str, Any]], config: dict) -> dict[str, dict[str, set[str]]]:
    fields = config.get("metadata_neighbor_fields")
    if fields is not None:
        fields = tuple(str(field) for field in fields)
    else:
        fields = ()
    cache_key = (id(metadata_index), fields)
    cached = _METADATA_NEIGHBOR_INDEX_CACHE.get(cache_key)
    if cached is not None:
        return cached
    token_buckets: dict[str, set[str]] = defaultdict(set)
    category_buckets: dict[str, set[str]] = defaultdict(set)
    for item_id, record in metadata_index.items():
        for token in _metadata_neighbor_tokens(record, config):
            token_buckets[token].add(item_id)
        for category in _semantic_categories(record):
            category_buckets[category].add(item_id)
    bucket_index = {"tokens": token_buckets, "categories": category_buckets}
    if len(_METADATA_NEIGHBOR_INDEX_CACHE) >= _METADATA_NEIGHBOR_INDEX_CACHE_LIMIT:
        _METADATA_NEIGHBOR_INDEX_CACHE.pop(next(iter(_METADATA_NEIGHBOR_INDEX_CACHE)))
    _METADATA_NEIGHBOR_INDEX_CACHE[cache_key] = bucket_index
    return bucket_index


def _metadata_neighbor_bucket_candidates(bucket_index: dict[str, dict[str, set[str]]], tokens: set[str], categories: set[str]) -> set[str]:
    candidates: set[str] = set()
    for token in tokens:
        candidates.update(bucket_index["tokens"].get(token, set()))
    for category in categories:
        candidates.update(bucket_index["categories"].get(category, set()))
    return candidates


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
