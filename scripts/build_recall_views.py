from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from rs_core.recsys.candidate_merge import unique_recent_items

DEFAULT_INPUT_DIR = "./data/processed/amazon_2023_recall_clean"
DEFAULT_OUTPUT_DIR = "./data/processed/amazon_2023_recall_views"
DEFAULT_RECENT_WINDOW_RATIO = 0.2
DEFAULT_MAX_ITEMS_PER_USER_FOR_ITEMCF = 50
DEFAULT_CATEGORY_TOP_K = 100
DEFAULT_ITEM_GRAPH_WINDOW = 5
DEFAULT_ITEM_GRAPH_TOP_K = 100
DEFAULT_ITEM_GRAPH_MIN_SCORE = 0.0
DEFAULT_ITEM_GRAPH_STRONG_MULTIPLIER = 1.5
DEFAULT_LIGHTWEIGHT_MAX_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_LIGHTWEIGHT_MIN_FREE_BYTES = 5 * 1024 * 1024 * 1024
DEFAULT_SEMANTIC_INVERTED_TOP_K = 2000
SEMANTIC_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build minimal recall views from canonical recall-clean tables."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Directory containing canonical recall-clean outputs.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory used to store recall views.",
    )
    parser.add_argument(
        "--recent-window-ratio",
        type=float,
        default=DEFAULT_RECENT_WINDOW_RATIO,
        help="Fraction of the train time span treated as recent for popularity views.",
    )
    parser.add_argument(
        "--max-items-per-user-for-itemcf",
        type=int,
        default=DEFAULT_MAX_ITEMS_PER_USER_FOR_ITEMCF,
        help="Maximum recent unique items per user used for ItemCF edges.",
    )
    parser.add_argument(
        "--category-top-k",
        type=int,
        default=DEFAULT_CATEGORY_TOP_K,
        help="Top-K items retained per category bucket in category recall outputs.",
    )
    parser.add_argument(
        "--item-graph-window",
        type=int,
        default=DEFAULT_ITEM_GRAPH_WINDOW,
        help="Maximum forward sequence distance used for directed item graph edges.",
    )
    parser.add_argument(
        "--item-graph-top-k",
        type=int,
        default=DEFAULT_ITEM_GRAPH_TOP_K,
        help="Maximum outgoing item graph neighbors retained per source item.",
    )
    parser.add_argument(
        "--item-graph-min-score",
        type=float,
        default=DEFAULT_ITEM_GRAPH_MIN_SCORE,
        help="Minimum item graph edge score retained in the output.",
    )
    parser.add_argument(
        "--item-graph-strong-multiplier",
        type=float,
        default=DEFAULT_ITEM_GRAPH_STRONG_MULTIPLIER,
        help="Score multiplier applied when destination item is in the strong-positive sequence.",
    )
    parser.add_argument(
        "--lightweight-full-safe",
        action="store_true",
        help="Build only full-safe lightweight recall views and skip ItemCF/item_graph outputs.",
    )
    parser.add_argument(
        "--lightweight-max-output-bytes",
        type=int,
        default=DEFAULT_LIGHTWEIGHT_MAX_OUTPUT_BYTES,
        help="Hard cap for total lightweight output bytes before promotion.",
    )
    parser.add_argument(
        "--lightweight-min-free-bytes",
        type=int,
        default=DEFAULT_LIGHTWEIGHT_MIN_FREE_BYTES,
        help="Minimum free bytes required on the output filesystem before building lightweight views.",
    )
    parser.add_argument(
        "--semantic-inverted-top-k",
        type=int,
        default=DEFAULT_SEMANTIC_INVERTED_TOP_K,
        help="Maximum item postings retained per semantic inverted-index token in lightweight mode.",
    )
    return parser.parse_args()


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            payload = line.strip()
            if payload:
                yield json.loads(payload)


def compact_json(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl_file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {
        "size_bytes": path.stat().st_size,
        "row_count": rows,
        "sha256": digest.hexdigest(),
    }


def directory_size_bytes(path: Path) -> int:
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            total += file_path.stat().st_size
    return total


def ensure_lightweight_output_target(output_dir: Path) -> Path:
    tmp_output_dir = output_dir.with_name(f"{output_dir.name}_tmp")
    if output_dir.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing lightweight output directory: {output_dir}"
        )
    if tmp_output_dir.exists():
        raise FileExistsError(
            f"Refusing to reuse existing lightweight temp output directory: {tmp_output_dir}"
        )
    return tmp_output_dir


