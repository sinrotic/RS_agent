from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.config import load_config
from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_core.online.recall.candidate_merge import load_two_tower_index
from rs_core.online.recall.two_tower_query import build_two_tower_query_for_user, is_seed_average_source
from rs_core.online.recall.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_core.online.recall.vector_index import VectorIndex
from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS, method_output_dir

SCHEMA_VERSION = "pool500_two_tower_method_source_v1"
SOURCE = "two_tower"
SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_SOURCE_INDEX_MANIFEST = ROOT / "outputs" / "recall" / "pool500_full_sources" / "two_tower" / "source_index_manifest.json"
DEFAULT_ELIGIBLE_USER_MANIFEST = ROOT / "outputs" / "recall" / "pool500_main_route_direct_recall_full_promoted" / "eligible_user_manifest.json"
DEFAULT_CONFIG = ROOT / "configs" / "recall" / "full_data_pool500" / "two_tower" / "source_config.yaml"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources"
FORBIDDEN_PATH_TOKENS = {"holdout", "valid", "test", "lopo", "clean_10000", "pool1000"}
FORBIDDEN_PATH_PARTS = {"LOPO"}
GATE_FIELDS = (
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "pool1000_allowed",
    "auto_promotion_allowed",
    "promotion_allowed",
    "final_pool500_ready_claimed",
)


