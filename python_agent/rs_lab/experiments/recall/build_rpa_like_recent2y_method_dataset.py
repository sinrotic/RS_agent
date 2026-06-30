from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "rpa_like_recent2y_method_dataset_v1"
ROW_SCHEMA_VERSION = "rpa_like_eligible_sequence_v1"
SOURCE_METHOD = "rpa_like_recursive_cf"
SOURCE_VARIANT = "recursive_cf_lite_zhang_pu_2007_dataset_v1"
SOURCE_STATUS = "DIAGNOSTIC_ONLY"
DEFAULT_DATA_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_datasets" / "recent_2y" / "rpa_like_recursive_cf" / "v1"
DEFAULT_MAX_RSS_MB = 4096
MAX_ALLOWED_RSS_MB = 5120
DEFAULT_SMOKE_USER_LIMIT = 5000
DEFAULT_MAX_ITEMS_PER_USER = 80
FORBIDDEN_PATH_TOKENS = {"holdout", "valid", "test", "lopo", "oracle", "eval_label", "clean_10000", "pool1000"}
FORBIDDEN_INPUT_NAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_SWITCHES = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
    "ready_source_artifact": False,
    "label_backflow_allowed": False,
}
DISALLOWED_ITEM_BUCKETS = {"blocked", "invalid", "not_allowed", "unsafe", "missing_metadata"}
ALLOWED_SCALE_TIERS = {"smoke", "formal"}
SPARSE_BUCKET = "sparse_seq_len_eq1"
MEDIUM_BUCKET = "medium_like_seq_len_2_4"


@dataclass(frozen=True)
class RPALikeRecent2YDatasetConfig:
    data_root: Path = DEFAULT_DATA_ROOT
    output_dir: Path = DEFAULT_OUTPUT_ROOT / "smoke"
    run_id: str = "rpa_like_recent2y_v1_smoke"
    scale_tier: str = "smoke"
    max_rss_mb: int = DEFAULT_MAX_RSS_MB
    smoke_user_limit: int = DEFAULT_SMOKE_USER_LIMIT
    formal_max_users: int = 0
    max_items_per_user: int = DEFAULT_MAX_ITEMS_PER_USER
    recursive_depth_cap: int = 2
    overwrite: bool = False
    enforce_venv: bool = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build train-only RPA-like recent-2y smoke/formal method datasets.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--scale-tier", choices=sorted(ALLOWED_SCALE_TIERS), default="smoke")
    parser.add_argument("--max-rss-mb", type=int, default=DEFAULT_MAX_RSS_MB)
    parser.add_argument("--smoke-user-limit", type=int, default=DEFAULT_SMOKE_USER_LIMIT)
    parser.add_argument("--formal-max-users", type=int, default=0)
    parser.add_argument("--max-items-per-user", type=int, default=DEFAULT_MAX_ITEMS_PER_USER)
    parser.add_argument("--recursive-depth-cap", type=int, default=2)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / args.scale_tier)
    run_id = args.run_id or f"rpa_like_recent2y_v1_{args.scale_tier}"
    manifest = build_rpa_like_recent2y_method_dataset(
        RPALikeRecent2YDatasetConfig(
            data_root=args.data_root,
            output_dir=output_dir,
            run_id=run_id,
            scale_tier=args.scale_tier,
            max_rss_mb=args.max_rss_mb,
            smoke_user_limit=args.smoke_user_limit,
            formal_max_users=args.formal_max_users,
            max_items_per_user=args.max_items_per_user,
            recursive_depth_cap=args.recursive_depth_cap,
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["outputs"]["method_dataset_manifest"]}, ensure_ascii=False, indent=2))


