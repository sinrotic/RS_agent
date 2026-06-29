from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_core.online.recall.two_tower_query import build_two_tower_query_for_user
from rs_core.online.recall.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_core.online.recall.vector_index import load_vector_index_artifact

SCHEMA_VERSION = "raw_two_tower_direct_eval_v1"
POSITIVE_FIELDS = ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased")
DEFAULT_METRIC_KS = (20, 50, 100, 500)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a TwoTower source index directly on fixed pool500 users.")
    parser.add_argument("--source-index-manifest", required=True)
    parser.add_argument("--eval-users", required=True)
    parser.add_argument("--train-sequences", required=True)
    parser.add_argument("--label-paths", nargs="+", required=True)
    parser.add_argument("--output-manifest", required=True)
    parser.add_argument("--metric-ks", default=",".join(str(k) for k in DEFAULT_METRIC_KS))
    parser.add_argument("--seed-window", type=int, default=10)
    parser.add_argument("--recency-decay", type=float, default=0.85)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--item-block-size", type=int, default=50000)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_two_tower_direct_eval(
    *,
    source_index_manifest_path: Path,
    eval_users_path: Path,
    train_sequences_path: Path,
    label_paths: list[Path],
    output_manifest_path: Path,
    metric_ks: Iterable[int] = DEFAULT_METRIC_KS,
    seed_window: int = 10,
    recency_decay: float = 0.85,
    batch_size: int = 512,
    item_block_size: int = 50000,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    metric_ks = _parse_metric_ks(metric_ks)
    if seed_window <= 0:
        raise ValueError("seed_window must be positive")
    if batch_size <= 0 or item_block_size <= 0:
        raise ValueError("batch_size and item_block_size must be positive")

    started = perf_counter()
    source_manifest = validate_two_tower_source_index_manifest(source_index_manifest_path)
    index_path = _resolve_manifest_path(source_index_manifest_path, source_manifest["index_path"])
    index = load_vector_index_artifact(index_path)
    index.model_metadata.update(
        {
            "artifact_type": source_manifest.get("schema_version"),
            "variant": source_manifest.get("variant"),
            "model_type": source_manifest.get("model_type"),
            "source_name": source_manifest.get("source_name"),
            "model_parameters": source_manifest.get("model_parameters", {}),
        }
    )
    load_index_seconds = perf_counter() - started

    users = _load_eval_users(eval_users_path)
    eval_user_ids = [str(row["user_id"]) for row in users]
    eval_user_set = set(eval_user_ids)
    segments = {str(row["user_id"]): str(row.get("segment") or "unknown") for row in users}
    sequences = _load_sequences(train_sequences_path, eval_user_set)
    labels_by_user = _load_labels(label_paths, eval_user_ids)
    _validate_inputs(eval_user_ids, sequences, labels_by_user)

    query_vectors: dict[str, list[float]] = {}
    excluded_items: dict[str, set[str]] = {}
    query_sources: dict[str, str] = {}
    queryless_users: list[str] = []
    queryless_reasons: Counter[str] = Counter()
    seed_item_counts: list[int] = []
    seed_vector_counts: list[int] = []
    projected_seed_query_count = 0
    for user_id in eval_user_ids:
        query = build_two_tower_query_for_user(
            sequences[user_id],
            index,
            seed_window=seed_window,
            recency_decay=recency_decay,
            artifact_user_embedding_first=True,
            project_seed_average=True,
        )
        seed_item_counts.append(query.seed_item_count)
        seed_vector_counts.append(query.seed_vector_count)
        if query.applied_projection:
            projected_seed_query_count += 1
        if query.has_query:
            query_vectors[user_id] = query.query_vector
            excluded_items[user_id] = query.excluded_items
            query_sources[user_id] = query.query_source
        else:
            queryless_users.append(user_id)
            queryless_reasons[query.queryless_reason or "unknown"] += 1

    search_started = perf_counter()
    results_by_user = {}
    query_items = list(query_vectors.items())
    limit = max(metric_ks)
    for start in range(0, len(query_items), batch_size):
        batch = dict(query_items[start : start + batch_size])
        batch_excluded = {user_id: excluded_items[user_id] for user_id in batch}
        results_by_user.update(index.search_many(batch, limit=limit, excluded_items=batch_excluded, item_block_size=item_block_size))
    search_seconds = perf_counter() - search_started

    metrics, segment_metrics, raw_hit_count, candidate_rows, underfilled_user_count = _score_results(
        eval_user_ids=eval_user_ids,
        labels_by_user=labels_by_user,
        results_by_user=results_by_user,
        segments=segments,
        metric_ks=metric_ks,
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_index_manifest": str(source_index_manifest_path),
        "index_path": str(index_path),
        "eval_scope": "two_tower_direct_only",
        "no_oracle_label_injection": True,
        "candidate_generation_inputs": [str(train_sequences_path), str(index_path)],
        "label_paths": [str(path) for path in label_paths],
        "metric_ks": metric_ks,
        "user_count": len(eval_user_ids),
        "query_user_count": len(query_vectors),
        "queryless_user_count": len(queryless_users),
        "query_source_counts": dict(sorted(Counter(query_sources.values()).items())),
        "queryless_reason_counts": dict(sorted(queryless_reasons.items())),
        "seed_item_count_stats": _count_stats(seed_item_counts),
        "seed_vector_count_stats": _count_stats(seed_vector_counts),
        "projected_seed_query_count": projected_seed_query_count,
        "item_count": len(index.items),
        "candidate_rows": candidate_rows,
        "underfilled_user_count": underfilled_user_count,
        "underfilled_user_rate": round(underfilled_user_count / len(eval_user_ids), 6) if eval_user_ids else 0.0,
        "positive_denominator_at_500": sum(len(labels_by_user[user_id]) for user_id in eval_user_ids),
        "raw_two_tower_unique_positive_hits": raw_hit_count,
        "metrics": metrics,
        "segment_metrics": segment_metrics,
        "timing_seconds": {
            "load_index": round(load_index_seconds, 6),
            "search": round(search_seconds, 6),
            "total": round(perf_counter() - started, 6),
        },
        "search_config": {
            "limit": limit,
            "seed_window": seed_window,
            "recency_decay": recency_decay,
            "batch_size": batch_size,
            "item_block_size": item_block_size,
            "artifact_user_embedding_first": True,
            "project_seed_average": True,
            "seed_sequence_keys": ["recent_positive_item_sequence", "recent_strong_positive_item_sequence", "recent_item_sequence"],
            "user_tower_projection": bool(source_manifest.get("model_parameters")),
        },
    }
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_manifest_path, manifest)
    return manifest