def build_two_tower_method_source(
    *,
    source_index_manifest_path: Path = DEFAULT_SOURCE_INDEX_MANIFEST,
    artifact_manifest_path: Path | None = None,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    eligible_user_manifest_path: Path | None = None,
    config_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    target_user_limit: int | None = None,
    batch_size: int | None = None,
    per_user_candidate_limit: int | None = None,
    candidate_limit_per_user: int | None = None,
    seed_window: int | None = None,
    recency_decay: float | None = None,
    overwrite: bool = False,
    resume: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    config = load_config(config_path) if config_path and Path(config_path).is_file() else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    if artifact_manifest_path is not None:
        source_index_manifest_path = artifact_manifest_path
    source_index_manifest_path = _config_path(method_config, "source_index_manifest_path", Path(str(method_config.get("artifact_manifest_path"))) if method_config.get("artifact_manifest_path") else source_index_manifest_path).resolve()
    clean_manifest_path = _config_path(method_config, "clean_manifest_path", clean_manifest_path).resolve()
    eligible_user_manifest_path = _optional_config_path(method_config, "eligible_user_manifest_path", eligible_user_manifest_path)
    output_root = Path(output_root).resolve() if output_root is not None else _config_path(config, "output_root", DEFAULT_OUTPUT_ROOT).resolve()
    run_id = str(run_id or config.get("run_id") or _default_run_id())
    batch_size = int(batch_size if batch_size is not None else method_config.get("batch_size", 50))
    target_user_limit = int(target_user_limit if target_user_limit is not None else method_config.get("target_user_limit", 500))
    if candidate_limit_per_user is not None:
        per_user_candidate_limit = candidate_limit_per_user
    per_user_candidate_limit = int(per_user_candidate_limit if per_user_candidate_limit is not None else method_config.get("per_user_candidate_limit", 500))
    seed_window = int(seed_window if seed_window is not None else method_config.get("seed_window", 30))
    recency_decay = float(recency_decay if recency_decay is not None else method_config.get("recency_decay", 0.85))
    _validate_positive(batch_size=batch_size, target_user_limit=target_user_limit, per_user_candidate_limit=per_user_candidate_limit, seed_window=seed_window)
    intended_read_paths = [source_index_manifest_path, clean_manifest_path]
    if eligible_user_manifest_path:
        intended_read_paths.append(eligible_user_manifest_path)
    _validate_actual_read_paths(intended_read_paths)
    validate_two_tower_source_index_manifest(source_index_manifest_path)

    output_dir = (output_root / run_id if output_root.name == SOURCE else method_output_dir(output_root, SOURCE, run_id)).resolve()
    final_marker = output_dir / "_FINALIZED.json"
    state_path = output_dir / "run_state.json"
    shard_dir = output_dir / "tmp" / "candidate_shards"
    config_hash_payload = {
        "source_index_manifest_path": str(source_index_manifest_path),
        "clean_manifest_path": str(clean_manifest_path),
        "eligible_user_manifest_path": str(eligible_user_manifest_path) if eligible_user_manifest_path else None,
        "target_user_limit": target_user_limit,
        "batch_size": batch_size,
        "per_user_candidate_limit": per_user_candidate_limit,
        "seed_window": seed_window,
        "recency_decay": recency_decay,
        "query_vector_policy": "artifact_user_embedding_first_then_projected_train_sequence_seed_average_vectors",
        "artifact_user_embedding_first": True,
        "project_seed_average": True,
        "seed_sequence_keys": ["recent_positive_item_sequence", "recent_strong_positive_item_sequence", "recent_item_sequence"],
        "source": SOURCE,
    }
    config_hash = _sha256_json(config_hash_payload)
    if output_dir.exists():
        if overwrite:
            shutil.rmtree(output_dir)
        elif resume:
            if not state_path.is_file() or read_json(state_path).get("config_hash") != config_hash:
                raise ValueError("resume requires the same config hash")
            if final_marker.exists():
                raise FileExistsError(f"complete output directory already exists: {output_dir}")
        elif final_marker.exists():
            raise FileExistsError(f"complete output directory already exists: {output_dir}")
        else:
            raise FileExistsError(f"incomplete output directory already exists; pass --resume or --overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    write_json(state_path, {"status": "RUNNING", "source": SOURCE, "source_status": SOURCE_STATUS, "diagnostic_only": True, "config_hash": config_hash, "config": config_hash_payload})

    clean_manifest = read_json(clean_manifest_path)
    train_sequences_path = _resolve_train_sequence_path(clean_manifest_path, clean_manifest)
    target_sequences = _load_target_sequences(train_sequences_path, eligible_user_manifest_path, target_user_limit)
    target_user_ids = [str(row["user_id"]) for row in target_sequences]
    artifact_index = load_two_tower_index(source_index_manifest_path)
    if not isinstance(artifact_index, VectorIndex):
        raise ValueError("two_tower source_index_manifest_path must load as VectorIndex")

    candidate_stats = _write_candidate_shards(
        target_sequences=target_sequences,
        vector_index=artifact_index,
        source_index_manifest_path=source_index_manifest_path,
        config_hash=config_hash,
        shard_dir=shard_dir,
        batch_size=batch_size,
        per_user_candidate_limit=per_user_candidate_limit,
        seed_window=seed_window,
        recency_decay=recency_decay,
        resume=resume,
    )
    candidates_path = output_dir / "candidates.jsonl"
    candidate_row_count = _merge_shards(shard_dir, candidates_path)
    candidate_signature = _file_signature(candidates_path)
    clean_signature = _file_signature(clean_manifest_path)
    train_signature = _file_signature(train_sequences_path)
    artifact_signature = _file_signature(source_index_manifest_path)
    read_paths = [source_index_manifest_path, clean_manifest_path, train_sequences_path]
    if eligible_user_manifest_path:
        read_paths.append(eligible_user_manifest_path)
    no_holdout_audit = _no_holdout_audit(read_paths, clean_manifest, clean_manifest_path.parent)
    if no_holdout_audit["status"] == "BLOCKED":
        raise ValueError(f"forbidden non-train read paths found: {no_holdout_audit['blocked_read_paths']}")

    count_stats = _count_stats(candidate_stats["candidate_counts"])
    reason_counts = dict(sorted(candidate_stats["reason_counts"].items()))
    common_flags = _common_flags()
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": SOURCE_STATUS,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "dataset_policy": "train_only_two_tower_target_slice_diagnostic",
        "train_only": True,
        "source_clean_manifest": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "source_index_manifest_path": str(source_index_manifest_path),
        "clean_manifest_sha256": clean_signature["sha256"],
        "train_sequence_sha256": train_signature["sha256"],
        "artifact_manifest_sha256": artifact_signature["sha256"],
        "target_user_count": len(target_user_ids),
        "target_user_ids_sha256": hashlib.sha256("\n".join(target_user_ids).encode("utf-8")).hexdigest(),
        "config_hash": config_hash,
        "config": config_hash_payload,
        "outputs": {
            "method_dataset_manifest": str(output_dir / "method_dataset_manifest.json"),
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "candidates": str(candidates_path),
            "coverage_audit": str(output_dir / "coverage_audit.json"),
            "undercoverage_audit": str(output_dir / "undercoverage_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
        },
        **common_flags,
    }
    coverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": SOURCE_STATUS,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "train_only": True,
        "target_user_count": len(target_user_ids),
        "candidate_row_count": candidate_row_count,
        "user_coverage_count": candidate_stats["user_coverage_count"],
        "artifact_user_embedding_hit_count": candidate_stats["artifact_user_embedding_hit_count"],
        "seed_vector_fallback_hit_count": candidate_stats["seed_vector_fallback_hit_count"],
        "seed_fallback_user_count": candidate_stats["seed_vector_fallback_hit_count"],
        "query_vector_user_count": candidate_stats["query_vector_user_count"],
        "candidate_under_limit_user_count": len(candidate_stats["undercovered_users"]),
        "candidate_count_stats": count_stats,
        "candidates_path": str(candidates_path),
        **common_flags,
    }
    undercoverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": SOURCE_STATUS,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "train_only": True,
        "method_target_per_user": per_user_candidate_limit,
        "target_user_count": len(target_user_ids),
        "undercovered_user_count": len(candidate_stats["undercovered_users"]),
        "users_with_target_candidates": candidate_stats["user_coverage_count"],
        "reason_counts": reason_counts,
        "sample_users": candidate_stats["undercovered_users"][:50],
        **common_flags,
    }
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": SOURCE_STATUS,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "train_only": True,
        "mode": "target_slice_diagnostic",
        "heavy_job": False,
        "checkpoint_enabled": True,
        "resume_enabled": True,
        "resumed_from_checkpoint": resume,
        "batch_size": batch_size,
        "shard_dir": str(shard_dir),
        "shard_count": candidate_stats["shard_count"],
        "config_hash": config_hash,
        "runtime_seconds": round(perf_counter() - started, 6),
        "candidate_signature": candidate_signature,
        "source_signatures": {
            "artifact_manifest": artifact_signature,
            "clean_manifest": clean_signature,
            "train_user_sequences": train_signature,
            "candidates": candidate_signature,
        },
        **common_flags,
    }
    outputs = {
        "method_dataset_manifest": str(output_dir / "method_dataset_manifest.json"),
        "source_index_manifest": str(output_dir / "source_index_manifest.json"),
        "candidates": str(candidates_path),
        "coverage_audit": str(output_dir / "coverage_audit.json"),
        "undercoverage_audit": str(output_dir / "undercoverage_audit.json"),
        "resource_audit": str(output_dir / "resource_audit.json"),
        "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
    }
    method_dataset_manifest["outputs"] = outputs
    source_index_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.source_index_manifest",
        "status": SOURCE_STATUS,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "index_scope": "TARGET_SLICE_DIAGNOSTIC_INDEX",
        "train_only": True,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "recall_index_path": str(source_index_manifest_path),
        "source_index_manifest_path": str(source_index_manifest_path),
        "candidate_path": str(candidates_path),
        "candidates_path": str(candidates_path),
        "candidate_row_count": candidate_row_count,
        "candidate_user_count": candidate_stats["user_coverage_count"],
        "row_count": candidate_row_count,
        "vector_index_item_count": len(artifact_index.items),
        "artifact_user_embedding_count": len(artifact_index.user_embeddings),
        "query_vector_policy": "artifact_user_embedding_first_then_projected_train_sequence_seed_average_vectors",
        "generation_config_overrides": {
            "two_tower_enabled": True,
            "two_tower_per_user": per_user_candidate_limit,
            "two_tower_query_batch_size": batch_size,
            "two_tower_seed_window": seed_window,
            "two_tower_recency_decay": recency_decay,
        },
        "outputs": outputs,
        **common_flags,
    }
    source_index_manifest["manifest_sha256"] = _sha256_json(source_index_manifest)
    method_dataset_manifest["source_index_manifest_sha256"] = source_index_manifest["manifest_sha256"]

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    required_outputs_present = {name: (output_dir / name).is_file() for name in REQUIRED_SOURCE_OUTPUTS}
    if not all(required_outputs_present.values()):
        raise RuntimeError(f"missing required outputs: {required_outputs_present}")
    write_json(final_marker, {"status": "PASS", "source": SOURCE, "source_status": SOURCE_STATUS, "diagnostic_only": True, "config_hash": config_hash})
    write_json(state_path, {"status": "COMPLETE", "source": SOURCE, "source_status": SOURCE_STATUS, "diagnostic_only": True, "config_hash": config_hash, "config": config_hash_payload})
    return {**source_index_manifest, "config_hash": config_hash, "required_outputs_present": required_outputs_present, "coverage_audit": coverage_audit, "undercoverage_audit": undercoverage_audit}