def build_rpa_like_recent2y_method_dataset(config: RPALikeRecent2YDatasetConfig) -> dict[str, Any]:
    started = perf_counter()
    if config.enforce_venv:
        enforce_project_venv(ROOT)
    _validate_config(config)

    data_root = config.data_root.resolve()
    output_dir = config.output_dir.resolve()
    paths = _input_paths(data_root)
    _validate_allowed_inputs(paths)
    _prepare_output_dir(output_dir, overwrite=config.overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)

    memory_samples: list[dict[str, Any]] = []
    _sample_memory(memory_samples, "start")
    _enforce_memory_guard(memory_samples, config.max_rss_mb)

    recent_manifest = read_json(paths["recent_2y_manifest"])
    governance_manifest = read_json(paths["train_governance_manifest"])
    user_quality = _load_user_quality(paths["user_quality_profile"])
    _sample_memory(memory_samples, "after_load_user_quality")
    _enforce_memory_guard(memory_samples, config.max_rss_mb)

    item_quality = _load_item_quality(paths["item_quality_profile"])
    _sample_memory(memory_samples, "after_load_item_quality")
    _enforce_memory_guard(memory_samples, config.max_rss_mb)

    item_frequency = _load_item_frequency(paths["item_frequency_train"])
    _sample_memory(memory_samples, "after_load_item_frequency")
    _enforce_memory_guard(memory_samples, config.max_rss_mb)

    rows_path = output_dir / "method_dataset_rows.jsonl"
    stats = Counter()
    bucket_counts: Counter[str] = Counter()
    unique_items: set[str] = set()
    seed_lengths: list[int] = []
    if config.scale_tier == "smoke":
        selected_rows, collect_audit = _collect_smoke_rows(
            paths["user_sequences_train"],
            user_quality=user_quality,
            item_quality=item_quality,
            item_frequency=item_frequency,
            config=config,
            stats=stats,
        )
        selected_rows.sort(key=lambda row: (row["target_bucket"], row["user_id"]))
        with rows_path.open("w", encoding="utf-8") as handle:
            for row in selected_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                bucket_counts[row["target_bucket"]] += 1
                unique_items.update(row["seed_item_sequence"])
                seed_lengths.append(int(row["eligible_seed_item_count"]))
    else:
        collect_audit = _write_formal_rows(
            paths["user_sequences_train"],
            rows_path=rows_path,
            user_quality=user_quality,
            item_quality=item_quality,
            item_frequency=item_frequency,
            config=config,
            stats=stats,
            bucket_counts=bucket_counts,
            unique_items=unique_items,
            seed_lengths=seed_lengths,
        )
    _sample_memory(memory_samples, "after_rows_written")
    _enforce_memory_guard(memory_samples, config.max_rss_mb)

    row_count = int(stats["selected_user_count"])
    rows_signature = _file_signature(rows_path)
    input_signatures = {name: _file_signature(path) for name, path in paths.items()}
    seed_stats = _length_stats(seed_lengths)
    runtime_seconds = round(perf_counter() - started, 6)
    peak_rss_mb = max((int(sample.get("rss_mb") or 0) for sample in memory_samples), default=0)

    outputs = {
        "method_dataset_rows": str(rows_path),
        "method_dataset_manifest": str(output_dir / "method_dataset_manifest.json"),
        "resource_audit": str(output_dir / "resource_audit.json"),
        "no_oracle_audit": str(output_dir / "no_oracle_audit.json"),
        "dataset_audit": str(output_dir / "dataset_audit.json"),
    }
    read_files = {name: str(path) for name, path in paths.items()}
    policy = {
        "paper_basis": "Zhang_Pu_2007_recursive_prediction_algorithm_for_collaborative_filtering",
        "paper_reference": {
            "title": "A recursive prediction algorithm for collaborative filtering recommender systems",
            "authors": ["Jiyong Zhang", "Pearl Pu"],
            "venue": "RecSys 2007",
            "doi": "10.1145/1297231.1297241",
            "acm_url": "https://dl.acm.org/doi/10.1145/1297231.1297241",
        },
        "implementation_level": "dataset_only_train_only_short_sequence_targets_not_full_rating_matrix_rpa",
        "selection_policy": "rpa_like_short_sequence_train_only_v1",
        "formal_policy": "all_eligible_short_sequence_train_only_users" if config.formal_max_users == 0 else "diagnostic_truncated_formal_max_users",
        "smoke_policy": "balanced_sparse_medium_like_small_sample",
        "sequence_len_min": 1,
        "sequence_len_max": 4,
        "source_sequence_field": "recent_positive_item_sequence",
        "source_timestamp_field": "recent_positive_timestamp_sequence",
        "sample_count_caps": {"smoke_user_limit": config.smoke_user_limit} if config.scale_tier == "smoke" else ("none" if config.formal_max_users == 0 else {"formal_max_users": config.formal_max_users}),
        "not_for_promotion": True,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "row_schema_version": ROW_SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": config.run_id,
        "dataset_tier": config.scale_tier,
        "source_method": SOURCE_METHOD,
        "source_variant": SOURCE_VARIANT,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "train_only": True,
        **FORBIDDEN_SWITCHES,
        "algorithm_family": "Recursive_CF_RPA_like",
        "dataset_role": "train_only_rpa_like_recent2y_eligible_sequence_method_dataset",
        "dataset_scope": "recent_2y_train_only_governed_short_sequence_users",
        "input_scope": "recent_2y_train_only_governance",
        "policy": policy,
        "row_count": row_count,
        "user_count": row_count,
        "item_count": len(unique_items),
        "bucket_counts": dict(bucket_counts),
        "seed_item_count_stats": seed_stats,
        "dropped_reason_counts": dict(stats),
        "collect_audit": collect_audit,
        "resource_summary": {
            "max_rss_mb": config.max_rss_mb,
            "max_allowed_rss_mb": MAX_ALLOWED_RSS_MB,
            "peak_rss_mb": peak_rss_mb,
            "memory_contract": "local_builder_must_not_exceed_5g_fail_at_configured_max_rss",
        },
        "read_files": read_files,
        "input_signatures": input_signatures,
        "method_dataset_rows_signature": rows_signature,
        "recent_window_manifest_schema": recent_manifest.get("schema_version"),
        "governance_manifest_schema": governance_manifest.get("schema_version"),
        "outputs": outputs,
        "labels_role": "none_in_dataset_build_or_candidate_generation",
        "source_builder_required_for_candidate_generation": True,
        "recommended_source_builder_sequence_field": "seed_item_sequence",
    }
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "resource_status": "PASS",
        "train_only": True,
        "diagnostic_only": True,
        "max_rss_mb": config.max_rss_mb,
        "max_allowed_rss_mb": MAX_ALLOWED_RSS_MB,
        "peak_rss_mb": peak_rss_mb,
        "memory_contract": "local_builder_must_not_exceed_5g_fail_at_configured_max_rss",
        "memory_samples": memory_samples,
        "runtime_seconds": runtime_seconds,
        "scale_tier": config.scale_tier,
        "row_count": row_count,
        "user_count": row_count,
        "item_count": len(unique_items),
        "raw_train_rows_scanned": int(stats["raw_train_rows_scanned"]),
        "dropped_reason_counts": dict(stats),
    }
    no_oracle_audit = {
        "schema_version": f"{SCHEMA_VERSION}.no_oracle_audit",
        "status": "PASS",
        "train_only": True,
        "diagnostic_only": True,
        "allowed_build_inputs": read_files,
        "forbidden_build_inputs": sorted(FORBIDDEN_PATH_TOKENS),
        "uses_valid": False,
        "uses_test": False,
        "uses_holdout": False,
        "uses_lopo": False,
        "uses_oracle": False,
        "uses_eval_label": False,
        "eval_labels_used_for_candidate_generation": False,
        "eval_labels_used_for_scoring_rule_selection": False,
        "candidate_generation_allowed": False,
        "label_backflow_allowed": False,
    }
    dataset_audit = {
        "schema_version": f"{SCHEMA_VERSION}.dataset_audit",
        "status": "PASS",
        "scale_tier": config.scale_tier,
        "row_schema_version": ROW_SCHEMA_VERSION,
        "bucket_counts": dict(bucket_counts),
        "seed_item_count_stats": seed_stats,
        "unique_seed_item_count": len(unique_items),
        "collect_audit": collect_audit,
        "dropped_reason_counts": dict(stats),
    }
    _sample_memory(memory_samples, "end")
    _enforce_memory_guard(memory_samples, config.max_rss_mb)
    resource_audit["memory_samples"] = memory_samples
    resource_audit["peak_rss_mb"] = max((int(sample.get("rss_mb") or 0) for sample in memory_samples), default=peak_rss_mb)
    manifest["resource_summary"]["peak_rss_mb"] = resource_audit["peak_rss_mb"]

    write_json(output_dir / "method_dataset_manifest.json", manifest)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_oracle_audit.json", no_oracle_audit)
    write_json(output_dir / "dataset_audit.json", dataset_audit)
    return manifest


