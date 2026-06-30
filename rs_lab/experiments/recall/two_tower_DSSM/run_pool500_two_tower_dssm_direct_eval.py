from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_core.offline.training.two_tower_DSSM.source_manifest import validate_two_tower_dssm_source_index_manifest
from rs_core.online.recall.two_tower_query import build_two_tower_query_for_user
from rs_core.online.recall.vector_index import load_vector_index_artifact, normalize_vector
from rs_lab.experiments.recall.run_pool500_two_tower_direct_eval import (
    DEFAULT_METRIC_KS,
    _count_stats,
    _load_eval_users,
    _load_labels,
    _load_sequences,
    _parse_metric_ks,
    _resolve_manifest_path,
    _score_results,
    _validate_inputs,
)

SCHEMA_VERSION = "raw_two_tower_dssm_direct_eval_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a two_tower_DSSM source index directly on fixed pool500 users.")
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


def run_two_tower_dssm_direct_eval(
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
    source_manifest = validate_two_tower_dssm_source_index_manifest(source_index_manifest_path)
    index_path = _resolve_manifest_path(source_index_manifest_path, source_manifest["index_path"])
    index = load_vector_index_artifact(index_path)
    user_embedding_path = source_manifest.get("user_embedding_path")
    resolved_user_embedding_path = None
    if user_embedding_path:
        resolved_user_embedding_path = _resolve_manifest_path(source_index_manifest_path, user_embedding_path)
        index.user_embeddings.update(_load_user_vectors(resolved_user_embedding_path))
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
    candidate_generation_inputs = [str(train_sequences_path), str(index_path)]
    if resolved_user_embedding_path:
        candidate_generation_inputs.append(str(resolved_user_embedding_path))

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_index_manifest": str(source_index_manifest_path),
        "index_path": str(index_path),
        "eval_scope": "two_tower_dssm_direct_only",
        "no_oracle_label_injection": True,
        "candidate_generation_inputs": candidate_generation_inputs,
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
        "raw_two_tower_dssm_unique_positive_hits": raw_hit_count,
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


def _load_user_vectors(path: Path) -> dict[str, list[float]]:
    vectors = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        vector = normalize_vector([float(value) for value in row.get("embedding", [])])
        if user_id and vector:
            vectors[user_id] = vector
    return vectors


def main() -> None:
    args = parse_args()
    manifest = run_two_tower_dssm_direct_eval(
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