def semantic_tokens(record: dict[str, Any]) -> set[str]:
    text_parts: list[str] = []
    for field_name in ("title_clean", "main_category", "description_text", "features_text", "item_text"):
        value = record.get(field_name)
        if value:
            text_parts.append(str(value))
    for value in record.get("categories_flat", []):
        if value:
            text_parts.append(str(value))
    return {token for token in SEMANTIC_TOKEN_PATTERN.findall(" ".join(text_parts).lower()) if len(token) >= 2}


def build_semantic_inverted_index(items_path: Path, output_dir: Path, top_k: int) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("semantic_inverted_top_k must be >= 1")
    token_items: defaultdict[str, list[tuple[float, str]]] = defaultdict(list)
    item_rows = 0
    for record in iter_jsonl(items_path):
        item_rows += 1
        item_id = record["parent_asin"]
        score = float(record.get("rating_number") or 0.0)
        for token in semantic_tokens(record):
            token_items[token].append((score, item_id))

    output_path = output_dir / "semantic_inverted_index.jsonl"
    rows_written = 0
    postings_written = 0
    with output_path.open("w", encoding="utf-8") as sink:
        for token, scored_items in sorted(token_items.items()):
            seen: set[str] = set()
            postings: list[str] = []
            for _score, item_id in sorted(scored_items, key=lambda item: (-item[0], item[1])):
                if item_id in seen:
                    continue
                seen.add(item_id)
                postings.append(item_id)
                if len(postings) >= top_k:
                    break
            sink.write(compact_json({"token": token, "parent_asins": postings}) + "\n")
            rows_written += 1
            postings_written += len(postings)

    return {
        "output_path": str(output_path),
        "rows_written": rows_written,
        "postings_written": postings_written,
        "items_indexed": item_rows,
        "top_k": top_k,
    }


def build_source_signature(input_dir: Path, required_paths: list[Path]) -> dict[str, Any]:
    manifest_path = input_dir / "manifest.json"
    stats_path = input_dir / "stats.json"
    manifest_hash = file_sha256(manifest_path) if manifest_path.exists() else None
    stats_hash = file_sha256(stats_path) if stats_path.exists() else None
    canonical_file_signatures = {
        path.name: jsonl_file_signature(path)
        for path in required_paths
    }
    combined_parts = [str(input_dir), str(manifest_hash), str(stats_hash)]
    combined_parts.extend(
        f"{name}:{payload['size_bytes']}:{payload['row_count']}"
        for name, payload in sorted(canonical_file_signatures.items())
    )
    return {
        "input_dir": str(input_dir),
        "manifest_path": str(manifest_path) if manifest_path.exists() else None,
        "stats_path": str(stats_path) if stats_path.exists() else None,
        "manifest_sha256": manifest_hash,
        "stats_sha256": stats_hash,
        "canonical_file_signatures": canonical_file_signatures,
        "combined_signature": hashlib.sha256("|".join(combined_parts).encode("utf-8")).hexdigest(),
    }


def ensure_args(
    recent_window_ratio: float,
    max_items_per_user: int,
    category_top_k: int,
    item_graph_window: int,
    item_graph_top_k: int,
    item_graph_min_score: float,
    item_graph_strong_multiplier: float,
) -> None:
    if not 0 <= recent_window_ratio <= 1:
        raise ValueError("recent_window_ratio must be between 0 and 1")
    if max_items_per_user < 1 or max_items_per_user > 500:
        raise ValueError("max_items_per_user_for_itemcf must be between 1 and 500")
    if category_top_k < 1:
        raise ValueError("category_top_k must be >= 1")
    if item_graph_window < 1 or item_graph_window > 100:
        raise ValueError("item_graph_window must be between 1 and 100")
    if item_graph_top_k < 1:
        raise ValueError("item_graph_top_k must be >= 1")
    if item_graph_min_score < 0:
        raise ValueError("item_graph_min_score must be >= 0")
    if item_graph_strong_multiplier < 1:
        raise ValueError("item_graph_strong_multiplier must be >= 1")