def _validate_config(config: RPALikeRecent2YDatasetConfig) -> None:
    if config.scale_tier not in ALLOWED_SCALE_TIERS:
        raise ValueError(f"--scale-tier must be one of {sorted(ALLOWED_SCALE_TIERS)}")
    if config.max_rss_mb <= 0:
        raise ValueError("--max-rss-mb must be positive")
    if config.max_rss_mb > MAX_ALLOWED_RSS_MB:
        raise ValueError(f"--max-rss-mb must be <= {MAX_ALLOWED_RSS_MB} for local 5G memory contract")
    if config.smoke_user_limit <= 0:
        raise ValueError("--smoke-user-limit must be positive")
    if config.formal_max_users < 0:
        raise ValueError("--formal-max-users must be non-negative")
    if config.max_items_per_user <= 0:
        raise ValueError("--max-items-per-user must be positive")
    if config.recursive_depth_cap <= 0:
        raise ValueError("--recursive-depth-cap must be positive")


def _input_paths(data_root: Path) -> dict[str, Path]:
    governance_root = data_root / "train_only_governance"
    return {
        "recent_2y_manifest": data_root / "manifest.json",
        "train_governance_manifest": governance_root / "manifest.json",
        "user_sequences_train": data_root / "user_sequences.train.jsonl",
        "user_quality_profile": governance_root / "user_quality_profile.jsonl",
        "item_quality_profile": governance_root / "item_quality_profile.jsonl",
        "item_frequency_train": governance_root / "item_frequency_train.jsonl",
    }