def _parse_metric_ks(values: Iterable[int] | str) -> list[int]:
    if isinstance(values, str):
        raw_values = [value.strip() for value in values.split(",") if value.strip()]
    else:
        raw_values = list(values)
    metric_ks = sorted({int(value) for value in raw_values})
    if not metric_ks or any(k <= 0 for k in metric_ks):
        raise ValueError("metric_ks must contain positive integers")
    return metric_ks


def _resolve_manifest_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else manifest_path.resolve().parent / path


def _count_stats(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    return {"min": ordered[0], "p50": _percentile(ordered, 0.5), "p90": _percentile(ordered, 0.9), "max": ordered[-1]}


def _percentile(values: list[int], q: float) -> float:
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(values) - 1)
    weight = pos - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 6)


def _load_eval_users(path: Path) -> list[dict[str, Any]]:
    users = [row for row in iter_jsonl(path)]
    if not users:
        raise ValueError("eval users file is empty")
    user_ids = [str(row.get("user_id") or "") for row in users]
    if any(not user_id for user_id in user_ids):
        raise ValueError("eval users contain missing user_id")
    if len(set(user_ids)) != len(user_ids):
        raise ValueError("eval users contain duplicate user_id")
    return users


def _load_sequences(path: Path, eval_user_set: set[str]) -> dict[str, dict[str, Any]]:
    sequences = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or row.get("reviewer_id") or "")
        if user_id in eval_user_set:
            sequences[user_id] = row
    return sequences


def _load_labels(label_paths: list[Path], eval_user_ids: list[str]) -> dict[str, set[str]]:
    labels_by_user = {user_id: set() for user_id in eval_user_ids}
    for label_path in label_paths:
        for row in iter_jsonl(label_path):
            if not _is_positive(row):
                continue
            user_id = str(row.get("user_id") or row.get("user") or "")
            if user_id not in labels_by_user:
                continue
            item_id = str(row.get("parent_asin") or row.get("item_id") or row.get("item") or "")
            if item_id:
                labels_by_user[user_id].add(item_id)
    return labels_by_user