def quality_bucket(average_rating: float | None, rating_number: int | None) -> str:
    avg = float(average_rating or 0.0)
    cnt = int(rating_number or 0)
    if avg >= 4.3 and cnt >= 100:
        return "high"
    if avg >= 4.0 and cnt >= 20:
        return "medium"
    return "low"


def build_popularity_view(
    train_path: Path,
    output_dir: Path,
    recent_window_ratio: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    pop_counts: Counter[str] = Counter()
    verified_counts: Counter[str] = Counter()
    decayed_counts: defaultdict[str, float] = defaultdict(float)
    category_by_item: dict[str, str] = {}
    train_min_ts: int | None = None
    train_max_ts: int | None = None
    positive_rows = 0

    for record in iter_jsonl(train_path):
        if not record.get("label_binary"):
            continue
        positive_rows += 1
        timestamp = int(record["timestamp"])
        item_id = record["parent_asin"]
        pop_counts[item_id] += 1
        if record.get("verified_purchase"):
            verified_counts[item_id] += 1
        category_by_item[item_id] = record.get("category", "")
        train_min_ts = timestamp if train_min_ts is None else min(train_min_ts, timestamp)
        train_max_ts = timestamp if train_max_ts is None else max(train_max_ts, timestamp)

    recent_threshold = train_min_ts or 0
    span = 1
    if train_min_ts is not None and train_max_ts is not None:
        span = max(1, train_max_ts - train_min_ts)
        recent_threshold = int(train_max_ts - span * recent_window_ratio)

    recent_counts: Counter[str] = Counter()
    for record in iter_jsonl(train_path):
        if not record.get("label_binary"):
            continue
        timestamp = int(record["timestamp"])
        item_id = record["parent_asin"]
        normalized_age = 0.5 if train_min_ts is None else 0.5 + ((timestamp - train_min_ts) / span)
        decayed_counts[item_id] += normalized_age
        if timestamp >= recent_threshold:
            recent_counts[item_id] += 1

    popularity_view: dict[str, dict[str, Any]] = {}
    output_path = output_dir / "popular_recall.jsonl"
    rows_written = 0
    with output_path.open("w", encoding="utf-8") as sink:
        for item_id, pop_score in sorted(pop_counts.items(), key=lambda item: (-item[1], item[0])):
            record = {
                "parent_asin": item_id,
                "category": category_by_item.get(item_id, ""),
                "pop_score": pop_score,
                "verified_pop_score": verified_counts[item_id],
                "recent_pop_score": recent_counts[item_id],
                "time_decay_pop_score": round(decayed_counts[item_id], 6),
            }
            popularity_view[item_id] = record
            sink.write(compact_json(record) + "\n")
            rows_written += 1

    return popularity_view, {
        "output_path": str(output_path),
        "rows_written": rows_written,
        "positive_rows_used": positive_rows,
        "recent_threshold": recent_threshold,
    }


def build_itemcf_edges(
    user_sequences_path: Path,
    output_path: Path,
    label_field: str,
    max_items_per_user: int,
) -> dict[str, Any]:
    item_user_count: Counter[str] = Counter()
    pair_count: Counter[tuple[str, str]] = Counter()
    users_used = 0

    for record in iter_jsonl(user_sequences_path):
        items = record.get(label_field, [])
        unique_items = unique_recent_items(items, max_items_per_user)
        if unique_items:
            item_user_count.update(unique_items)
        if len(unique_items) < 2:
            continue
        users_used += 1
        for pair in combinations(sorted(unique_items), 2):
            pair_count[pair] += 1

    rows_written = 0
    with output_path.open("w", encoding="utf-8") as sink:
        for (item_a, item_b), cooc_cnt in sorted(
            pair_count.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        ):
            denominator = math.sqrt(item_user_count[item_a] * item_user_count[item_b])
            score = 0.0 if denominator == 0 else round(cooc_cnt / denominator, 6)
            for src_item, dst_item in ((item_a, item_b), (item_b, item_a)):
                sink.write(
                    compact_json(
                        {
                            "src_item": src_item,
                            "dst_item": dst_item,
                            "cooc_cnt": cooc_cnt,
                            "src_user_cnt": item_user_count[src_item],
                            "dst_user_cnt": item_user_count[dst_item],
                            "score": score,
                            "label_variant": label_field,
                        }
                    )
                    + "\n"
                )
                rows_written += 1

    return {
        "output_path": str(output_path),
        "rows_written": rows_written,
        "users_used": users_used,
        "unique_item_count": len(item_user_count),
        "unique_pair_count": len(pair_count),
    }


def build_itemcf_views(
    train_user_sequences_path: Path,
    output_dir: Path,
    max_items_per_user: int,
) -> dict[str, Any]:
    weak_path = output_dir / "itemcf_recall_weak.jsonl"
    strong_path = output_dir / "itemcf_recall_strong.jsonl"
    weak_stats = build_itemcf_edges(
        train_user_sequences_path,
        weak_path,
        "recent_positive_item_sequence",
        max_items_per_user,
    )
    strong_stats = build_itemcf_edges(
        train_user_sequences_path,
        strong_path,
        "recent_strong_positive_item_sequence",
        max_items_per_user,
    )
    return {
        "weak": weak_stats,
        "strong": strong_stats,
    }


def build_item_graph_view(
    user_sequences_path: Path,
    output_dir: Path,
    window: int,
    top_k: int,
    min_score: float,
    strong_multiplier: float,
) -> dict[str, Any]:
    edge_scores: defaultdict[tuple[str, str], float] = defaultdict(float)
    edge_support: Counter[tuple[str, str]] = Counter()
    strong_support: Counter[tuple[str, str]] = Counter()
    item_occurrence_count: Counter[str] = Counter()
    users_used = 0

    for record in iter_jsonl(user_sequences_path):
        sequence = record.get("recent_positive_item_sequence", [])
        if not sequence:
            continue
        strong_items = set(record.get("recent_strong_positive_item_sequence", []))
        item_occurrence_count.update(sequence)
        users_used += 1
        for src_index, src_item in enumerate(sequence):
            max_dst_index = min(len(sequence), src_index + window + 1)
            for dst_index in range(src_index + 1, max_dst_index):
                dst_item = sequence[dst_index]
                if src_item == dst_item:
                    continue
                distance = dst_index - src_index
                recency_weight = (dst_index + 1) / len(sequence)
                distance_weight = 1 / distance
                strong_weight = strong_multiplier if dst_item in strong_items else 1.0
                edge = (src_item, dst_item)
                edge_scores[edge] += recency_weight * distance_weight * strong_weight
                edge_support[edge] += 1
                if dst_item in strong_items:
                    strong_support[edge] += 1

    outgoing_edges: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for (src_item, dst_item), raw_score in edge_scores.items():
        score = round(raw_score, 6)
        if score < min_score:
            continue
        outgoing_edges[src_item].append(
            {
                "src_item": src_item,
                "dst_item": dst_item,
                "score": score,
                "cooc_cnt": edge_support[(src_item, dst_item)],
                "strong_dst_cnt": strong_support[(src_item, dst_item)],
                "src_occurrence_cnt": item_occurrence_count[src_item],
                "dst_occurrence_cnt": item_occurrence_count[dst_item],
                "window": window,
                "strong_multiplier": strong_multiplier,
            }
        )

    output_path = output_dir / "item_graph_recall.jsonl"
    rows_written = 0
    with output_path.open("w", encoding="utf-8") as sink:
        for src_item in sorted(outgoing_edges):
            neighbors = sorted(
                outgoing_edges[src_item],
                key=lambda item: (-item["score"], -item["cooc_cnt"], item["dst_item"]),
            )[:top_k]
            for neighbor in neighbors:
                sink.write(compact_json(neighbor) + "\n")
                rows_written += 1

    return {
        "output_path": str(output_path),
        "rows_written": rows_written,
        "users_used": users_used,
        "unique_src_item_count": len(outgoing_edges),
        "unique_edge_count": sum(len(edges) for edges in outgoing_edges.values()),
        "window": window,
        "top_k": top_k,
        "min_score": min_score,
        "strong_multiplier": strong_multiplier,
    }


def build_category_and_semantic_views(
    items_path: Path,
    output_dir: Path,
    popularity_view: dict[str, dict[str, Any]],
    category_top_k: int,
) -> dict[str, Any]:
    category_items_path = output_dir / "category_recall_items.jsonl"
    category_top_path = output_dir / "category_top_items.jsonl"
    semantic_path = output_dir / "semantic_recall_inputs.jsonl"

    category_top_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    category_rows = 0
    semantic_rows = 0

    def update_bucket(bucket_name: str, item_payload: dict[str, Any]) -> None:
        bucket = category_top_candidates[bucket_name]
        bucket.append(item_payload)
        bucket.sort(
            key=lambda item: (-item["score"], -item["recent_pop_score"], item["parent_asin"])
        )
        if len(bucket) > category_top_k:
            del bucket[category_top_k:]

    with category_items_path.open("w", encoding="utf-8") as category_sink, semantic_path.open(
        "w", encoding="utf-8"
    ) as semantic_sink:
        for record in iter_jsonl(items_path):
            item_id = record["parent_asin"]
            pop = popularity_view.get(
                item_id,
                {
                    "pop_score": 0,
                    "verified_pop_score": 0,
                    "recent_pop_score": 0,
                    "time_decay_pop_score": 0.0,
                },
            )
            category_record = {
                "parent_asin": item_id,
                "category": record.get("category", ""),
                "source_categories": record.get("source_categories", []),
                "main_category": record.get("main_category", ""),
                "categories_flat": record.get("categories_flat", []),
                "store": record.get("store", ""),
                "average_rating": record.get("average_rating"),
                "rating_number": record.get("rating_number"),
                "quality_bucket": quality_bucket(
                    record.get("average_rating"), record.get("rating_number")
                ),
                "pop_score": pop["pop_score"],
                "recent_pop_score": pop["recent_pop_score"],
                "verified_pop_score": pop["verified_pop_score"],
                "time_decay_pop_score": pop["time_decay_pop_score"],
            }
            category_sink.write(compact_json(category_record) + "\n")
            category_rows += 1

            semantic_record = {
                "parent_asin": item_id,
                "category": record.get("category", ""),
                "source_categories": record.get("source_categories", []),
                "title_clean": record.get("title_clean", ""),
                "main_category": record.get("main_category", ""),
                "categories_flat": record.get("categories_flat", []),
                "description_text": record.get("description_text", ""),
                "features_text": record.get("features_text", ""),
                "item_text": record.get("item_text", ""),
            }
            semantic_sink.write(compact_json(semantic_record) + "\n")
            semantic_rows += 1

            candidate = {
                "parent_asin": item_id,
                "score": pop["pop_score"],
                "recent_pop_score": pop["recent_pop_score"],
            }
            main_category = record.get("main_category", "") or "unknown"
            update_bucket(f"main::{main_category}", candidate)
            for category_name in record.get("categories_flat", []):
                update_bucket(f"path::{category_name}", candidate)

    top_bucket_rows = 0
    with category_top_path.open("w", encoding="utf-8") as sink:
        for bucket_name, items in sorted(category_top_candidates.items()):
            sink.write(compact_json({"bucket": bucket_name, "top_items": items}) + "\n")
            top_bucket_rows += 1

    return {
        "category_items_path": str(category_items_path),
        "category_top_path": str(category_top_path),
        "semantic_path": str(semantic_path),
        "category_rows_written": category_rows,
        "semantic_rows_written": semantic_rows,
        "category_bucket_rows": top_bucket_rows,
    }


def replace_path_prefix(payload: Any, old_prefix: str, new_prefix: str) -> Any:
    if isinstance(payload, dict):
        return {key: replace_path_prefix(value, old_prefix, new_prefix) for key, value in payload.items()}
    if isinstance(payload, list):
        return [replace_path_prefix(value, old_prefix, new_prefix) for value in payload]
    if isinstance(payload, str):
        return payload.replace(old_prefix, new_prefix)
    return payload


def build_lightweight_full_safe_views(
    input_dir: Path,
    output_dir: Path,
    recent_window_ratio: float,
    category_top_k: int,
    min_free_bytes: int,
    max_output_bytes: int,
    semantic_inverted_top_k: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if min_free_bytes < 0:
        raise ValueError("lightweight_min_free_bytes must be >= 0")
    if max_output_bytes < 1:
        raise ValueError("lightweight_max_output_bytes must be >= 1")

    train_path = input_dir / "canonical_interactions.train.jsonl"
    items_path = input_dir / "canonical_items.jsonl"
    if not train_path.exists():
        raise FileNotFoundError(f"Missing train interactions file: {train_path}")
    if not items_path.exists():
        raise FileNotFoundError(f"Missing canonical items file: {items_path}")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(output_dir.parent).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(
            f"Insufficient free space for lightweight recall views: {free_bytes} < {min_free_bytes}"
        )

    tmp_output_dir = ensure_lightweight_output_target(output_dir)
    tmp_output_dir.mkdir(parents=True)
    try:
        source_signature = build_source_signature(input_dir, [train_path, items_path])
        popularity_view, popularity_stats = build_popularity_view(
            train_path,
            tmp_output_dir,
            recent_window_ratio,
        )
        category_stats = build_category_and_semantic_views(
            items_path,
            tmp_output_dir,
            popularity_view,
            category_top_k,
        )
        semantic_inverted_stats = build_semantic_inverted_index(
            items_path,
            tmp_output_dir,
            semantic_inverted_top_k,
        )
        artifact_size_bytes = directory_size_bytes(tmp_output_dir)

        manifest_payload = {
            "schema_version": "1.2",
            "mode": "lightweight_full_safe",
            "generated_at": datetime.now(UTC).isoformat(),
            "source_clean_dir": str(input_dir),
            "source_signature": source_signature,
            "outputs": {
                "popular_recall": popularity_stats["output_path"],
                "category_recall_items": category_stats["category_items_path"],
                "category_top_items": category_stats["category_top_path"],
                "semantic_recall_inputs": category_stats["semantic_path"],
                "semantic_inverted_index": semantic_inverted_stats["output_path"],
            },
            "skipped_outputs": ["itemcf_recall_weak", "itemcf_recall_strong", "item_graph_recall"],
        }
        stats_payload = {
            "schema_version": "1.2",
            "mode": "lightweight_full_safe",
            "generated_at": datetime.now(UTC).isoformat(),
            "config": {
                "recent_window_ratio": recent_window_ratio,
                "category_top_k": category_top_k,
                "lightweight_min_free_bytes": min_free_bytes,
                "lightweight_max_output_bytes": max_output_bytes,
                "semantic_inverted_top_k": semantic_inverted_top_k,
            },
            "safety": {
                "free_bytes_before_build": free_bytes,
                "artifact_size_bytes_before_manifest": artifact_size_bytes,
                "atomic_tmp_dir": str(tmp_output_dir),
                "promoted_output_dir": str(output_dir),
            },
            "source_signature": source_signature,
            "popular_recall": popularity_stats,
            "category_recall": category_stats,
            "semantic_inverted_index": semantic_inverted_stats,
            "skipped_outputs": ["itemcf_recall_weak", "itemcf_recall_strong", "item_graph_recall"],
        }
        manifest_payload = replace_path_prefix(manifest_payload, str(tmp_output_dir), str(output_dir))
        stats_payload = replace_path_prefix(stats_payload, str(tmp_output_dir), str(output_dir))
        stats_payload["safety"]["atomic_tmp_dir"] = str(tmp_output_dir)
        manifest_path = write_manifest(tmp_output_dir, manifest_payload)
        stats_path = write_stats(tmp_output_dir, stats_payload)
        stats_payload["safety"]["final_output_size_bytes"] = directory_size_bytes(tmp_output_dir)
        write_stats(tmp_output_dir, stats_payload)
        final_output_size_bytes = directory_size_bytes(tmp_output_dir)
        if final_output_size_bytes > max_output_bytes:
            raise RuntimeError(
                f"Lightweight recall view output exceeds hard cap: {final_output_size_bytes} > {max_output_bytes}"
            )
        stats_payload["safety"]["final_output_size_bytes"] = final_output_size_bytes
        write_stats(tmp_output_dir, stats_payload)
        tmp_output_dir.rename(output_dir)
        manifest_payload["manifest_path"] = str(output_dir / manifest_path.name)
        stats_payload["stats_path"] = str(output_dir / stats_path.name)
        return manifest_payload, stats_payload
    except Exception:
        shutil.rmtree(tmp_output_dir, ignore_errors=True)
        raise


def write_manifest(output_dir: Path, payload: dict[str, Any]) -> Path:
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def write_stats(output_dir: Path, payload: dict[str, Any]) -> Path:
    stats_path = output_dir / "stats.json"
    stats_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats_path


def main() -> None:
    args = parse_args()
    ensure_args(
        args.recent_window_ratio,
        args.max_items_per_user_for_itemcf,
        args.category_top_k,
        args.item_graph_window,
        args.item_graph_top_k,
        args.item_graph_min_score,
        args.item_graph_strong_multiplier,
    )

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if args.lightweight_full_safe:
        manifest_payload, stats_payload = build_lightweight_full_safe_views(
            input_dir=input_dir,
            output_dir=output_dir,
            recent_window_ratio=args.recent_window_ratio,
            category_top_k=args.category_top_k,
            min_free_bytes=args.lightweight_min_free_bytes,
            max_output_bytes=args.lightweight_max_output_bytes,
            semantic_inverted_top_k=args.semantic_inverted_top_k,
        )
        print(f"Lightweight full-safe recall views written to: {output_dir}")
        print(f"Manifest written to: {manifest_payload['manifest_path']}")
        print(f"Stats written to: {stats_payload['stats_path']}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    train_path = input_dir / "canonical_interactions.train.jsonl"
    items_path = input_dir / "canonical_items.jsonl"
    train_user_sequences_path = input_dir / "user_sequences.train.jsonl"
    if not train_path.exists():
        raise FileNotFoundError(f"Missing train interactions file: {train_path}")
    if not items_path.exists():
        raise FileNotFoundError(f"Missing canonical items file: {items_path}")
    if not train_user_sequences_path.exists():
        raise FileNotFoundError(f"Missing train user sequences file: {train_user_sequences_path}")

    popularity_view, popularity_stats = build_popularity_view(
        train_path,
        output_dir,
        args.recent_window_ratio,
    )
    itemcf_stats = build_itemcf_views(
        train_user_sequences_path,
        output_dir,
        args.max_items_per_user_for_itemcf,
    )
    item_graph_stats = build_item_graph_view(
        train_user_sequences_path,
        output_dir,
        args.item_graph_window,
        args.item_graph_top_k,
        args.item_graph_min_score,
        args.item_graph_strong_multiplier,
    )
    category_stats = build_category_and_semantic_views(
        items_path,
        output_dir,
        popularity_view,
        args.category_top_k,
    )

    manifest_payload = {
        "schema_version": "1.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_clean_dir": str(input_dir),
        "outputs": {
            "popular_recall": popularity_stats["output_path"],
            "itemcf_recall_weak": itemcf_stats["weak"]["output_path"],
            "itemcf_recall_strong": itemcf_stats["strong"]["output_path"],
            "item_graph_recall": item_graph_stats["output_path"],
            "category_recall_items": category_stats["category_items_path"],
            "category_top_items": category_stats["category_top_path"],
            "semantic_recall_inputs": category_stats["semantic_path"],
        },
    }
    stats_payload = {
        "schema_version": "1.1",
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "recent_window_ratio": args.recent_window_ratio,
            "max_items_per_user_for_itemcf": args.max_items_per_user_for_itemcf,
            "category_top_k": args.category_top_k,
            "item_graph_window": args.item_graph_window,
            "item_graph_top_k": args.item_graph_top_k,
            "item_graph_min_score": args.item_graph_min_score,
            "item_graph_strong_multiplier": args.item_graph_strong_multiplier,
        },
        "popular_recall": popularity_stats,
        "itemcf_recall": itemcf_stats,
        "item_graph_recall": item_graph_stats,
        "category_recall": category_stats,
    }
    manifest_path = write_manifest(output_dir, manifest_payload)
    stats_path = write_stats(output_dir, stats_payload)

    print(f"Popularity recall written to: {popularity_stats['output_path']}")
    print(f"Weak ItemCF recall written to: {itemcf_stats['weak']['output_path']}")
    print(f"Strong ItemCF recall written to: {itemcf_stats['strong']['output_path']}")
    print(f"Item graph recall written to: {item_graph_stats['output_path']}")
    print(f"Category recall written to: {category_stats['category_items_path']}")
    print(f"Semantic recall inputs written to: {category_stats['semantic_path']}")
    print(f"Manifest written to: {manifest_path}")
    print(f"Stats written to: {stats_path}")


if __name__ == "__main__":
    main()
