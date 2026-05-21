from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _enforce_project_venv, _existing_ancestor, _file_signature

SCHEMA_VERSION = "full_train_usercf_sidecar_v2"
SOURCE_NAME = "usercf_recall"
INDEX_SCOPE = "FULL_DERIVED_INDEX"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_ELIGIBLE_USER_QUALITY_MANIFEST = ROOT / "outputs" / "recall" / "pool500_user_quality" / "target500_train_only" / "eligible_user_quality_manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_sidecar_fix" / "usercf_recall_guarded_diagnostic"
DEFAULT_MAX_ITEMS_PER_USER = 80
DEFAULT_MAX_ITEM_USER_FREQ = 5000
DEFAULT_SIMILAR_USERS_TOP_K = 100
DEFAULT_CANDIDATE_TOP_K_PER_USER = 200
DEFAULT_SHARD_COUNT = 64
DEFAULT_TARGET_BATCH_SIZE = 100
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
DEFAULT_MAX_RSS_MB = 4096
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
    parser = argparse.ArgumentParser(description="Build a guarded diagnostic train-only UserCF recall sidecar index.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--eligible-user-quality-manifest", default=str(DEFAULT_ELIGIBLE_USER_QUALITY_MANIFEST))
    parser.add_argument("--include-medium-behavior", action="store_true")
    parser.add_argument("--max-items-per-user", type=int, default=DEFAULT_MAX_ITEMS_PER_USER)
    parser.add_argument("--max-item-user-freq", type=int, default=DEFAULT_MAX_ITEM_USER_FREQ)
    parser.add_argument("--similar-users-top-k", type=int, default=DEFAULT_SIMILAR_USERS_TOP_K)
    parser.add_argument("--candidate-top-k-per-user", type=int, default=DEFAULT_CANDIDATE_TOP_K_PER_USER)
    parser.add_argument("--shard-count", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--target-user-limit", type=int, default=0, help="Keep at most N eligible diagnostic users; 0 keeps all eligible users.")
    parser.add_argument("--target-batch-size", type=int, default=DEFAULT_TARGET_BATCH_SIZE)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--min-free-memory-bytes", type=int, default=0)
    parser.add_argument("--max-rss-mb", type=int, default=DEFAULT_MAX_RSS_MB)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_full_train_usercf_sidecar(
    *,
    clean_manifest: Path = DEFAULT_CLEAN_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    eligible_user_quality_manifest: Path | None = DEFAULT_ELIGIBLE_USER_QUALITY_MANIFEST,
    include_medium_behavior: bool = False,
    max_items_per_user: int = DEFAULT_MAX_ITEMS_PER_USER,
    max_item_user_freq: int = DEFAULT_MAX_ITEM_USER_FREQ,
    similar_users_top_k: int = DEFAULT_SIMILAR_USERS_TOP_K,
    candidate_top_k_per_user: int = DEFAULT_CANDIDATE_TOP_K_PER_USER,
    shard_count: int = DEFAULT_SHARD_COUNT,
    target_user_limit: int = 0,
    target_batch_size: int = DEFAULT_TARGET_BATCH_SIZE,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    min_free_memory_bytes: int = 0,
    max_rss_mb: int = DEFAULT_MAX_RSS_MB,
    resume: bool = False,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    memory_samples: list[dict[str, Any]] = []
    _sample_memory(memory_samples, "start")
    _validate_caps(
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        similar_users_top_k=similar_users_top_k,
        candidate_top_k_per_user=candidate_top_k_per_user,
        shard_count=shard_count,
        target_batch_size=target_batch_size,
        min_free_bytes=min_free_bytes,
        min_free_memory_bytes=min_free_memory_bytes,
        max_rss_mb=max_rss_mb,
    )
    if target_user_limit < 0:
        raise ValueError("--target-user-limit must be non-negative")
    if enforce_venv:
        _enforce_project_venv()

    clean_manifest = clean_manifest.resolve()
    output_dir = output_dir.resolve()
    eligible_user_quality_manifest = eligible_user_quality_manifest.resolve() if eligible_user_quality_manifest else None
    _precheck_paths(clean_manifest, output_dir, overwrite, resume, eligible_user_quality_manifest)
    _enforce_memory_guard(memory_samples, max_rss_mb=max_rss_mb, min_free_memory_bytes=min_free_memory_bytes)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if disk_free_start < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below --min-free-bytes: {disk_free_start} < {min_free_bytes}")

    manifest_payload = read_json(clean_manifest)
    train_sequence_path = _resolve_train_sequence_path(clean_manifest, manifest_payload)
    _precheck_train_path(train_sequence_path)
    eligible_manifest_payload, eligible_target_user_ids = _resolve_eligible_target_users(
        eligible_user_quality_manifest,
        include_medium_behavior=include_medium_behavior,
        target_user_limit=target_user_limit,
    )

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    if output_dir.exists() and not resume:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    shards_dir = output_dir / "shards"
    checkpoint_dir = output_dir / "batch_checkpoints"
    shards_dir.mkdir(parents=True, exist_ok=resume)
    checkpoint_dir.mkdir(parents=True, exist_ok=resume)

    user_items, item_users_raw, load_audit, target_user_ids = _load_train_user_items(
        train_sequence_path,
        max_items_per_user,
        target_user_limit=target_user_limit,
        eligible_target_user_ids=eligible_target_user_ids,
    )
    hot_items = {item_id for item_id, users in item_users_raw.items() if len(users) > max_item_user_freq}
    item_users = {item_id: users for item_id, users in item_users_raw.items() if item_id not in hot_items}
    _sample_memory(memory_samples, "after_index_load")
    _enforce_memory_guard(memory_samples, max_rss_mb=max_rss_mb, min_free_memory_bytes=min_free_memory_bytes)

    shard_paths = [shards_dir / f"usercf_recall_shard_{index:05d}.jsonl" for index in range(shard_count)]
    if not resume:
        for shard_path in shard_paths:
            shard_path.write_text("", encoding="utf-8")
    batch_manifests = _build_usercf_candidates_batched(
        user_items=user_items,
        item_users=item_users,
        target_user_ids=target_user_ids,
        similar_users_top_k=similar_users_top_k,
        candidate_top_k_per_user=candidate_top_k_per_user,
        target_batch_size=target_batch_size,
        shard_paths=shard_paths,
        checkpoint_dir=checkpoint_dir,
        resume=resume,
        memory_samples=memory_samples,
        max_rss_mb=max_rss_mb,
        min_free_memory_bytes=min_free_memory_bytes,
    )
    shard_stats = _scan_candidate_shards(shard_paths)
    candidate_shard_signatures = [_file_signature(Path(stat["path"])) for stat in shard_stats]
    candidate_user_count = sum(int(stat["row_count"]) for stat in shard_stats)
    candidate_total_count = sum(int(stat["candidate_count"]) for stat in shard_stats)
    neighbor_edge_checks = sum(int(batch.get("neighbor_edge_checks", 0)) for batch in batch_manifests)
    similar_user_links_used = sum(int(batch.get("similar_user_links_used", 0)) for batch in batch_manifests)
    row_count = candidate_user_count
    target_user_count = len(target_user_ids)
    underfilled_user_coverage = round(candidate_user_count / target_user_count, 6) if target_user_count else 0.0
    marginal_candidate_share = round(candidate_total_count / (target_user_count * 500), 6) if target_user_count else 0.0
    peak_rss_mb = max((sample.get("rss_mb") or 0 for sample in memory_samples), default=0)

    config_caps = {
        "max_items_per_user": max_items_per_user,
        "max_item_user_freq": max_item_user_freq,
        "similar_users_top_k": similar_users_top_k,
        "candidate_top_k_per_user": candidate_top_k_per_user,
        "shard_count": shard_count,
        "target_user_limit": target_user_limit,
        "target_batch_size": target_batch_size,
        "min_free_bytes": min_free_bytes,
        "min_free_memory_bytes": min_free_memory_bytes,
        "max_rss_mb": max_rss_mb,
        "resume": resume,
    }
    hard_contract = {
        "source": SOURCE_NAME,
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    resolved_paths = {
        "clean_manifest": str(clean_manifest),
        "train_user_sequences_path": str(train_sequence_path),
        "eligible_user_quality_manifest": str(eligible_user_quality_manifest) if eligible_user_quality_manifest else None,
        "output_dir": str(output_dir),
        "shards_dir": str(shards_dir),
        "checkpoint_dir": str(checkpoint_dir),
    }
    forbidden_inputs = [str(train_sequence_path.parent / name) for name in FORBIDDEN_INPUT_NAMES]
    source_signature = _source_signature(train_sequence_path)
    eligible_signature = _file_signature(eligible_user_quality_manifest) if eligible_user_quality_manifest else None
    dropped_hot_items = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE_NAME,
        "max_item_user_freq": max_item_user_freq,
        "dropped_item_count": len(hot_items),
        "items": [
            {"item_id": item_id, "user_freq": len(item_users_raw[item_id])}
            for item_id in sorted(hot_items, key=lambda item_id: (-len(item_users_raw[item_id]), item_id))
        ],
    }
    no_holdout_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **hard_contract,
        "read_files": [path for path in (str(train_sequence_path), str(eligible_user_quality_manifest) if eligible_user_quality_manifest else None) if path],
        "forbidden_inputs": forbidden_inputs,
        "uses_valid": False,
        "uses_test": False,
        "uses_holdout": False,
        "uses_10k": False,
        "uses_pool1000": False,
        "ranking_input_modified": False,
        "train_sequence_field": "recent_positive_item_sequence",
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **hard_contract,
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "config_caps": config_caps,
        "source_signature": source_signature,
        "eligible_user_quality_signature": eligible_signature,
        **load_audit,
        "effective_item_count": len(item_users),
        "dropped_hot_item_count": len(hot_items),
        "candidate_user_count": candidate_user_count,
        "candidate_total_count": candidate_total_count,
        "row_count": row_count,
        "peak_rss_mb": peak_rss_mb,
        "neighbor_edge_checks": neighbor_edge_checks,
        "similar_user_links_used": similar_user_links_used,
        "underfilled_user_coverage": underfilled_user_coverage,
        "underfilled_user_coverage_count": candidate_user_count,
        "marginal_candidate_share": marginal_candidate_share,
        "memory_samples": memory_samples,
        "batches": batch_manifests,
        "shards": shard_stats,
    }
    per_source_candidate_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.per_source_candidate_manifest",
        "status": "DIAGNOSTIC_ONLY",
        **hard_contract,
        "source_status": "DIAGNOSTIC_ONLY",
        "target_user_count": target_user_count,
        "indexed_user_count": load_audit["indexed_user_count"],
        "candidate_user_count": candidate_user_count,
        "candidate_total_count": candidate_total_count,
        "row_count": row_count,
        "peak_rss_mb": peak_rss_mb,
        "underfilled_user_coverage": underfilled_user_coverage,
        "underfilled_user_coverage_count": candidate_user_count,
        "marginal_candidate_share": marginal_candidate_share,
        "candidate_shards": [stat["path"] for stat in shard_stats],
        "candidate_shard_signatures": candidate_shard_signatures,
        "alignment_with_ready_source_stoploss_audit": {
            "ready_sources_reference": ["category", "popular", "swing_recall"],
            "metric_compatibility": ["underfilled_user_coverage", "marginal_candidate_share", "row_count"],
            "diagnostic_judgement": "UserCF has marginal diagnostic contribution only when candidate_user_count covers underfilled heavy_cf_eligible users and marginal_candidate_share is positive; this artifact does not authorize promotion.",
        },
    }
    eligible_user_policy = "heavy_cf_eligible_or_medium_behavior" if include_medium_behavior else "heavy_cf_eligible"
    if eligible_manifest_payload and eligible_manifest_payload.get("scope") == "target500_train_only_high_cost_slice_users":
        eligible_user_policy = "target500_train_only_high_cost_slice"
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source_status": "DIAGNOSTIC_ONLY",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **hard_contract,
        "eligible_user_policy": eligible_user_policy,
        "resolved_paths": resolved_paths,
        "config_caps": config_caps,
        "target_user_count": target_user_count,
        "indexed_user_count": load_audit["indexed_user_count"],
        "candidate_user_count": candidate_user_count,
        "candidate_total_count": candidate_total_count,
        "row_count": row_count,
        "peak_rss_mb": peak_rss_mb,
        "underfilled_user_coverage": underfilled_user_coverage,
        "marginal_candidate_share": marginal_candidate_share,
        "outputs": {
            "candidate_shards": [stat["path"] for stat in shard_stats],
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "custom_index_selection_manifest": str(output_dir / "custom_index_selection_manifest.json"),
            "readiness_contract": str(output_dir / "readiness_contract.json"),
            "per_source_candidate_manifest": str(output_dir / "per_source_candidate_manifest.json"),
            "dropped_hot_items": str(output_dir / "dropped_hot_items.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
        },
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    custom_index_selection_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **hard_contract,
        "source_status": "DIAGNOSTIC_ONLY",
        "selection_reason": "guarded_train_only_usercf_diagnostic_for_heavy_cf_eligible_users_avoids_unbounded_user_user_matrix",
        "eligible_user_policy": source_index_manifest["eligible_user_policy"],
        "eligible_user_quality_manifest": str(eligible_user_quality_manifest) if eligible_user_quality_manifest else None,
        "eligible_user_quality_summary": _eligible_quality_summary(eligible_manifest_payload),
        "target_user_ids": target_user_ids,
        "allowed_inputs": ["clean_manifest.train_user_sequences_path", "eligible_user_quality_manifest.profiles"],
        "forbidden_inputs": forbidden_inputs,
        "source_signature": source_signature,
        "eligible_user_quality_signature": eligible_signature,
        "candidate_shards": source_index_manifest["outputs"]["candidate_shards"],
        "candidate_shard_signatures": candidate_shard_signatures,
    }

    write_json(output_dir / "dropped_hot_items.json", dropped_hot_items)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(output_dir / "custom_index_selection_manifest.json", custom_index_selection_manifest)
    write_json(output_dir / "per_source_candidate_manifest.json", per_source_candidate_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    readiness_contract = _readiness_contract(
        output_dir=output_dir,
        source_index_manifest=source_index_manifest,
        custom_index_selection_manifest=custom_index_selection_manifest,
        per_source_candidate_manifest=per_source_candidate_manifest,
        candidate_shard_signatures=candidate_shard_signatures,
    )
    write_json(output_dir / "readiness_contract.json", readiness_contract)
    return source_index_manifest


def _validate_caps(
    *,
    max_items_per_user: int,
    max_item_user_freq: int,
    similar_users_top_k: int,
    candidate_top_k_per_user: int,
    shard_count: int,
    target_batch_size: int,
    min_free_bytes: int,
    min_free_memory_bytes: int,
    max_rss_mb: int,
) -> None:
    positive_caps = {
        "--max-items-per-user": max_items_per_user,
        "--max-item-user-freq": max_item_user_freq,
        "--similar-users-top-k": similar_users_top_k,
        "--candidate-top-k-per-user": candidate_top_k_per_user,
        "--shard-count": shard_count,
        "--target-batch-size": target_batch_size,
        "--max-rss-mb": max_rss_mb,
    }
    for name, value in positive_caps.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    if min_free_bytes < 0:
        raise ValueError("--min-free-bytes must be non-negative")
    if min_free_memory_bytes < 0:
        raise ValueError("--min-free-memory-bytes must be non-negative")


def _precheck_paths(clean_manifest: Path, output_dir: Path, overwrite: bool, resume: bool, eligible_user_quality_manifest: Path | None) -> None:
    for path in (clean_manifest, output_dir, eligible_user_quality_manifest):
        if path is None:
            continue
        lowered = str(path).replace("\\", "/").lower()
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden holdout/10k/pool1000 path is not allowed: {path}")
    if not clean_manifest.is_file():
        raise FileNotFoundError(clean_manifest)
    if eligible_user_quality_manifest and not eligible_user_quality_manifest.is_file():
        raise FileNotFoundError(eligible_user_quality_manifest)
    if overwrite and resume:
        raise ValueError("--overwrite and --resume cannot be used together")
    try:
        output_dir.relative_to(clean_manifest.parent)
    except ValueError:
        return
    raise ValueError(f"Output directory must not be inside clean manifest directory: {output_dir}")


def _precheck_train_path(train_sequence_path: Path) -> None:
    lowered = str(train_sequence_path).replace("\\", "/").lower()
    if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
        raise ValueError(f"Forbidden holdout/10k/pool1000 path is not allowed: {train_sequence_path}")
    if any(name in lowered for name in FORBIDDEN_INPUT_NAMES):
        raise ValueError(f"Forbidden non-train input is not allowed: {train_sequence_path}")
    if train_sequence_path.name != "user_sequences.train.jsonl":
        raise ValueError(f"UserCF sidecar must read user_sequences.train.jsonl, got {train_sequence_path.name}")
    if not train_sequence_path.is_file():
        raise FileNotFoundError(train_sequence_path)


def _resolve_train_sequence_path(clean_manifest: Path, manifest_payload: dict[str, Any]) -> Path:
    candidates = [
        manifest_payload.get("train_user_sequences_path"),
        manifest_payload.get("user_sequences_train_path"),
        manifest_payload.get("user_sequences", {}).get("train") if isinstance(manifest_payload.get("user_sequences"), dict) else None,
    ]
    for candidate in candidates:
        if candidate:
            path = Path(str(candidate))
            if path.is_absolute():
                return path.resolve()
            root_candidate = (ROOT / path).resolve()
            if root_candidate.exists():
                return root_candidate
            return (clean_manifest.parent / path).resolve()
    return (clean_manifest.parent / "user_sequences.train.jsonl").resolve()


def _resolve_eligible_target_users(
    eligible_user_quality_manifest: Path | None,
    *,
    include_medium_behavior: bool,
    target_user_limit: int,
) -> tuple[dict[str, Any] | None, list[str] | None]:
    if eligible_user_quality_manifest is None:
        return None, None
    payload = read_json(eligible_user_quality_manifest)
    if payload.get("train_only") is not True:
        raise ValueError("eligible_user_quality_manifest must be train_only")
    if payload.get("candidate_generation_allowed") is not False:
        raise ValueError("eligible_user_quality_manifest must not authorize candidate generation")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("eligible_user_quality_manifest.profiles must be a list")
    target_user_ids = []
    if payload.get("scope") == "target500_train_only_high_cost_slice_users":
        for profile in profiles:
            if isinstance(profile, dict) and profile.get("eligible_for_usercf_slice") is True and profile.get("quality_bucket") == "target500_high_cost_slice":
                user_id = str(profile.get("user_id", ""))
                if user_id:
                    target_user_ids.append(user_id)
    else:
        allowed_buckets = {"heavy_cf_eligible"}
        if include_medium_behavior:
            allowed_buckets.add("medium_behavior")
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            user_id = str(profile.get("user_id", ""))
            bucket = str(profile.get("quality_bucket", ""))
            eligible_for_usercf = profile.get("eligible_for_usercf") is True
            medium_allowed = include_medium_behavior and bucket == "medium_behavior"
            if user_id and (eligible_for_usercf or bucket == "heavy_cf_eligible" or medium_allowed) and bucket in allowed_buckets:
                target_user_ids.append(user_id)
    if target_user_limit:
        target_user_ids = target_user_ids[:target_user_limit]
    return payload, target_user_ids


def _load_train_user_items(
    path: Path,
    max_items_per_user: int,
    target_user_limit: int = 0,
    eligible_target_user_ids: list[str] | None = None,
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, Any], list[str]]:
    user_items: dict[str, set[str]] = {}
    item_users: dict[str, set[str]] = defaultdict(set)
    rows_scanned = 0
    rows_with_positive_sequence = 0
    raw_positive_event_count = 0
    kept_positive_event_count = 0
    target_items: set[str] = set()
    target_user_ids: list[str] = []
    if eligible_target_user_ids is not None and not eligible_target_user_ids:
        return {}, {}, {
            "train_rows_scanned": 0,
            "rows_with_positive_sequence": 0,
            "indexed_user_count": 0,
            "target_user_limit": target_user_limit,
            "target_user_count": 0,
            "target_item_count": 0,
            "raw_positive_event_count": 0,
            "kept_unique_positive_event_count": 0,
            "raw_item_count": 0,
        }, []
    explicit_target_set = set(eligible_target_user_ids or [])
    if explicit_target_set or target_user_limit:
        for row in iter_jsonl(path):
            user_id = str(row.get("user_id", ""))
            raw_items = row.get("recent_positive_item_sequence", []) or []
            if not user_id or not isinstance(raw_items, list):
                continue
            if explicit_target_set and user_id not in explicit_target_set:
                continue
            items = _recent_unique_items(raw_items, max_items_per_user)
            if not items:
                continue
            target_user_ids.append(user_id)
            target_items.update(items)
            if not explicit_target_set and target_user_limit and len(target_user_ids) >= target_user_limit:
                break
        if explicit_target_set:
            target_user_ids = [user_id for user_id in eligible_target_user_ids or [] if user_id in set(target_user_ids)]
    for row in iter_jsonl(path):
        rows_scanned += 1
        user_id = str(row.get("user_id", ""))
        raw_items = row.get("recent_positive_item_sequence", []) or []
        if not user_id or not isinstance(raw_items, list):
            continue
        rows_with_positive_sequence += 1
        raw_positive_event_count += len(raw_items)
        items = _recent_unique_items(raw_items, max_items_per_user)
        if not items:
            continue
        item_set = set(items)
        if target_user_ids and not (user_id in set(target_user_ids) or item_set & target_items):
            continue
        user_items[user_id] = item_set
        kept_positive_event_count += len(item_set)
        for item_id in item_set:
            item_users[item_id].add(user_id)
    if not target_user_ids:
        target_user_ids = list(user_items)
    return user_items, dict(item_users), {
        "train_rows_scanned": rows_scanned,
        "rows_with_positive_sequence": rows_with_positive_sequence,
        "indexed_user_count": len(user_items),
        "target_user_limit": target_user_limit,
        "target_user_count": len(target_user_ids),
        "target_item_count": len(target_items),
        "raw_positive_event_count": raw_positive_event_count,
        "kept_unique_positive_event_count": kept_positive_event_count,
        "raw_item_count": len(item_users),
    }, target_user_ids