def _validate_allowed_inputs(paths: dict[str, Path]) -> None:
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"Required RPA-like dataset input does not exist: {name}={path}")
        _reject_forbidden_path(path, f"input:{name}")
    if paths["user_sequences_train"].name != "user_sequences.train.jsonl":
        raise ValueError(f"RPA-like dataset must read train user sequences only: {paths['user_sequences_train']}")


def _reject_forbidden_path(path: Path, label: str) -> None:
    filename = path.name.lower()
    if filename in FORBIDDEN_INPUT_NAMES:
        raise ValueError(f"Forbidden {label} path: {path}")
    lowered_parts = {part.lower() for part in path.parts}
    forbidden = lowered_parts & FORBIDDEN_PATH_TOKENS
    if forbidden:
        raise ValueError(f"Forbidden {label} path tokens {sorted(forbidden)}: {path}")


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    _reject_forbidden_path(output_dir, "output")
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory already exists and is non-empty: {output_dir}")


def _load_user_quality(path: Path) -> dict[str, str]:
    profiles: dict[str, str] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or row.get("reviewerID") or "")
        if not user_id:
            continue
        bucket = str(row.get("quality_bucket_v2") or row.get("user_bucket_v2") or row.get("quality_bucket") or row.get("user_bucket") or "unknown")
        profiles[user_id] = bucket
    return profiles


def _load_item_quality(path: Path) -> dict[str, str]:
    profiles: dict[str, str] = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or row.get("asin") or "")
        if not item_id:
            continue
        bucket = str(row.get("quality_bucket_v2") or row.get("item_quality_bucket") or row.get("quality_bucket") or row.get("hotness_bucket") or "unknown")
        profiles[item_id] = bucket
    return profiles


def _load_item_frequency(path: Path) -> dict[str, int]:
    frequencies: dict[str, int] = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or row.get("asin") or "")
        if not item_id:
            continue
        count = row.get("user_count", row.get("train_user_count", row.get("frequency", row.get("interaction_count", 0))))
        try:
            frequencies[item_id] = int(count or 0)
        except (TypeError, ValueError):
            frequencies[item_id] = 0
    return frequencies


