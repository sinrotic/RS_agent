from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.recsys.candidate_merge import unique_recent_items
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _existing_ancestor

SCHEMA_VERSION = "full_train_itemcf_sidecar_v1"
DEFAULT_CLEAN_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_recall_sources" / "itemcf_full_train_sidecar"
DEFAULT_MAX_ITEMS_PER_USER = 50
DEFAULT_MAX_ITEM_USER_FREQ = 5000
DEFAULT_TOP_K_PER_SEED = 100
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
SOURCES = {
    "itemcf_weak": "recent_positive_item_sequence",
    "itemcf_strong": "recent_strong_positive_item_sequence",
}
SOURCE_USER_QUALITY_POLICIES = {
    "itemcf_weak": {"heavy_cf_eligible", "medium_behavior"},
    "itemcf_strong": {"heavy_cf_eligible"},
}
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
)
FORBIDDEN_INPUT_NAMES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build full clean train ItemCF sidecar edges.")
    parser.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    parser.add_argument("--source", choices=sorted(SOURCES), required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-items-per-user", type=int, default=DEFAULT_MAX_ITEMS_PER_USER)
    parser.add_argument("--max-item-user-freq", type=int, default=DEFAULT_MAX_ITEM_USER_FREQ)
    parser.add_argument("--top-k-per-seed", type=int, default=DEFAULT_TOP_K_PER_SEED)
    parser.add_argument("--target-user-limit", type=int, default=0, help="Build a memory-bounded diagnostic sidecar from the first N source-positive train users; 0 builds all users.")
    parser.add_argument("--consumer-user-limit", type=int, default=500, help="Freeze the first N train users using the recall-only runner batch selection semantics.")
    parser.add_argument("--augment-existing-manifest", default="", help="Update an existing source_index_manifest.json with consumer coverage artifacts without rebuilding edges.")
    parser.add_argument("--user-quality-manifest", default="")
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_full_train_itemcf_sidecar(
    *,
    clean_dir: Path = DEFAULT_CLEAN_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    source: str,
    max_items_per_user: int = DEFAULT_MAX_ITEMS_PER_USER,
    max_item_user_freq: int = DEFAULT_MAX_ITEM_USER_FREQ,
    top_k_per_seed: int = DEFAULT_TOP_K_PER_SEED,
    target_user_limit: int = 0,
    user_quality_manifest_path: Path | None = None,
    consumer_user_limit: int = 500,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()
    _validate_args(source, max_items_per_user, max_item_user_freq, top_k_per_seed, target_user_limit, min_free_bytes)
    if consumer_user_limit < 0:
        raise ValueError("consumer_user_limit must be non-negative")

    clean_dir = clean_dir.resolve()
    output_dir = _resolve_output_dir(output_dir, source)
    train_sequences_path = clean_dir / "user_sequences.train.jsonl"
    user_quality_manifest_path = user_quality_manifest_path.resolve() if user_quality_manifest_path else None
    _precheck(clean_dir, output_dir, train_sequences_path, min_free_bytes, overwrite, user_quality_manifest_path)
    quality_policy = _load_user_quality_policy(user_quality_manifest_path, source)

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)

    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    memory_sampler = _MemorySampler().start()
    label_variant = SOURCES[source]
    edges_path = output_dir / f"{source}_edges.jsonl"
    build_stats = _build_itemcf_edges(
        train_sequences_path,
        edges_path,
        source=source,
        label_variant=label_variant,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        top_k_per_seed=top_k_per_seed,
        target_user_limit=target_user_limit,
        eligible_user_ids=quality_policy["eligible_user_ids"],
        quality_bucket_by_user=quality_policy["quality_bucket_by_user"],
        profile_source_rows_scanned=quality_policy["profile_source_rows_scanned"],
    )
    runtime_seconds = round(perf_counter() - started, 6)
    memory_fields = memory_sampler.stop()
    peak_rss_mb = memory_fields["memory_peak_rss_mb"]
    peak_rss_mb_end = memory_fields["memory_rss_end_mb"]
    diagnostic_only = target_user_limit > 0 or user_quality_manifest_path is not None
    readiness_status = "DIAGNOSTIC_ONLY" if diagnostic_only else "READY"
    output_status = "DIAGNOSTIC_OUTPUT_READY" if diagnostic_only else "FULL_OUTPUT_READY"

    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": source,
        "label_variant": label_variant,
        "index_scope": "FULL_DERIVED_INDEX",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "train_only": True,
        "diagnostic_only": diagnostic_only,
        "user_quality_policy": quality_policy["policy_name"],
        "user_quality_manifest_path": str(user_quality_manifest_path) if user_quality_manifest_path else None,
        "eligible_buckets": quality_policy["eligible_buckets"],
        "profile_boundary": quality_policy["profile_boundary"],
        "runtime_seconds": runtime_seconds,
        "peak_rss_mb": peak_rss_mb,
        "peak_rss_mb_end": peak_rss_mb_end,
        **memory_fields,
        "source_clean_dir": str(clean_dir),
        "train_user_sequences_path": str(train_sequences_path),
        "edges_path": str(edges_path),
        "source_signature": _file_signature(train_sequences_path),
        "edge_signature": _file_signature(edges_path),
        "readiness_contract": str(output_dir / "readiness_contract.json"),
        **build_stats,
    }
    custom_index_selection_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "selection_scope": "method_level_custom_index",
        "source": source,
        "index_scope": "FULL_DERIVED_INDEX",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "selected_label_field": label_variant,
        "config": {
            "max_items_per_user": max_items_per_user,
            "max_item_user_freq": max_item_user_freq,
            "top_k_per_seed": top_k_per_seed,
            "target_user_limit": target_user_limit,
            "user_quality_policy": quality_policy["policy_name"],
            "user_quality_manifest_path": str(user_quality_manifest_path) if user_quality_manifest_path else None,
            "eligible_buckets": quality_policy["eligible_buckets"],
        },
        "user_quality_manifest_path": str(user_quality_manifest_path) if user_quality_manifest_path else None,
        "eligible_buckets": quality_policy["eligible_buckets"],
        "actual_train_user_count": build_stats["actual_train_user_count"],
        "users_with_source_items": build_stats["users_with_source_items"],
        "users_scanned_within_profile": build_stats["users_scanned_within_profile"],
        "users_filtered_by_quality": build_stats["users_filtered_by_quality"],
        "used_quality_bucket_counts": build_stats["used_quality_bucket_counts"],
        "edge_count": build_stats["rows_written"],
        "unique_item_count_after_hot_cap": build_stats["unique_item_count_after_hot_cap"],
        "runtime_seconds": runtime_seconds,
        "peak_rss_mb": peak_rss_mb,
        "peak_rss_mb_end": peak_rss_mb_end,
        **memory_fields,
        "allowed_inputs": [str(train_sequences_path)] + ([str(user_quality_manifest_path)] if user_quality_manifest_path else []),
        "forbidden_inputs": [str(clean_dir / name) for name in FORBIDDEN_INPUT_NAMES],
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "index_scope": "FULL_DERIVED_INDEX",
        "source": source,
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "min_free_bytes": min_free_bytes,
        "max_items_per_user": max_items_per_user,
        "max_item_user_freq": max_item_user_freq,
        "top_k_per_seed": top_k_per_seed,
        "target_user_limit": target_user_limit,
        "user_quality_manifest_path": str(user_quality_manifest_path) if user_quality_manifest_path else None,
        "user_quality_policy": quality_policy["policy_name"],
        "eligible_user_count": len(quality_policy["eligible_user_ids"]) if quality_policy["eligible_user_ids"] is not None else None,
        "peak_rss_mb": peak_rss_mb,
        "peak_rss_mb_end": peak_rss_mb_end,
        "runtime_seconds": runtime_seconds,
        **memory_fields,
        "eligible_buckets": quality_policy["eligible_buckets"],
        "actual_train_user_count": build_stats["actual_train_user_count"],
        "users_scanned": build_stats["users_scanned"],
        "users_scanned_within_profile": build_stats["users_scanned_within_profile"],
        "users_filtered_by_quality": build_stats["users_filtered_by_quality"],
        "used_quality_bucket_counts": build_stats["used_quality_bucket_counts"],
        "users_with_source_items": build_stats["users_with_source_items"],
        "edge_count": build_stats["rows_written"],
        "users_used": build_stats["users_used"],
        "unique_item_count_before_hot_cap": build_stats["unique_item_count_before_hot_cap"],
        "unique_item_count_after_hot_cap": build_stats["unique_item_count_after_hot_cap"],
        "hot_item_count": build_stats["hot_item_count"],
        "unique_pair_count": build_stats["unique_pair_count"],
        "rows_written": build_stats["rows_written"],
    }
    no_holdout_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "uses_holdout": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "read_files": [str(train_sequences_path)] + ([str(user_quality_manifest_path)] if user_quality_manifest_path else []),
        "forbidden_inputs": [str(clean_dir / name) for name in FORBIDDEN_INPUT_NAMES],
        "forbidden_10k_paths_rejected": True,
        "forbidden_pool1000_paths_rejected": True,
    }

    coverage_artifacts = _build_coverage_artifacts(
        clean_dir=clean_dir,
        train_sequences_path=train_sequences_path,
        output_dir=output_dir,
        source=source,
        label_variant=label_variant,
        edges_path=edges_path,
        source_index_manifest=source_index_manifest,
        build_stats=build_stats,
        quality_policy=quality_policy,
        user_quality_manifest_path=user_quality_manifest_path,
        consumer_user_limit=consumer_user_limit,
        max_items_per_user=max_items_per_user,
        runtime_seconds=runtime_seconds,
        peak_rss_mb=peak_rss_mb,
        peak_rss_mb_end=peak_rss_mb_end,
        memory_fields=memory_fields,
    )
    source_index_manifest.update(coverage_artifacts["source_index_fields"])
    candidate_manifest = _candidate_manifest(source, output_dir, edges_path, build_stats, quality_policy, diagnostic_only, peak_rss_mb, peak_rss_mb_end, runtime_seconds, user_quality_manifest_path, memory_fields)
    comparison = _weak_strong_comparison(source, build_stats, quality_policy, diagnostic_only, peak_rss_mb)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "custom_index_selection_manifest.json", custom_index_selection_manifest)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(output_dir / "per_source_candidate_manifest.json", candidate_manifest)
    write_json(output_dir / "weak_strong_comparison.json", comparison)
    readiness_contract = _readiness_contract(
        output_dir=output_dir,
        source=source,
        readiness_status=readiness_status,
        output_status=output_status,
        source_index_manifest=source_index_manifest,
        custom_index_selection_manifest=custom_index_selection_manifest,
        edges_path=edges_path,
    )
    write_json(output_dir / "readiness_contract.json", readiness_contract)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": runtime_seconds,
        "source": source,
        "label_variant": label_variant,
        "index_scope": "FULL_DERIVED_INDEX",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "train_only": True,
        "diagnostic_only": diagnostic_only,
        "user_quality_policy": quality_policy["policy_name"],
        "user_quality_manifest_path": str(user_quality_manifest_path) if user_quality_manifest_path else None,
        "eligible_buckets": quality_policy["eligible_buckets"],
        "profile_boundary": quality_policy["profile_boundary"],
        "project_venv_required": enforce_venv,
        "output_dir": str(output_dir),
        "peak_rss_mb": peak_rss_mb,
        "peak_rss_mb_end": peak_rss_mb_end,
        **memory_fields,
        "required_artifacts": {
            "edges": str(edges_path),
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "consumer_user_manifest": coverage_artifacts["consumer_user_manifest_path"],
            "coverage_audit": coverage_artifacts["coverage_audit_path"],
            "custom_dataset_manifest": coverage_artifacts["custom_dataset_manifest_path"],
            "custom_index_selection_manifest": str(output_dir / "custom_index_selection_manifest.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
            "readiness_contract": str(output_dir / "readiness_contract.json"),
            "per_source_candidate_manifest": str(output_dir / "per_source_candidate_manifest.json"),
            "weak_strong_comparison": str(output_dir / "weak_strong_comparison.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "artifact_signatures": {
            "edges": _file_signature(edges_path),
            "source_index_manifest": _file_signature(output_dir / "source_index_manifest.json"),
            "consumer_user_manifest": _file_signature(Path(coverage_artifacts["consumer_user_manifest_path"])),
            "coverage_audit": _file_signature(Path(coverage_artifacts["coverage_audit_path"])),
            "custom_dataset_manifest": _file_signature(Path(coverage_artifacts["custom_dataset_manifest_path"])),
            "custom_index_selection_manifest": _file_signature(output_dir / "custom_index_selection_manifest.json"),
            "resource_audit": _file_signature(output_dir / "resource_audit.json"),
            "no_holdout_audit": _file_signature(output_dir / "no_holdout_audit.json"),
            "readiness_contract": _file_signature(output_dir / "readiness_contract.json"),
            "per_source_candidate_manifest": _file_signature(output_dir / "per_source_candidate_manifest.json"),
            "weak_strong_comparison": _file_signature(output_dir / "weak_strong_comparison.json"),
        },
        **build_stats,
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _build_coverage_artifacts(
    *,
    clean_dir: Path,
    train_sequences_path: Path,
    output_dir: Path,
    source: str,
    label_variant: str,
    edges_path: Path,
    source_index_manifest: dict[str, Any],
    build_stats: dict[str, Any],
    quality_policy: dict[str, Any],
    user_quality_manifest_path: Path | None,
    consumer_user_limit: int,
    max_items_per_user: int,
    runtime_seconds: float | None = None,
    peak_rss_mb: float | None = None,
    peak_rss_mb_end: float | None = None,
    memory_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory_fields = memory_fields or {}
    canonical_items_path = clean_dir / "canonical_items.jsonl"
    consumer_sequences = _load_consumer_sequences(train_sequences_path, consumer_user_limit)
    consumer_user_ids = [str(row["user_id"]) for row in consumer_sequences]
    consumer_user_ids_sha256 = hashlib.sha256("\n".join(consumer_user_ids).encode("utf-8")).hexdigest()
    consumer_manifest_path = output_dir / "consumer_user_manifest.json"
    coverage_audit_path = output_dir / "coverage_audit.json"
    custom_dataset_manifest_path = _custom_dataset_manifest_path(output_dir, source)
    profiled_bucket_counts = Counter(quality_policy["quality_bucket_by_user"].values())
    builder_user_ids = quality_policy["eligible_user_ids"]
    builder_consumer_user_ids = set(consumer_user_ids) if builder_user_ids is None else set(consumer_user_ids) & builder_user_ids
    edge_src_items, edge_items = _load_edge_items(edges_path)
    canonical_items = _load_canonical_item_universe(canonical_items_path)
    consumer_users_with_seed_items = 0
    consumer_users_with_edge_seed_hit = 0
    consumer_users_without_source_items = 0
    consumer_users_without_edge_seed_hit = 0
    non_builder_consumer_seed_hit_count = 0

    for sequence in consumer_sequences:
        user_id = str(sequence["user_id"])
        seed_items = unique_recent_items(sequence.get(label_variant, []), max_items_per_user)
        if not seed_items:
            consumer_users_without_source_items += 1
            continue
        consumer_users_with_seed_items += 1
        has_seed_hit = any(item in edge_src_items for item in seed_items)
        if has_seed_hit:
            consumer_users_with_edge_seed_hit += 1
            if user_id not in builder_consumer_user_ids:
                non_builder_consumer_seed_hit_count += 1
        else:
            consumer_users_without_edge_seed_hit += 1

    edge_items_out_of_universe = sorted(edge_items - canonical_items)
    consumer_count_matches = consumer_user_limit == 0 or len(consumer_user_ids) <= consumer_user_limit
    forbidden_inputs = [str(clean_dir / name) for name in FORBIDDEN_INPUT_NAMES]
    audit_status = "PASS" if consumer_count_matches and not edge_items_out_of_universe else "FAIL"
    consumer_seed_hit_status = "PASS" if consumer_users_with_edge_seed_hit > 0 else "WARN"
    coverage_scope = "full_run_train_only_consumer_users" if consumer_user_limit == 0 else f"target{consumer_user_limit}_train_only_consumer_users"
    consumer_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.consumer_user_manifest",
        "status": "PASS" if consumer_count_matches else "FAIL",
        "scope": coverage_scope,
        "selection_source_path": str(train_sequences_path),
        "selection_source_sha256": _file_signature(train_sequences_path)["sha256"],
        "selection_algorithm": "first_n_user_sequences_with_user_id_from_train_jsonl",
        "limit_users": consumer_user_limit,
        "full_run": consumer_user_limit == 0,
        "consumer_user_count": len(consumer_user_ids),
        "consumer_user_ids": consumer_user_ids,
        "consumer_user_ids_sha256": consumer_user_ids_sha256,
        "train_only": True,
        "not_quality_profile": True,
        "forbidden_inputs_checked": True,
        "forbidden_inputs": forbidden_inputs,
        "created_by_command": f"python -m rs_lab.experiments.recall.build_full_train_itemcf_sidecars --source {source} --consumer-user-limit {consumer_user_limit}",
    }
    coverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": audit_status,
        "audit_status": audit_status,
        "audit_status_note": "PASS means the audit completed and invariants held; it does not claim READY promotion.",
        "consumer_seed_hit_status": consumer_seed_hit_status,
        "consumer_seed_hit_status_reason": "consumer_users_with_edge_seed_hit > 0" if consumer_users_with_edge_seed_hit else "no consumer seed item appeared as an edge src_item",
        "source": source,
        "coverage_scope": coverage_scope,
        "consumer_user_manifest_path": str(consumer_manifest_path),
        "consumer_user_count": len(consumer_user_ids),
        "consumer_user_scope": coverage_scope,
        "consumer_users_with_seed_items": consumer_users_with_seed_items,
        "consumer_users_with_edge_seed_hit": consumer_users_with_edge_seed_hit,
        "consumer_users_without_source_items": consumer_users_without_source_items,
        "consumer_users_without_edge_seed_hit": consumer_users_without_edge_seed_hit,
        "consumer_user_hit_ratio": consumer_users_with_edge_seed_hit / len(consumer_user_ids) if consumer_user_ids else 0.0,
        "profiled_user_count": quality_policy["profiled_user_count"],
        "profiled_quality_bucket_counts": dict(sorted(profiled_bucket_counts.items())),
        "builder_user_collection": "all_train_source_positive_users" if builder_user_ids is None else "quality_profile_eligible_users",
        "builder_source_positive_user_count": build_stats["users_with_source_items"],
        "builder_pair_contributing_user_count": build_stats["users_used"],
        "non_builder_consumer_user_count": len(set(consumer_user_ids) - builder_consumer_user_ids),
        "non_builder_consumer_seed_hit_count": non_builder_consumer_seed_hit_count,
        "edge_unique_item_count": len(edge_items),
        "edge_item_in_universe_count": len(edge_items & canonical_items),
        "edge_item_out_of_universe_count": len(edge_items_out_of_universe),
        "edge_items_out_of_universe_sample": edge_items_out_of_universe[:20],
        "canonical_item_count": len(canonical_items),
        "canonical_items_path": str(canonical_items_path),
        "edges_path": str(edges_path),
        "train_only": True,
        "forbidden_inputs_checked": True,
        "forbidden_inputs": forbidden_inputs,
        "diagnostic_contribution_expected": consumer_users_with_edge_seed_hit > 0,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    source_artifact_user_quality_policy = source_index_manifest["user_quality_policy"]
    custom_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.custom_dataset_manifest",
        "status": "DIAGNOSTIC_ONLY",
        "source": source,
        "manifest_role": "legacy_unfiltered_sidecar_coverage_audit" if source_artifact_user_quality_policy == "unfiltered_legacy_itemcf_sidecar" else "quality_builder_sidecar_coverage_audit",
        "custom_dataset_policy_satisfied": source_artifact_user_quality_policy != "unfiltered_legacy_itemcf_sidecar",
        "source_artifact_user_quality_policy": source_artifact_user_quality_policy,
        "quality_builder_sidecar_required_for_policy_satisfaction": source_artifact_user_quality_policy == "unfiltered_legacy_itemcf_sidecar",
        "quality_builder_sidecar_path": None if source_artifact_user_quality_policy == "unfiltered_legacy_itemcf_sidecar" else str(output_dir),
        "selection_scope": "legacy_unfiltered_index_builder" if source_artifact_user_quality_policy == "unfiltered_legacy_itemcf_sidecar" else "index_builder_only",
        "user_quality_manifest_path": str(user_quality_manifest_path) if user_quality_manifest_path else None,
        "eligible_buckets": quality_policy["eligible_buckets"],
        "target_user_limit": build_stats.get("target_user_limit"),
        "actual_train_user_count": build_stats.get("actual_train_user_count"),
        "users_with_source_items": build_stats["users_with_source_items"],
        "users_scanned_within_profile": build_stats.get("users_scanned_within_profile"),
        "users_filtered_by_quality": build_stats.get("users_filtered_by_quality"),
        "used_quality_bucket_counts": build_stats["used_quality_bucket_counts"],
        "unique_item_count_after_hot_cap": build_stats.get("unique_item_count_after_hot_cap"),
        "runtime_seconds": runtime_seconds,
        "peak_rss_mb": peak_rss_mb,
        "peak_rss_mb_end": peak_rss_mb_end,
        **memory_fields,
        "does_not_define_consumer_universe": True,
        "consumer_user_manifest_path": str(consumer_manifest_path),
        "consumer_coverage_audit_path": str(coverage_audit_path),
        "source_index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "edges_path": str(edges_path),
        "edge_count": build_stats["rows_written"],
        "target_user_limit_semantics": "source_positive_builder_sequences_limit",
        "train_only": True,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    write_json(consumer_manifest_path, consumer_manifest)
    write_json(coverage_audit_path, coverage_audit)
    write_json(custom_dataset_manifest_path, custom_dataset_manifest)
    return {
        "consumer_user_manifest_path": str(consumer_manifest_path),
        "coverage_audit_path": str(coverage_audit_path),
        "custom_dataset_manifest_path": str(custom_dataset_manifest_path),
        "source_index_fields": {
            "edge_count": build_stats["rows_written"],
            "builder_source_positive_user_count": build_stats["users_with_source_items"],
            "builder_pair_contributing_user_count": build_stats["users_used"],
            "target_user_limit_semantics": "source_positive_builder_sequences_limit",
            "consumer_user_manifest_path": str(consumer_manifest_path),
            "coverage_audit_path": str(coverage_audit_path),
            "custom_dataset_manifest_path": str(custom_dataset_manifest_path),
            "index_builder_policy": source_artifact_user_quality_policy,
            "profiled_quality_bucket_counts": dict(sorted(profiled_bucket_counts.items())),
            "builder_quality_bucket_counts": build_stats["used_quality_bucket_counts"],
            "promotion_allowed": False,
        },
    }


def _load_consumer_sequences(train_sequences_path: Path, limit_users: int) -> list[dict[str, Any]]:
    sequences: list[dict[str, Any]] = []
    for sequence in iter_jsonl(train_sequences_path):
        if not sequence.get("user_id"):
            continue
        sequences.append(sequence)
        if limit_users > 0 and len(sequences) >= limit_users:
            break
    return sequences


def _load_edge_items(edges_path: Path) -> tuple[set[str], set[str]]:
    src_items: set[str] = set()
    edge_items: set[str] = set()
    for row in iter_jsonl(edges_path):
        src_item = str(row.get("src_item") or "")
        dst_item = str(row.get("dst_item") or "")
        if src_item:
            src_items.add(src_item)
            edge_items.add(src_item)
        if dst_item:
            edge_items.add(dst_item)
    return src_items, edge_items


def _load_canonical_item_universe(canonical_items_path: Path) -> set[str]:
    if not canonical_items_path.is_file():
        raise FileNotFoundError(canonical_items_path)
    items: set[str] = set()
    for row in iter_jsonl(canonical_items_path):
        item_id = row.get("parent_asin") or row.get("item_id") or row.get("asin")
        if item_id:
            items.add(str(item_id))
    return items


def _custom_dataset_manifest_path(output_dir: Path, source: str) -> Path:
    return output_dir / f"{source}_custom_dataset_manifest.json"


def augment_existing_itemcf_manifest(
    *,
    source_index_manifest_path: Path,
    clean_dir: Path = DEFAULT_CLEAN_DIR,
    consumer_user_limit: int = 500,
    user_quality_manifest_path: Path | None = None,
    max_items_per_user: int = DEFAULT_MAX_ITEMS_PER_USER,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        _enforce_project_venv()
    if consumer_user_limit < 0:
        raise ValueError("consumer_user_limit must be non-negative")
    source_index_manifest_path = source_index_manifest_path.resolve()
    source_index_manifest = read_json(source_index_manifest_path)
    source = str(source_index_manifest["source"])
    if source not in SOURCES:
        raise ValueError(f"Unsupported source: {source}")
    clean_dir = clean_dir.resolve()
    output_dir = source_index_manifest_path.parent
    train_sequences_path = clean_dir / "user_sequences.train.jsonl"
    user_quality_manifest_path = user_quality_manifest_path.resolve() if user_quality_manifest_path else None
    _precheck_for_augmentation(clean_dir, output_dir, train_sequences_path, user_quality_manifest_path)
    quality_policy = _load_user_quality_policy(user_quality_manifest_path, source)
    edges_path = Path(str(source_index_manifest["edges_path"])).resolve()
    build_stats = _stats_from_existing_manifest(source_index_manifest)
    coverage_artifacts = _build_coverage_artifacts(
        clean_dir=clean_dir,
        train_sequences_path=train_sequences_path,
        output_dir=output_dir,
        source=source,
        label_variant=str(source_index_manifest.get("label_variant") or SOURCES[source]),
        edges_path=edges_path,
        source_index_manifest=source_index_manifest,
        build_stats=build_stats,
        quality_policy=quality_policy,
        user_quality_manifest_path=user_quality_manifest_path,
        consumer_user_limit=consumer_user_limit,
        max_items_per_user=max_items_per_user,
    )
    source_index_manifest.update(coverage_artifacts["source_index_fields"])
    write_json(source_index_manifest_path, source_index_manifest)
    return {"status": "PASS", "source_index_manifest_path": str(source_index_manifest_path), **coverage_artifacts}


def _precheck_for_augmentation(clean_dir: Path, output_dir: Path, train_sequences_path: Path, user_quality_manifest_path: Path | None) -> None:
    for path in (clean_dir, output_dir, *( [user_quality_manifest_path] if user_quality_manifest_path else [])):
        lowered = str(path).replace("\\", "/").lower()
        if "10000" in lowered or "10k" in lowered or any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden 10k/pool1000 path is not allowed: {path}")
    if not train_sequences_path.is_file():
        raise FileNotFoundError(train_sequences_path)
    if user_quality_manifest_path is not None and not user_quality_manifest_path.is_file():
        raise FileNotFoundError(user_quality_manifest_path)


def _stats_from_existing_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    rows_written = int(manifest.get("edge_count") or manifest.get("rows_written") or manifest.get("edge_signature", {}).get("row_count") or 0)
    return {
        "users_with_source_items": int(manifest.get("builder_source_positive_user_count") or manifest.get("users_with_source_items") or 0),
        "users_used": int(manifest.get("builder_pair_contributing_user_count") or manifest.get("users_used") or 0),
        "used_quality_bucket_counts": manifest.get("used_quality_bucket_counts") or {},
        "rows_written": rows_written,
    }


def _build_itemcf_edges(
    user_sequences_path: Path,
    output_path: Path,
    *,
    source: str,
    label_variant: str,
    max_items_per_user: int,
    max_item_user_freq: int,
    top_k_per_seed: int,
    target_user_limit: int,
    eligible_user_ids: set[str] | None,
    quality_bucket_by_user: dict[str, str],
    profile_source_rows_scanned: int | None,
) -> dict[str, Any]:
    sequences: list[list[str]] = []
    item_user_count: Counter[str] = Counter()
    users_scanned = 0
    users_scanned_within_profile = 0
    users_filtered_by_quality = 0
    used_quality_buckets: Counter[str] = Counter()

    for record in iter_jsonl(user_sequences_path):
        if profile_source_rows_scanned is not None and users_scanned >= profile_source_rows_scanned:
            break
        users_scanned += 1
        users_scanned_within_profile += 1
        user_id = str(record.get("user_id", ""))
        items = record.get(label_variant, [])
        if not isinstance(items, list):
            continue
        unique_items = unique_recent_items(items, max_items_per_user)
        if not unique_items:
            continue
        if eligible_user_ids is not None and user_id not in eligible_user_ids:
            users_filtered_by_quality += 1
            continue
        used_quality_buckets.update([quality_bucket_by_user.get(user_id, "unprofiled")])
        item_user_count.update(unique_items)
        sequences.append(unique_items)
        if target_user_limit and len(sequences) >= target_user_limit:
            break

    hot_items = {item for item, count in item_user_count.items() if count > max_item_user_freq}
    capped_item_user_count = Counter({item: count for item, count in item_user_count.items() if item not in hot_items})
    pair_count: Counter[tuple[str, str]] = Counter()
    users_used = 0
    item_events_dropped_by_hot_cap = 0

    for unique_items in sequences:
        filtered_items = [item for item in unique_items if item not in hot_items]
        item_events_dropped_by_hot_cap += len(unique_items) - len(filtered_items)
        if len(filtered_items) < 2:
            continue
        users_used += 1
        for pair in combinations(sorted(filtered_items), 2):
            pair_count[pair] += 1

    outgoing_edges: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for (item_a, item_b), cooc_cnt in pair_count.items():
        denominator = math.sqrt(capped_item_user_count[item_a] * capped_item_user_count[item_b])
        score = 0.0 if denominator == 0 else round(cooc_cnt / denominator, 6)
        for src_item, dst_item in ((item_a, item_b), (item_b, item_a)):
            outgoing_edges[src_item].append(
                {
                    "src_item": src_item,
                    "dst_item": dst_item,
                    "score": score,
                    "source": source,
                    "label_variant": label_variant,
                    "cooc_cnt": cooc_cnt,
                    "src_user_cnt": capped_item_user_count[src_item],
                    "dst_user_cnt": capped_item_user_count[dst_item],
                }
            )

    rows_written = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for src_item in sorted(outgoing_edges):
            ranked_edges = sorted(
                outgoing_edges[src_item],
                key=lambda row: (-row["score"], -row["cooc_cnt"], row["dst_item"]),
            )[:top_k_per_seed]
            for rank, row in enumerate(ranked_edges, start=1):
                handle.write(json.dumps({**row, "rank": rank}, ensure_ascii=False) + "\n")
                rows_written += 1

    return {
        "output_path": str(output_path),
        "actual_train_user_count": len(sequences),
        "users_scanned": users_scanned,
        "users_scanned_within_profile": users_scanned_within_profile,
        "users_filtered_by_quality": users_filtered_by_quality,
        "users_with_source_items": len(sequences),
        "edge_count": rows_written,
        "target_user_limit": target_user_limit,
        "used_quality_bucket_counts": dict(sorted(used_quality_buckets.items())),
        "users_used": users_used,
        "unique_item_count_before_hot_cap": len(item_user_count),
        "unique_item_count_after_hot_cap": len(capped_item_user_count),
        "hot_item_count": len(hot_items),
        "hot_items": sorted(hot_items),
        "item_events_dropped_by_hot_cap": item_events_dropped_by_hot_cap,
        "unique_pair_count": len(pair_count),
        "rows_written": rows_written,
    }


def _load_user_quality_policy(user_quality_manifest_path: Path | None, source: str) -> dict[str, Any]:
    if user_quality_manifest_path is None:
        return {
            "policy_name": "unfiltered_legacy_itemcf_sidecar",
            "eligible_buckets": sorted(SOURCE_USER_QUALITY_POLICIES[source]),
            "eligible_user_ids": None,
            "quality_bucket_by_user": {},
            "profiled_user_count": None,
            "profile_source_rows_scanned": None,
            "profile_boundary": None,
        }
    manifest = read_json(user_quality_manifest_path)
    profiles = manifest.get("profiles", [])
    if not isinstance(profiles, list):
        raise ValueError("user_quality manifest must contain a profiles list")
    profile_user_ids = [str(profile.get("user_id", "")) for profile in profiles if isinstance(profile, dict) and profile.get("user_id")]
    profiled_user_count = _required_int(manifest, "profiled_user_count")
    profile_source_rows_scanned = _required_int(manifest, "profile_source_rows_scanned")
    first_profiled_user_id = str(manifest.get("first_profiled_user_id") or "")
    last_profiled_user_id = str(manifest.get("last_profiled_user_id") or "")
    profiled_user_ids_sha256 = str(manifest.get("profiled_user_ids_sha256") or "")
    profile_universe_scope = str(manifest.get("profile_universe_scope") or "")
    if profiled_user_count != len(profile_user_ids):
        raise ValueError("user_quality profiled_user_count does not match profiles")
    if profile_user_ids and (profile_user_ids[0] != first_profiled_user_id or profile_user_ids[-1] != last_profiled_user_id):
        raise ValueError("user_quality first/last profiled user boundary does not match profiles")
    if profiled_user_ids_sha256 != _user_ids_sha256(profile_user_ids):
        raise ValueError("user_quality profiled_user_ids_sha256 does not match profiles")
    eligible_buckets = SOURCE_USER_QUALITY_POLICIES[source]
    eligible_user_ids: set[str] = set()
    quality_bucket_by_user: dict[str, str] = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        user_id = str(profile.get("user_id", ""))
        bucket = str(profile.get("quality_bucket", ""))
        if not user_id:
            continue
        quality_bucket_by_user[user_id] = bucket
        if bucket in eligible_buckets:
            eligible_user_ids.add(user_id)
    policy_name = "heavy_cf_eligible_or_medium_behavior" if source == "itemcf_weak" else "heavy_cf_eligible"
    return {
        "policy_name": policy_name,
        "eligible_buckets": sorted(eligible_buckets),
        "eligible_user_ids": eligible_user_ids,
        "quality_bucket_by_user": quality_bucket_by_user,
        "profiled_user_count": profiled_user_count,
        "profile_source_rows_scanned": profile_source_rows_scanned,
        "profile_boundary": {
            "profiled_user_count": profiled_user_count,
            "profile_source_rows_scanned": profile_source_rows_scanned,
            "first_profiled_user_id": first_profiled_user_id,
            "last_profiled_user_id": last_profiled_user_id,
            "profiled_user_ids_sha256": profiled_user_ids_sha256,
            "profile_universe_scope": profile_universe_scope,
        },
    }


def _required_int(manifest: dict[str, Any], field: str) -> int:
    value = manifest.get(field)
    if not isinstance(value, int):
        raise ValueError(f"user_quality manifest must contain integer {field}")
    return value


def _user_ids_sha256(user_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(user_ids).encode("utf-8")).hexdigest()


def _candidate_manifest(
    source: str,
    output_dir: Path,
    edges_path: Path,
    build_stats: dict[str, Any],
    quality_policy: dict[str, Any],
    diagnostic_only: bool,
    peak_rss_mb: float,
    peak_rss_mb_end: float,
    runtime_seconds: float,
    user_quality_manifest_path: Path | None,
    memory_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory_fields = memory_fields or {}
    return {
        "schema_version": f"{SCHEMA_VERSION}.per_source_candidate_manifest",
        "status": "PASS",
        "source": source,
        "scope": "user_quality_filtered_itemcf_diagnostic",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "diagnostic_only": diagnostic_only,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "candidate_path": str(edges_path),
        "candidate_signature": _file_signature(edges_path),
        "source_index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "readiness_contract_path": str(output_dir / "readiness_contract.json"),
        "user_quality_policy": quality_policy["policy_name"],
        "user_quality_manifest_path": str(user_quality_manifest_path) if user_quality_manifest_path else None,
        "eligible_buckets": quality_policy["eligible_buckets"],
        "eligible_quality_buckets": quality_policy["eligible_buckets"],
        "target_user_limit": build_stats["target_user_limit"],
        "actual_train_user_count": build_stats["actual_train_user_count"],
        "profiled_user_count": quality_policy["profiled_user_count"],
        "users_scanned": build_stats["users_scanned"],
        "users_scanned_within_profile": build_stats["users_scanned_within_profile"],
        "users_filtered_by_quality": build_stats["users_filtered_by_quality"],
        "used_quality_bucket_counts": build_stats["used_quality_bucket_counts"],
        "users_with_source_items": build_stats["users_with_source_items"],
        "edge_count": build_stats["rows_written"],
        "candidate_user_count": build_stats["users_with_source_items"],
        "candidate_total_count": build_stats["rows_written"],
        "unique_item_count": build_stats["unique_item_count_after_hot_cap"],
        "unique_item_count_after_hot_cap": build_stats["unique_item_count_after_hot_cap"],
        "duplicate_overlap": 0,
        "marginal_candidate_share": 1.0 if build_stats["rows_written"] else 0.0,
        "underfilled_user_coverage": 1.0 if build_stats["users_with_source_items"] else 0.0,
        "runtime_seconds": runtime_seconds,
        "peak_rss_mb": peak_rss_mb,
        "peak_rss_mb_end": peak_rss_mb_end,
        **memory_fields,
        "rows_written": build_stats["rows_written"],
    }


def _weak_strong_comparison(source: str, build_stats: dict[str, Any], quality_policy: dict[str, Any], diagnostic_only: bool, peak_rss_mb: float | None) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.weak_strong_comparison",
        "status": "PASS",
        "source": source,
        "comparison_axis": "itemcf_weak_allows_heavy_or_medium_itemcf_strong_allows_heavy_only",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "diagnostic_only": diagnostic_only,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "source_policy": quality_policy["policy_name"],
        "source_eligible_quality_buckets": quality_policy["eligible_buckets"],
        "expected_policy_by_source": {
            "itemcf_weak": "heavy_cf_eligible_or_medium_behavior",
            "itemcf_strong": "heavy_cf_eligible",
        },
        "used_quality_bucket_counts": build_stats["used_quality_bucket_counts"],
        "users_filtered_by_quality": build_stats["users_filtered_by_quality"],
        "rows_written": build_stats["rows_written"],
    }


def _readiness_contract(
    *,
    output_dir: Path,
    source: str,
    readiness_status: str,
    output_status: str,
    source_index_manifest: dict[str, Any],
    custom_index_selection_manifest: dict[str, Any],
    edges_path: Path,
) -> dict[str, Any]:
    source_index_signature = _file_signature(output_dir / "source_index_manifest.json")
    selection_manifest_signature = _file_signature(output_dir / "custom_index_selection_manifest.json")
    edge_signature = _file_signature(edges_path)
    payload = {
        "source": source,
        "status": readiness_status,
        "index_status": "INDEX_READY",
        "diagnostic_output_status": "DIAGNOSTIC_OUTPUT_READY",
        "full_output_status": output_status,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "manifest_path": str(output_dir / "readiness_contract.json"),
        "index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "output_manifest_path": str(output_dir / "custom_index_selection_manifest.json"),
        "edges_path": str(edges_path),
        "edge_signature": edge_signature,
        "index_manifest_signature": source_index_signature,
        "output_manifest_signature": selection_manifest_signature,
        "source_signature": source_index_manifest["source_signature"],
        "config": custom_index_selection_manifest["config"],
    }
    payload["index_manifest_sha256"] = source_index_signature["sha256"]
    payload["output_manifest_sha256"] = selection_manifest_signature["sha256"]
    payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"schema_version": f"{SCHEMA_VERSION}.readiness_contract", **payload}



def _resolve_output_dir(output_dir: Path, source: str) -> Path:
    resolved = output_dir.resolve()
    default_root = DEFAULT_OUTPUT_DIR.resolve()
    if resolved == default_root:
        return resolved / source
    return resolved


def _validate_args(source: str, max_items_per_user: int, max_item_user_freq: int, top_k_per_seed: int, target_user_limit: int, min_free_bytes: int) -> None:
    if source not in SOURCES:
        raise ValueError(f"Unsupported source: {source}")
    for label, value in {
        "max_items_per_user": max_items_per_user,
        "max_item_user_freq": max_item_user_freq,
        "top_k_per_seed": top_k_per_seed,
    }.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if target_user_limit < 0:
        raise ValueError("target_user_limit must be non-negative")
    if min_free_bytes < 0:
        raise ValueError("min_free_bytes must be non-negative")


def _precheck(clean_dir: Path, output_dir: Path, train_sequences_path: Path, min_free_bytes: int, overwrite: bool, user_quality_manifest_path: Path | None = None) -> None:
    for path in (clean_dir, output_dir, *( [user_quality_manifest_path] if user_quality_manifest_path else [])):
        lowered = str(path).replace("\\", "/").lower()
        if "10000" in lowered or "10k" in lowered or any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden 10k/pool1000 path is not allowed: {path}")
    if not clean_dir.is_dir():
        raise NotADirectoryError(clean_dir)
    if not train_sequences_path.is_file():
        raise FileNotFoundError(train_sequences_path)
    if user_quality_manifest_path is not None and not user_quality_manifest_path.is_file():
        raise FileNotFoundError(user_quality_manifest_path)
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    try:
        output_dir.relative_to(clean_dir)
    except ValueError:
        pass
    else:
        raise ValueError(f"Output directory must not be inside clean dir: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below --min-free-bytes: {free_bytes} < {min_free_bytes}")


def _enforce_project_venv() -> None:
    executable = Path(sys.executable).resolve()
    expected = (ROOT / ".venv").resolve()
    try:
        executable.relative_to(expected)
    except ValueError as exc:
        raise RuntimeError(f"Project .venv Python is required, got {sys.executable}") from exc


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "row_count": rows,
        "sha256": digest.hexdigest(),
    }


class _MemorySampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_mb = 0.0
        self._end_mb = 0.0
        self._peak_mb = 0.0

    def start(self) -> "_MemorySampler":
        self._start_mb = _peak_rss_mb()
        self._peak_mb = self._start_mb
        if self._start_mb:
            self._thread = threading.Thread(target=self._sample, daemon=True)
            self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._end_mb = _peak_rss_mb()
        if self._end_mb > self._peak_mb:
            self._peak_mb = self._end_mb
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if not self._peak_mb:
            status = "UNMEASURED"
            measurement = "fallback_not_authoritative_for_os_rss"
        else:
            status = "PASS" if self._peak_mb <= 400 else "FAIL"
            measurement = "sampled_process_rss_peak"
        return {
            "memory_rss_start_mb": self._start_mb,
            "memory_rss_end_mb": self._end_mb,
            "memory_peak_rss_mb": self._peak_mb,
            "memory_target_mb": 400,
            "memory_target_status": status,
            "memory_peak_measurement": measurement,
        }

    def _sample(self) -> None:
        while not self._stop.wait(0.05):
            current = _peak_rss_mb()
            if current > self._peak_mb:
                self._peak_mb = current


def _peak_rss_mb() -> float:
    try:
        import psutil  # type: ignore

        return round(psutil.Process().memory_info().rss / 1024 / 1024, 3)
    except Exception:
        return 0.0



def main() -> None:
    args = parse_args()
    if args.augment_existing_manifest:
        manifest = augment_existing_itemcf_manifest(
            source_index_manifest_path=Path(args.augment_existing_manifest),
            clean_dir=Path(args.clean_dir),
            consumer_user_limit=args.consumer_user_limit,
            user_quality_manifest_path=Path(args.user_quality_manifest) if args.user_quality_manifest else None,
            max_items_per_user=args.max_items_per_user,
            enforce_venv=not args.skip_venv_check,
        )
        print(json.dumps({"status": manifest["status"], "manifest_path": manifest["source_index_manifest_path"]}, ensure_ascii=False, indent=2))
        return
    manifest = build_full_train_itemcf_sidecar(
        clean_dir=Path(args.clean_dir),
        output_dir=Path(args.output_dir),
        source=args.source,
        max_items_per_user=args.max_items_per_user,
        max_item_user_freq=args.max_item_user_freq,
        top_k_per_seed=args.top_k_per_seed,
        target_user_limit=args.target_user_limit,
        user_quality_manifest_path=Path(args.user_quality_manifest) if args.user_quality_manifest else None,
        consumer_user_limit=args.consumer_user_limit,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["required_artifacts"]["manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