def _write_candidate_shards(
    *,
    target_sequences: list[dict[str, Any]],
    vector_index: VectorIndex,
    source_index_manifest_path: Path,
    config_hash: str,
    shard_dir: Path,
    batch_size: int,
    per_user_candidate_limit: int,
    seed_window: int,
    recency_decay: float,
    resume: bool,
) -> dict[str, Any]:
    candidate_counts: list[int] = []
    undercovered_users: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    user_coverage_count = 0
    artifact_user_embedding_hit_count = 0
    seed_vector_fallback_hit_count = 0
    query_vector_user_count = 0
    shard_count = 0
    for batch_index, batch in enumerate(_chunks(target_sequences, batch_size)):
        shard_path = shard_dir / f"batch_{batch_index:05d}.jsonl"
        checkpoint_path = shard_path.with_suffix(".json")
        if resume and shard_path.is_file() and checkpoint_path.is_file():
            checkpoint = read_json(checkpoint_path)
            for count in checkpoint.get("candidate_counts", []):
                count = int(count)
                candidate_counts.append(count)
                if count:
                    user_coverage_count += 1
            undercovered_users.extend(checkpoint.get("undercovered_users", []))
            reason_counts.update(checkpoint.get("reason_counts", {}))
            artifact_user_embedding_hit_count += int(checkpoint.get("artifact_user_embedding_hit_count", 0))
            seed_vector_fallback_hit_count += int(checkpoint.get("seed_vector_fallback_hit_count", 0))
            query_vector_user_count += int(checkpoint.get("query_vector_user_count", 0))
            shard_count += 1
            continue
        query_vectors: dict[str, list[float]] = {}
        excluded_items: dict[str, set[str]] = {}
        query_sources: dict[str, str] = {}
        seed_counts: dict[str, int] = {}
        seed_vector_counts: dict[str, int] = {}
        queryless_reasons: dict[str, str] = {}
        projected_seed_queries: set[str] = set()
        for sequence in batch:
            user_id = str(sequence.get("user_id") or "")
            query = build_two_tower_query_for_user(
                sequence,
                vector_index,
                seed_window=seed_window,
                recency_decay=recency_decay,
                artifact_user_embedding_first=True,
                project_seed_average=True,
            )
            excluded_items[user_id] = query.excluded_items
            seed_counts[user_id] = query.seed_item_count
            seed_vector_counts[user_id] = query.seed_vector_count
            if query.applied_projection:
                projected_seed_queries.add(user_id)
            if query.has_query:
                query_vectors[user_id] = query.query_vector
                query_sources[user_id] = query.query_source
            else:
                queryless_reasons[user_id] = query.queryless_reason or "unknown"
        search_results = vector_index.search_many(query_vectors, per_user_candidate_limit, excluded_items) if query_vectors else {}
        batch_result = _write_candidate_batch(
            batch=batch,
            shard_path=shard_path,
            checkpoint_path=checkpoint_path,
            search_results=search_results,
            query_vectors=query_vectors,
            query_sources=query_sources,
            seed_counts=seed_counts,
            seed_vector_counts=seed_vector_counts,
            queryless_reasons=queryless_reasons,
            projected_seed_queries=projected_seed_queries,
            per_user_candidate_limit=per_user_candidate_limit,
            source_index_manifest_path=source_index_manifest_path,
            config_hash=config_hash,
            batch_index=batch_index,
        )
        batch_counts = batch_result["candidate_counts"]
        batch_undercovered = batch_result["undercovered_users"]
        batch_reasons = Counter(batch_result["reason_counts"])
        candidate_counts.extend(batch_counts)
        user_coverage_count += sum(1 for count in batch_counts if int(count) > 0)
        undercovered_users.extend(batch_undercovered)
        reason_counts.update(batch_reasons)
        artifact_user_embedding_hit_count += batch_result["artifact_user_embedding_hit_count"]
        seed_vector_fallback_hit_count += batch_result["seed_vector_fallback_hit_count"]
        query_vector_user_count += batch_result["query_vector_user_count"]
        shard_count += 1
    return {
        "candidate_counts": candidate_counts,
        "undercovered_users": undercovered_users,
        "reason_counts": reason_counts,
        "user_coverage_count": user_coverage_count,
        "artifact_user_embedding_hit_count": artifact_user_embedding_hit_count,
        "seed_vector_fallback_hit_count": seed_vector_fallback_hit_count,
        "query_vector_user_count": query_vector_user_count,
        "shard_count": shard_count,
    }