def _collect_smoke_rows(
    path: Path,
    *,
    user_quality: dict[str, str],
    item_quality: dict[str, str],
    item_frequency: dict[str, int],
    config: RPALikeRecent2YDatasetConfig,
    stats: Counter,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    per_bucket_cap = max(1, math.ceil(config.smoke_user_limit / 2))
    heaps: dict[str, list[tuple[str, dict[str, Any]]]] = {SPARSE_BUCKET: [], MEDIUM_BUCKET: []}
    for sequence_row in iter_jsonl(path):
        stats["raw_train_rows_scanned"] += 1
        row = _row_from_sequence(sequence_row, user_quality=user_quality, item_quality=item_quality, item_frequency=item_frequency, config=config, stats=stats)
        if row is None:
            continue
        bucket = row["target_bucket"]
        if bucket not in heaps:
            stats["bucket_not_selected_for_smoke"] += 1
            continue
        key = _stable_selection_key(row["user_id"], config.run_id)
        heap = heaps[bucket]
        item = (_invert_hex_key(key), row)
        if len(heap) < per_bucket_cap:
            heapq.heappush(heap, item)
        elif item[0] > heap[0][0]:
            heapq.heapreplace(heap, item)
    rows: list[dict[str, Any]] = []
    bucket_available = {}
    for bucket, heap in heaps.items():
        bucket_rows = [row for _, row in heap]
        bucket_rows.sort(key=lambda row: _stable_selection_key(row["user_id"], config.run_id))
        bucket_available[bucket] = len(bucket_rows)
        rows.extend(bucket_rows)
    rows = rows[: config.smoke_user_limit]
    for row in rows:
        stats["selected_user_count"] += 1
    return rows, {
        "selection_mode": "deterministic_hash_balanced_bucket_sample",
        "per_bucket_cap": per_bucket_cap,
        "bucket_available_counts": bucket_available,
        "bucket_underfilled_counts": {bucket: max(0, per_bucket_cap - count) for bucket, count in bucket_available.items()},
    }


def _write_formal_rows(
    path: Path,
    *,
    rows_path: Path,
    user_quality: dict[str, str],
    item_quality: dict[str, str],
    item_frequency: dict[str, int],
    config: RPALikeRecent2YDatasetConfig,
    stats: Counter,
    bucket_counts: Counter[str],
    unique_items: set[str],
    seed_lengths: list[int],
) -> dict[str, Any]:
    truncated = False
    with rows_path.open("w", encoding="utf-8") as handle:
        for sequence_row in iter_jsonl(path):
            stats["raw_train_rows_scanned"] += 1
            row = _row_from_sequence(sequence_row, user_quality=user_quality, item_quality=item_quality, item_frequency=item_frequency, config=config, stats=stats)
            if row is None:
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats["selected_user_count"] += 1
            bucket_counts[row["target_bucket"]] += 1
            unique_items.update(row["seed_item_sequence"])
            seed_lengths.append(int(row["eligible_seed_item_count"]))
            if config.formal_max_users and stats["selected_user_count"] >= config.formal_max_users:
                truncated = True
                break
    return {
        "selection_mode": "all_eligible_short_sequence_train_only_users" if not config.formal_max_users else "diagnostic_truncated_formal_max_users",
        "formal_max_users": config.formal_max_users,
        "truncated": truncated,
    }


def _row_from_sequence(
    sequence_row: dict[str, Any],
    *,
    user_quality: dict[str, str],
    item_quality: dict[str, str],
    item_frequency: dict[str, int],
    config: RPALikeRecent2YDatasetConfig,
    stats: Counter,
) -> dict[str, Any] | None:
    user_id = str(sequence_row.get("user_id") or "")
    if not user_id:
        stats["missing_user_id"] += 1
        return None
    quality_bucket = user_quality.get(user_id)
    if quality_bucket is None:
        stats["user_quality_missing"] += 1
        return None
    raw_items = [str(item_id) for item_id in sequence_row.get("recent_positive_item_sequence") or [] if item_id]
    raw_timestamps = list(sequence_row.get("recent_positive_timestamp_sequence") or [])
    if not raw_items:
        stats["zero_positive_excluded"] += 1
        return None
    deduped_items, deduped_timestamps = _unique_recent_with_timestamps(raw_items, raw_timestamps, config.max_items_per_user)
    eligible_items: list[str] = []
    eligible_timestamps: list[Any] = []
    dropped_reasons: Counter[str] = Counter()
    item_user_counts: list[int] = []
    for index, item_id in enumerate(deduped_items):
        reason = _drop_item_reason(item_id, item_quality=item_quality, item_frequency=item_frequency)
        if reason:
            dropped_reasons[reason] += 1
            continue
        eligible_items.append(item_id)
        eligible_timestamps.append(deduped_timestamps[index] if index < len(deduped_timestamps) else None)
        item_user_counts.append(item_frequency.get(item_id, 0))
    if not eligible_items:
        stats["empty_sequence_after_item_filter"] += 1
        return None
    target_bucket = _target_bucket(len(eligible_items))
    if target_bucket is None:
        stats["sequence_too_long_for_rpa_like"] += 1
        return None
    dropped_count = len(deduped_items) - len(eligible_items)
    for reason, count in dropped_reasons.items():
        stats[f"dropped_item:{reason}"] += count
    shared_item_hit = any(count > 1 for count in item_user_counts)
    return {
        "schema_version": ROW_SCHEMA_VERSION,
        "source_method": SOURCE_METHOD,
        "source_variant": SOURCE_VARIANT,
        "dataset_role": "train_only_rpa_like_eligible_user_sequence",
        "train_only": True,
        "diagnostic_only": True,
        "user_id": user_id,
        "user_quality_bucket": quality_bucket,
        "target_bucket": target_bucket,
        "positive_item_count": int(sequence_row.get("positive_sequence_len") or len(raw_items)),
        "raw_train_sequence_len": int(sequence_row.get("sequence_len") or len(sequence_row.get("recent_item_sequence") or raw_items)),
        "seed_item_sequence": eligible_items,
        "seed_timestamp_sequence": eligible_timestamps,
        "seed_item_count": len(deduped_items),
        "eligible_seed_item_count": len(eligible_items),
        "dropped_seed_item_count": dropped_count,
        "dropped_seed_reasons": dict(dropped_reasons),
        "shared_item_neighbor_signal": {
            "shared_item_hit": shared_item_hit,
            "max_item_user_count": max(item_user_counts) if item_user_counts else 0,
            "avg_item_user_count": round(sum(item_user_counts) / len(item_user_counts), 6) if item_user_counts else 0.0,
        },
        "max_items_per_user": config.max_items_per_user,
        "item_hotness_policy": "train_only_item_frequency_available_with_quality_bucket_guard",
        "iuf_weighting_required": True,
        "recursive_depth_cap": config.recursive_depth_cap,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "labels_role": "none_in_dataset_build",
    }


def _drop_item_reason(item_id: str, *, item_quality: dict[str, str], item_frequency: dict[str, int]) -> str | None:
    if item_id not in item_frequency:
        return "missing_item_frequency"
    bucket = item_quality.get(item_id, "unknown")
    if bucket.lower() in DISALLOWED_ITEM_BUCKETS:
        return "item_quality_bucket_not_allowed"
    return None


def _target_bucket(length: int) -> str | None:
    if length == 1:
        return SPARSE_BUCKET
    if 2 <= length <= 4:
        return MEDIUM_BUCKET
    return None


def _unique_recent_with_timestamps(items: Iterable[str], timestamps: Iterable[Any], limit: int) -> tuple[list[str], list[Any]]:
    item_list = list(items)
    timestamp_list = list(timestamps)
    rows = list(zip(item_list, timestamp_list + [None] * max(0, len(item_list) - len(timestamp_list))))
    seen: set[str] = set()
    selected: list[tuple[str, Any]] = []
    for item_id, timestamp in reversed(rows):
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        selected.append((item_id, timestamp))
        if len(selected) >= limit:
            break
    selected.reverse()
    return [item_id for item_id, _ in selected], [timestamp for _, timestamp in selected]


def _stable_selection_key(user_id: str, run_id: str) -> str:
    return hashlib.sha256(f"{run_id}:{user_id}".encode("utf-8")).hexdigest()


def _invert_hex_key(key: str) -> str:
    # heapq is min-heap; inverted key keeps the lexicographically smallest stable hashes.
    return "".join(f"{15 - int(char, 16):x}" for char in key)


def _sample_memory(samples: list[dict[str, Any]], stage: str) -> None:
    rss_mb, available_bytes, backend = _memory_snapshot()
    if rss_mb <= 0:
        raise RuntimeError("RSS memory measurement unavailable; refusing to run under local 5G memory contract")
    samples.append(
        {
            "stage": stage,
            "rss_mb": int(rss_mb),
            "available_memory_bytes": available_bytes,
            "backend": backend,
        }
    )


def _enforce_memory_guard(samples: list[dict[str, Any]], max_rss_mb: int) -> None:
    latest = samples[-1] if samples else {}
    rss_mb = int(latest.get("rss_mb") or 0)
    if rss_mb > max_rss_mb:
        raise RuntimeError(f"RSS memory guard exceeded: {rss_mb}MB > {max_rss_mb}MB")


def _memory_snapshot() -> tuple[int, int | None, str]:
    try:
        import psutil  # type: ignore

        process = psutil.Process()
        return int(process.memory_info().rss / (1024 * 1024)), int(psutil.virtual_memory().available), "psutil"
    except Exception:
        pass
    try:
        import resource  # type: ignore

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = int(usage / 1024) if sys.platform != "darwin" else int(usage / (1024 * 1024))
        return rss_mb, None, "resource"
    except Exception:
        return 0, None, "unavailable"


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return {"path": str(path), "exists": path.is_file(), "size_bytes": size, "sha256": digest.hexdigest()}


def _length_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50": ordered[min(len(ordered) - 1, int(0.5 * (len(ordered) - 1)))],
        "p90": ordered[min(len(ordered) - 1, int(0.9 * (len(ordered) - 1)))],
        "max": ordered[-1],
    }


if __name__ == "__main__":
    main()