def _recent_unique_items(raw_items: list[Any], max_items_per_user: int) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for item in reversed(raw_items[-max_items_per_user:]):
        item_id = str(item)
        if item_id and item_id not in seen:
            seen.add(item_id)
            items.append(item_id)
    items.reverse()
    return items


def _build_usercf_candidates_batched(
    *,
    user_items: dict[str, set[str]],
    item_users: dict[str, set[str]],
    target_user_ids: list[str],
    similar_users_top_k: int,
    candidate_top_k_per_user: int,
    target_batch_size: int,
    shard_paths: list[Path],
    checkpoint_dir: Path,
    resume: bool,
    memory_samples: list[dict[str, Any]],
    max_rss_mb: int,
    min_free_memory_bytes: int,
) -> list[dict[str, Any]]:
    batch_manifests: list[dict[str, Any]] = []
    for batch_index, start in enumerate(range(0, len(target_user_ids), target_batch_size)):
        batch_user_ids = target_user_ids[start : start + target_batch_size]
        checkpoint_path = checkpoint_dir / f"usercf_batch_{batch_index:05d}.json"
        if resume and checkpoint_path.exists():
            batch_manifests.append(read_json(checkpoint_path))
            continue
        build_result = _build_usercf_candidates(
            user_items=user_items,
            item_users=item_users,
            similar_users_top_k=similar_users_top_k,
            candidate_top_k_per_user=candidate_top_k_per_user,
            target_user_ids=batch_user_ids,
        )
        shard_delta = _append_candidate_shards(shard_paths, build_result["candidates_by_user"])
        _sample_memory(memory_samples, f"after_batch_{batch_index:05d}")
        _enforce_memory_guard(memory_samples, max_rss_mb=max_rss_mb, min_free_memory_bytes=min_free_memory_bytes)
        batch_manifest = {
            "schema_version": f"{SCHEMA_VERSION}.batch_checkpoint",
            "status": "PASS",
            "batch_index": batch_index,
            "target_user_count": len(batch_user_ids),
            "target_user_ids": batch_user_ids,
            "candidate_user_count": build_result["candidate_user_count"],
            "candidate_total_count": build_result["candidate_total_count"],
            "row_count": build_result["candidate_user_count"],
            "neighbor_edge_checks": build_result["neighbor_edge_checks"],
            "similar_user_links_used": build_result["similar_user_links_used"],
            "shards": shard_delta,
        }
        write_json(checkpoint_path, batch_manifest)
        batch_manifests.append(batch_manifest)
    return batch_manifests