def _write_candidate_batch(
    *,
    batch: list[dict[str, Any]],
    shard_path: Path,
    checkpoint_path: Path,
    search_results: dict[str, list[Any]],
    query_vectors: dict[str, list[float]],
    query_sources: dict[str, str],
    seed_counts: dict[str, int],
    seed_vector_counts: dict[str, int],
    queryless_reasons: dict[str, str],
    projected_seed_queries: set[str],
    per_user_candidate_limit: int,
    source_index_manifest_path: Path,
    config_hash: str,
    batch_index: int,
) -> dict[str, Any]:
    batch_counts: list[int] = []
    batch_undercovered: list[dict[str, Any]] = []
    batch_reasons: Counter[str] = Counter()
    with shard_path.open("w", encoding="utf-8") as handle:
        for sequence in batch:
            user_id = str(sequence.get("user_id") or "")
            results = search_results.get(user_id, [])
            count = len(results)
            batch_counts.append(count)
            if user_id not in query_vectors:
                reason = queryless_reasons.get(user_id, "unknown")
            elif count == 0:
                reason = "vector_search_returned_no_candidates"
            elif count < per_user_candidate_limit:
                reason = "vector_search_fanout_below_target"
            else:
                reason = ""
            if reason:
                row = {
                    "user_id": user_id,
                    "candidate_count": count,
                    "query_source": query_sources.get(user_id, "none"),
                    "seed_item_count": seed_counts.get(user_id, 0),
                    "seed_vector_count": seed_vector_counts.get(user_id, 0),
                    "reason": reason,
                }
                batch_undercovered.append(row)
                batch_reasons[reason] += 1
            for rank, candidate in enumerate(results, start=1):
                metadata = dict(candidate.metadata)
                query_source = query_sources.get(user_id, "none")
                query_vector_source = "seed_item_average" if is_seed_average_source(query_source) else query_source
                metadata.update({
                    "canonical_source": SOURCE,
                    "source_status": SOURCE_STATUS,
                    "diagnostic_only": True,
                    "query_source": query_source,
                    "query_vector_source": query_vector_source,
                    "seed_item_count": seed_counts.get(user_id, 0),
                    "seed_vector_count": seed_vector_counts.get(user_id, 0),
                    "applied_query_projection": user_id in projected_seed_queries,
                    "source_index_manifest_path": str(source_index_manifest_path),
                    "config_hash": config_hash,
                })
                handle.write(json.dumps({
                    "user_id": user_id,
                    "item_id": candidate.item_id,
                    "source": SOURCE,
                    "canonical_source": SOURCE,
                    "sources": [SOURCE],
                    "source_status": SOURCE_STATUS,
                    "diagnostic_only": True,
                    "score": candidate.score,
                    "rank": rank,
                    "metadata": metadata,
                }, ensure_ascii=False) + "\n")
    result = {
        "status": "PASS",
        "source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "batch_index": batch_index,
        "candidate_counts": batch_counts,
        "undercovered_users": batch_undercovered,
        "reason_counts": dict(sorted(batch_reasons.items())),
        "artifact_user_embedding_hit_count": sum(1 for row in batch if query_sources.get(str(row.get("user_id") or "")) == "artifact_user_embedding"),
        "seed_vector_fallback_hit_count": sum(1 for row in batch if is_seed_average_source(query_sources.get(str(row.get("user_id") or ""), ""))),
        "query_vector_user_count": len(query_vectors),
    }
    write_json(checkpoint_path, result)
    return result