def _is_positive(row: dict[str, Any]) -> bool:
    present_fields = [field for field in POSITIVE_FIELDS if field in row]
    if not present_fields:
        return True
    return any(bool(row.get(field)) for field in present_fields)


def _validate_inputs(eval_user_ids: list[str], sequences: dict[str, dict[str, Any]], labels_by_user: dict[str, set[str]]) -> None:
    missing_sequences = [user_id for user_id in eval_user_ids if user_id not in sequences]
    missing_labels = [user_id for user_id in eval_user_ids if not labels_by_user[user_id]]
    if missing_sequences or missing_labels:
        raise ValueError(
            json.dumps(
                {
                    "missing_sequences": len(missing_sequences),
                    "missing_labels": len(missing_labels),
                    "missing_sequence_sample": missing_sequences[:5],
                    "missing_label_sample": missing_labels[:5],
                },
                ensure_ascii=False,
            )
        )


def _score_results(
    *,
    eval_user_ids: list[str],
    labels_by_user: dict[str, set[str]],
    results_by_user: dict[str, Any],
    segments: dict[str, str],
    metric_ks: list[int],
) -> tuple[dict[str, float], dict[str, dict[str, float | int]], int, int, int]:
    denominators = {k: 0 for k in metric_ks}
    hits = {k: 0 for k in metric_ks}
    hit_users = {k: 0 for k in metric_ks}
    segment_user_counts = Counter(segments.values())
    segment_denominators = {segment: {k: 0 for k in metric_ks} for segment in segment_user_counts}
    segment_hits = {segment: {k: 0 for k in metric_ks} for segment in segment_user_counts}
    segment_hit_users = {segment: {k: 0 for k in metric_ks} for segment in segment_user_counts}
    unique_positive_hits = set()
    candidate_rows = 0
    underfilled_user_count = 0
    limit = max(metric_ks)
    for user_id in eval_user_ids:
        labels = labels_by_user[user_id]
        ranked = [row.item_id for row in results_by_user.get(user_id, [])]
        candidate_rows += len(ranked)
        if len(ranked) < limit:
            underfilled_user_count += 1
        segment = segments[user_id]
        for k in metric_ks:
            hit_set = labels & set(ranked[:k])
            denominators[k] += len(labels)
            hits[k] += len(hit_set)
            hit_users[k] += int(bool(hit_set))
            segment_denominators[segment][k] += len(labels)
            segment_hits[segment][k] += len(hit_set)
            segment_hit_users[segment][k] += int(bool(hit_set))
            unique_positive_hits.update((user_id, item_id) for item_id in hit_set)
    metrics = {}
    for k in metric_ks:
        metrics[f"recall_at_{k}"] = round(hits[k] / denominators[k], 6) if denominators[k] else 0.0
        metrics[f"hit_rate_at_{k}"] = round(hit_users[k] / len(eval_user_ids), 6) if eval_user_ids else 0.0
    segment_metrics = {}
    for segment in sorted(segment_user_counts):
        segment_metrics[segment] = {"user_count": segment_user_counts[segment]}
        for k in metric_ks:
            segment_metrics[segment][f"recall_at_{k}"] = (
                round(segment_hits[segment][k] / segment_denominators[segment][k], 6) if segment_denominators[segment][k] else 0.0
            )
            segment_metrics[segment][f"hit_rate_at_{k}"] = (
                round(segment_hit_users[segment][k] / segment_user_counts[segment], 6) if segment_user_counts[segment] else 0.0
            )
    return metrics, segment_metrics, len(unique_positive_hits), candidate_rows, underfilled_user_count


def main() -> None:
    args = parse_args()
    manifest = run_two_tower_direct_eval(
        source_index_manifest_path=Path(args.source_index_manifest),
        eval_users_path=Path(args.eval_users),
        train_sequences_path=Path(args.train_sequences),
        label_paths=[Path(path) for path in args.label_paths],
        output_manifest_path=Path(args.output_manifest),
        metric_ks=_parse_metric_ks(args.metric_ks),
        seed_window=args.seed_window,
        recency_decay=args.recency_decay,
        batch_size=args.batch_size,
        item_block_size=args.item_block_size,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