def _build_usercf_candidates(
    *,
    user_items: dict[str, set[str]],
    item_users: dict[str, set[str]],
    similar_users_top_k: int,
    candidate_top_k_per_user: int,
    target_user_ids: list[str] | None = None,
) -> dict[str, Any]:
    candidates_by_user: dict[str, list[dict[str, Any]]] = {}
    neighbor_edge_checks = 0
    similar_user_links_used = 0
    candidate_total_count = 0
    user_ids = target_user_ids or list(user_items)
    for user_id in user_ids:
        items = user_items.get(user_id, set())
        neighbor_scores: Counter[str] = Counter()
        for item_id in items:
            for neighbor_user in item_users.get(item_id, set()):
                if neighbor_user != user_id:
                    neighbor_scores[neighbor_user] += 1
                    neighbor_edge_checks += 1
        candidate_scores: Counter[str] = Counter()
        sorted_neighbors = sorted(neighbor_scores.items(), key=lambda pair: (-pair[1], pair[0]))[:similar_users_top_k]
        similar_user_links_used += len(sorted_neighbors)
        for neighbor_user, overlap in sorted_neighbors:
            neighbor_items = user_items.get(neighbor_user, set())
            norm = math.sqrt(len(items) * max(1, len(neighbor_items)))
            user_score = float(overlap) / norm if norm else 0.0
            for item_id in neighbor_items - items:
                candidate_scores[item_id] += user_score
        rows = []
        for rank, (item_id, score) in enumerate(sorted(candidate_scores.items(), key=lambda pair: (-pair[1], pair[0]))[:candidate_top_k_per_user], start=1):
            rows.append({"item_id": item_id, "score": round(float(score), 6), "rank": rank, "source": SOURCE_NAME})
        if rows:
            candidates_by_user[user_id] = rows
            candidate_total_count += len(rows)
    return {
        "candidates_by_user": candidates_by_user,
        "candidate_user_count": len(candidates_by_user),
        "candidate_total_count": candidate_total_count,
        "neighbor_edge_checks": neighbor_edge_checks,
        "similar_user_links_used": similar_user_links_used,
    }