def _merge_shards(shard_dir: Path, candidates_path: Path) -> int:
    row_count = 0
    with candidates_path.open("w", encoding="utf-8") as output:
        for shard_path in sorted(shard_dir.glob("batch_*.jsonl")):
            with shard_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        output.write(line)
                        row_count += 1
    return row_count


def _load_target_sequences(train_sequences_path: Path, eligible_user_manifest_path: Path | None, limit: int) -> list[dict[str, Any]]:
    eligible_user_ids: list[str] = []
    if eligible_user_manifest_path and eligible_user_manifest_path.is_file():
        manifest = read_json(eligible_user_manifest_path)
        raw_ids = manifest.get("eligible_user_ids") or manifest.get("target_user_ids") or []
        eligible_user_ids = [str(user_id) for user_id in raw_ids if user_id]
    if eligible_user_ids:
        wanted = set(eligible_user_ids[:limit])
        rows = [row for row in iter_jsonl(train_sequences_path) if str(row.get("user_id") or "") in wanted]
        by_user = {str(row.get("user_id")): row for row in rows}
        return [by_user[user_id] for user_id in eligible_user_ids[:limit] if user_id in by_user]
    rows = []
    for row in iter_jsonl(train_sequences_path):
        if row.get("user_id"):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _resolve_train_sequence_path(clean_manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path") or manifest.get("user_sequences_train_path") or clean_manifest_path.parent / "user_sequences.train.jsonl"
    path = Path(str(raw_path))
    path = path if path.is_absolute() else ROOT / path
    path = path.resolve()
    if path.name != "user_sequences.train.jsonl":
        raise ValueError(f"only user_sequences.train.jsonl is allowed for train sequence reads: {path}")
    if _is_forbidden_actual_read_path(path):
        raise ValueError(f"forbidden non-train path is not allowed: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _no_holdout_audit(read_paths: list[Path], clean_manifest: dict[str, Any], clean_manifest_dir: Path) -> dict[str, Any]:
    blocked = [str(path) for path in read_paths if _is_forbidden_actual_read_path(path)]
    ignored = _ignored_evaluation_only_paths(clean_manifest, clean_manifest_dir)
    return {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS" if not blocked else "BLOCKED",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "train_only": True,
        "read_paths": [str(path) for path in read_paths],
        "blocked_read_paths": blocked,
        "ignored_evaluation_only_paths": ignored,
        "forbidden_tokens": sorted(FORBIDDEN_PATH_TOKENS | {token.lower() for token in FORBIDDEN_PATH_PARTS}),
        "candidate_generation_uses_holdout": False,
        "uses_holdout": False,
        "uses_valid": False,
        "uses_test": False,
        "uses_lopo": False,
        "uses_pool1000": False,
        **_common_flags(),
    }


def _ignored_evaluation_only_paths(manifest: dict[str, Any], clean_manifest_dir: Path) -> list[str]:
    ignored: list[str] = []
    split_paths = manifest.get("split_paths")
    if isinstance(split_paths, dict):
        for key in ("valid", "validation", "test", "holdout", "lopo", "LOPO"):
            if split_paths.get(key):
                ignored.append(str(_manifest_relative_path(split_paths[key], clean_manifest_dir)))
    for key in ("valid", "validation", "test", "holdout", "lopo", "LOPO"):
        direct_key = f"{key}_path"
        if manifest.get(direct_key):
            ignored.append(str(_manifest_relative_path(manifest[direct_key], clean_manifest_dir)))
    return list(dict.fromkeys(ignored))


def _manifest_relative_path(raw_path: Any, base_dir: Path) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    root_relative = (ROOT / path).resolve()
    if root_relative.exists() or str(path).replace("\\", "/").startswith(("data/", "outputs/", "configs/")):
        return root_relative
    return (base_dir / path).resolve()


def _validate_actual_read_paths(paths: list[Path]) -> None:
    blocked = [str(path) for path in paths if _is_forbidden_actual_read_path(path)]
    if blocked:
        raise ValueError(f"forbidden non-train read paths found: {blocked}")


def _is_forbidden_actual_read_path(path: Path) -> bool:
    normalized = str(path).replace("\\", "/")
    lowered = normalized.lower()
    parts = {part.lower() for part in Path(lowered).parts}
    return bool(parts & FORBIDDEN_PATH_TOKENS) or any(part in normalized for part in FORBIDDEN_PATH_PARTS)


def _config_path(config: dict[str, Any], key: str, default: Path) -> Path:
    raw = config.get(key) or default
    path = Path(str(raw))
    return path if path.is_absolute() else ROOT / path


def _optional_config_path(config: dict[str, Any], key: str, default: Path | None) -> Path | None:
    raw = config.get(key) if config.get(key) is not None else default
    if raw is None or str(raw) == "":
        return None
    path = Path(str(raw))
    return (path if path.is_absolute() else ROOT / path).resolve()


def _common_flags() -> dict[str, bool]:
    return {"diagnostic_only": True, **{field: False for field in GATE_FIELDS}}


def _validate_positive(**values: int) -> None:
    for label, value in values.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")


def _chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


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


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {"path": str(path), "bytes": path.stat().st_size, "row_count": rows, "sha256": digest.hexdigest()}


def _sha256_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pool500 two_tower method source diagnostic artifacts.")
    parser.add_argument("--source-index-manifest", "--source-index-manifest-path", "--artifact-manifest", "--artifact-manifest-path", dest="source_index_manifest", default=str(DEFAULT_SOURCE_INDEX_MANIFEST))
    parser.add_argument("--clean-manifest", "--clean-manifest-path", dest="clean_manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--eligible-user-manifest", "--eligible-user-manifest-path", dest="eligible_user_manifest", default="")
    parser.add_argument("--config", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--target-user-limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--per-user-candidate-limit", "--candidate-limit-per-user", dest="per_user_candidate_limit", type=int, default=None)
    parser.add_argument("--seed-window", type=int, default=None)
    parser.add_argument("--recency-decay", type=float, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-venv-check", "--no-enforce-venv", dest="skip_venv_check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_two_tower_method_source(
        source_index_manifest_path=Path(args.source_index_manifest),
        clean_manifest_path=Path(args.clean_manifest),
        eligible_user_manifest_path=Path(args.eligible_user_manifest) if args.eligible_user_manifest else None,
        config_path=Path(args.config) if args.config else None,
        output_root=Path(args.output_root),
        run_id=args.run_id or None,
        target_user_limit=args.target_user_limit,
        batch_size=args.batch_size,
        per_user_candidate_limit=args.per_user_candidate_limit,
        seed_window=args.seed_window,
        recency_decay=args.recency_decay,
        overwrite=args.overwrite,
        resume=args.resume,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({
        "status": manifest["status"],
        "source": SOURCE,
        "source_status": manifest["source_status"],
        "output_dir": manifest["output_dir"],
        "method_dataset_manifest": manifest["outputs"]["method_dataset_manifest"],
        "source_index_manifest": manifest["outputs"]["source_index_manifest"],
        "candidate_row_count": manifest["candidate_row_count"],
        "candidate_user_count": manifest["candidate_user_count"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