def _append_candidate_shards(shard_paths: list[Path], candidates_by_user: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    stats = [{"shard_id": index, "path": str(path), "row_count": 0, "candidate_count": 0} for index, path in enumerate(shard_paths)]
    handles = [path.open("a", encoding="utf-8") for path in shard_paths]
    try:
        for user_id in sorted(candidates_by_user):
            shard_id = _stable_shard_id(user_id, len(shard_paths))
            record = {"user_id": user_id, "candidates": candidates_by_user[user_id]}
            handles[shard_id].write(json.dumps(record, ensure_ascii=False) + "\n")
            stats[shard_id]["row_count"] += 1
            stats[shard_id]["candidate_count"] += len(candidates_by_user[user_id])
    finally:
        for handle in handles:
            handle.close()
    return stats


def _scan_candidate_shards(shard_paths: list[Path]) -> list[dict[str, Any]]:
    stats = []
    for index, path in enumerate(shard_paths):
        row_count = 0
        candidate_count = 0
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    row_count += 1
                    candidate_count += len(row.get("candidates", []) or [])
        stats.append({"shard_id": index, "path": str(path), "row_count": row_count, "candidate_count": candidate_count})
    return stats


def _readiness_contract(
    *,
    output_dir: Path,
    source_index_manifest: dict[str, Any],
    custom_index_selection_manifest: dict[str, Any],
    per_source_candidate_manifest: dict[str, Any],
    candidate_shard_signatures: list[dict[str, Any]],
) -> dict[str, Any]:
    source_index_signature = _file_signature(output_dir / "source_index_manifest.json")
    selection_manifest_signature = _file_signature(output_dir / "custom_index_selection_manifest.json")
    per_source_candidate_signature = _file_signature(output_dir / "per_source_candidate_manifest.json")
    deterministic_payload = {
        "source": SOURCE_NAME,
        "status": "DIAGNOSTIC_ONLY",
        "index_status": "INDEX_READY",
        "diagnostic_output_status": "DIAGNOSTIC_OUTPUT_READY",
        "full_output_status": "DIAGNOSTIC_OUTPUT_READY",
        "index_scope": INDEX_SCOPE,
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "manifest_path": str(output_dir / "readiness_contract.json"),
        "index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "output_manifest_path": str(output_dir / "custom_index_selection_manifest.json"),
        "per_source_candidate_manifest_path": str(output_dir / "per_source_candidate_manifest.json"),
        "candidate_shard_signatures": candidate_shard_signatures,
        "index_manifest_signature": source_index_signature,
        "output_manifest_signature": selection_manifest_signature,
        "per_source_candidate_manifest_signature": per_source_candidate_signature,
        "source_signature": custom_index_selection_manifest["source_signature"],
        "target_user_count": per_source_candidate_manifest["target_user_count"],
        "indexed_user_count": per_source_candidate_manifest["indexed_user_count"],
        "candidate_user_count": per_source_candidate_manifest["candidate_user_count"],
        "candidate_total_count": per_source_candidate_manifest["candidate_total_count"],
        "row_count": per_source_candidate_manifest["row_count"],
        "peak_rss_mb": per_source_candidate_manifest["peak_rss_mb"],
        "underfilled_user_coverage": per_source_candidate_manifest["underfilled_user_coverage"],
        "marginal_candidate_share": per_source_candidate_manifest["marginal_candidate_share"],
    }
    deterministic_payload["index_manifest_sha256"] = source_index_signature["sha256"]
    deterministic_payload["output_manifest_sha256"] = selection_manifest_signature["sha256"]
    deterministic_payload["per_source_candidate_manifest_sha256"] = per_source_candidate_signature["sha256"]
    deterministic_payload["candidate_shards_sha256"] = hashlib.sha256(
        json.dumps(candidate_shard_signatures, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    deterministic_payload["manifest_sha256"] = hashlib.sha256(
        json.dumps(deterministic_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": f"{SCHEMA_VERSION}.readiness_contract",
        **deterministic_payload,
        "runtime_metadata": {
            "generated_at": source_index_manifest.get("generated_at"),
            "runtime_seconds": source_index_manifest.get("runtime_seconds"),
        },
    }


def _eligible_quality_summary(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"manifest_used": False}
    profiles = payload.get("profiles") or []
    buckets = Counter(str(profile.get("quality_bucket", "")) for profile in profiles if isinstance(profile, dict))
    return {
        "manifest_used": True,
        "scope": payload.get("scope"),
        "limit_users": payload.get("limit_users"),
        "profile_count": len(profiles),
        "bucket_counts": dict(sorted(buckets.items())),
    }


def _sample_memory(samples: list[dict[str, Any]], stage: str) -> None:
    rss_mb = _current_rss_mb()
    free_memory_bytes = _available_memory_bytes()
    samples.append({"stage": stage, "rss_mb": rss_mb, "free_memory_bytes": free_memory_bytes})


def _enforce_memory_guard(samples: list[dict[str, Any]], *, max_rss_mb: int, min_free_memory_bytes: int) -> None:
    latest = samples[-1] if samples else {"rss_mb": 0, "free_memory_bytes": None}
    rss_mb = latest.get("rss_mb") or 0
    if rss_mb and rss_mb > max_rss_mb:
        raise RuntimeError(f"RSS memory guard exceeded: {rss_mb}MB > {max_rss_mb}MB")
    free_memory_bytes = latest.get("free_memory_bytes")
    if min_free_memory_bytes and free_memory_bytes is not None and free_memory_bytes < min_free_memory_bytes:
        raise RuntimeError(f"Free memory guard exceeded: {free_memory_bytes} < {min_free_memory_bytes}")


def _current_rss_mb() -> int:
    try:
        import psutil  # type: ignore

        return int(psutil.Process().memory_info().rss / (1024 * 1024))
    except Exception:
        pass
    try:
        import resource

        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return int(rss / (1024 * 1024))
        return int(rss / 1024)
    except Exception:
        return 0


def _available_memory_bytes() -> int | None:
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().available)
    except Exception:
        return None


def _stable_shard_id(value: str, shard_count: int) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % shard_count


def _source_signature(path: Path) -> dict[str, Any]:
    signature = _file_signature(path)
    signature["field"] = "recent_positive_item_sequence"
    return signature


def main() -> None:
    args = parse_args()
    build_full_train_usercf_sidecar(
        clean_manifest=Path(args.clean_manifest),
        output_dir=Path(args.output_dir),
        eligible_user_quality_manifest=Path(args.eligible_user_quality_manifest) if args.eligible_user_quality_manifest else None,
        include_medium_behavior=args.include_medium_behavior,
        max_items_per_user=args.max_items_per_user,
        max_item_user_freq=args.max_item_user_freq,
        similar_users_top_k=args.similar_users_top_k,
        candidate_top_k_per_user=args.candidate_top_k_per_user,
        shard_count=args.shard_count,
        target_user_limit=args.target_user_limit,
        target_batch_size=args.target_batch_size,
        min_free_bytes=args.min_free_bytes,
        min_free_memory_bytes=args.min_free_memory_bytes,
        max_rss_mb=args.max_rss_mb,
        resume=args.resume,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )


if __name__ == "__main__":
    main()
