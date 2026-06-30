from __future__ import annotations

import hashlib
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, Iterable

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS

ROOT = Path(__file__).resolve().parents[6]
SOURCE = "category"
SCHEMA_VERSION = "pool500_recent2y_category_source_v1"
DEFAULT_DATASET_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_CLEAN_MANIFEST = DEFAULT_DATASET_ROOT / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = DEFAULT_DATASET_ROOT / "recall_views" / "manifest.json"
DEFAULT_GOVERNANCE_MANIFEST = DEFAULT_DATASET_ROOT / "train_only_governance" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources" / "recent_2y"
ALLOWED_USER_BUCKETS = {"fallback_only", "medium_behavior", "sequence_sufficient", "collaborative_rich"}
FORBIDDEN_PATH_PARTS = {"holdout", "valid", "test", "lopo", "clean_10000", "pool1000", "oracle", "eval_label"}
GOVERNANCE_FIELDS = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
}


def build_category_method_source(*, config: dict[str, Any], run_id: str, output_dir: Path, overwrite: bool) -> dict[str, Any]:
    started = perf_counter()
    if bool(config.get("enforce_venv", True)):
        enforce_project_venv(ROOT)
    _precheck_output(output_dir, overwrite)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    scale_tier = str(config.get("tier") or method_config.get("scale_tier") or "smoke")

    clean_manifest_path = _config_path(input_contract, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path")
    views_manifest_path = _config_path(input_contract, DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST, "lightweight_views_manifest", "lightweight_views_manifest_path")
    governance_manifest_path = _config_path(input_contract, DEFAULT_GOVERNANCE_MANIFEST, "governance_manifest", "governance_manifest_path")

    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(views_manifest_path)
    governance_manifest = read_json(governance_manifest_path)
    _assert_train_only_governance(governance_manifest)

    train_sequences_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    canonical_items_path = _resolve_repo_path(clean_manifest["canonical_items_path"])
    user_quality_profile_path = _resolve_repo_path(governance_manifest["artifacts"]["user_quality_profile"])
    item_frequency_path = _resolve_repo_path(governance_manifest["artifacts"]["item_frequency_train"])
    view_outputs = views_manifest.get("outputs") if isinstance(views_manifest.get("outputs"), dict) else {}
    category_top_items_path = _resolve_repo_path(view_outputs["category_top_items"])
    category_recall_items_path = _resolve_repo_path(view_outputs["category_recall_items"])

    limit_users = 0 if scale_tier == "all_eligible" else _limit_users(method_config.get("limit_users"), 500 if scale_tier == "smoke" else 50000)
    per_user = int(method_config.get("per_user", 40 if scale_tier == "smoke" else 80))
    seed_window = int(method_config.get("seed_window", 20))
    max_profile_buckets = int(method_config.get("max_profile_buckets", 6))
    per_bucket_cap = int(method_config.get("category_bucket_cap_per_user", method_config.get("per_bucket_cap", 20)))
    min_bucket_items = int(method_config.get("category_min_item_count", 5))
    fallback_bucket_count = int(method_config.get("fallback_bucket_count", 8))
    include_path_categories = bool(method_config.get("include_path_categories", True))
    allowed_buckets = set(method_config.get("eligible_user_buckets") or sorted(ALLOWED_USER_BUCKETS))
    candidate_materialization = "none" if scale_tier == "all_eligible" else _candidate_materialization_mode(method_config)

    input_paths = [
        clean_manifest_path,
        views_manifest_path,
        governance_manifest_path,
        train_sequences_path,
        canonical_items_path,
        user_quality_profile_path,
        item_frequency_path,
        category_top_items_path,
        category_recall_items_path,
    ]
    no_holdout_audit = _no_holdout_audit(input_paths)
    if no_holdout_audit["status"] != "PASS":
        raise ValueError(f"forbidden input path detected: {no_holdout_audit['forbidden_inputs']}")

    user_quality = _load_target_user_quality(user_quality_profile_path, allowed_buckets, limit_users)
    target_user_ids = list(user_quality)
    if not target_user_ids:
        raise ValueError("no target users selected for category source")

    bucket_top_items, bucket_stats = _load_category_top_items(category_top_items_path, min_bucket_items)
    fallback_buckets = _global_fallback_buckets(bucket_top_items, fallback_bucket_count)
    candidates_path = output_dir / "candidates.jsonl"
    profile_path = output_dir / "user_category_profile.jsonl"
    eligible_users_path = output_dir / "eligible_users.jsonl"
    category_top_items_index_path = output_dir / "category_top_items_index.jsonl"
    _write_category_top_items_index(category_top_items_index_path, bucket_top_items, min_bucket_items)

    target_user_count = len(target_user_ids)
    candidates = []
    candidate_row_count = 0
    if candidate_materialization == "full":
        sequence_rows = _load_target_sequences(train_sequences_path, set(target_user_ids), limit_users)
        sequence_by_user = {str(row.get("user_id")): row for row in sequence_rows}
        item_categories = _load_item_categories(category_recall_items_path, _seed_item_ids_from_sequences(sequence_rows, seed_window))
        profile_rows = []
        undercovered_reasons: dict[str, str] = {}
        for user_id in target_user_ids:
            sequence = sequence_by_user.get(user_id, {"user_id": user_id, "recent_item_sequence": [], "recent_positive_item_sequence": []})
            profile = _category_profile(
                sequence,
                item_categories,
                seed_window=seed_window,
                max_profile_buckets=max_profile_buckets,
                include_path_categories=include_path_categories,
            )
            profile_rows.append(_profile_row(user_id, user_quality[user_id], profile, sequence, seed_window))
            rows, reason = _candidate_rows_for_user(
                user_id=user_id,
                sequence=sequence,
                profile=profile,
                user_quality=user_quality[user_id],
                bucket_top_items=bucket_top_items,
                fallback_buckets=fallback_buckets,
                per_user=per_user,
                per_bucket_cap=per_bucket_cap,
            )
            candidates.extend(rows)
            if reason:
                undercovered_reasons[user_id] = reason
        write_jsonl(candidates_path, candidates)
        write_jsonl(profile_path, profile_rows)
        write_jsonl(eligible_users_path, (_eligible_user_row(row["user_id"], user_quality[row["user_id"]], row.get("top_profile_buckets") or [], sequence_by_user.get(row["user_id"], {})) for row in profile_rows))
        candidate_row_count = len(candidates)
        per_user_counts = _counts_by_user(candidates, target_user_ids)
        coverage_audit = _coverage_audit(
            candidates=candidates,
            target_user_ids=target_user_ids,
            per_user_counts=per_user_counts,
            user_quality=user_quality,
            bucket_stats=bucket_stats,
            profile_rows=profile_rows,
            scale_tier=scale_tier,
            per_user=per_user,
            per_bucket_cap=per_bucket_cap,
            min_bucket_items=min_bucket_items,
        )
        undercoverage_audit = _undercoverage_audit(target_user_ids, per_user_counts, undercovered_reasons, per_user)
    else:
        candidates_path = None
        coverage_audit, undercoverage_audit = _build_index_only_audits(
            train_sequences_path=train_sequences_path,
            category_recall_items_path=category_recall_items_path,
            target_user_ids=target_user_ids,
            user_quality=user_quality,
            fallback_buckets=fallback_buckets,
            profile_path=profile_path,
            eligible_users_path=eligible_users_path,
            bucket_stats=bucket_stats,
            scale_tier=scale_tier,
            seed_window=seed_window,
            max_profile_buckets=max_profile_buckets,
            include_path_categories=include_path_categories,
            per_user=per_user,
            per_bucket_cap=per_bucket_cap,
            min_bucket_items=min_bucket_items,
        )
    source_signatures = {
        "clean_manifest": _file_signature(clean_manifest_path),
        "lightweight_views_manifest": _file_signature(views_manifest_path),
        "governance_manifest": _file_signature(governance_manifest_path),
        "train_user_sequences": _file_signature(train_sequences_path),
        "canonical_items": _file_signature(canonical_items_path),
        "user_quality_profile": _file_signature(user_quality_profile_path),
        "item_frequency_train": _file_signature(item_frequency_path),
        "category_top_items": _file_signature(category_top_items_path),
        "category_recall_items": _file_signature(category_recall_items_path),
        "eligible_users": _file_signature(eligible_users_path),
        "user_category_profile": _file_signature(profile_path),
        "category_top_items_index": _file_signature(category_top_items_index_path),
    }
    if candidates_path is not None:
        source_signatures["candidates"] = _file_signature(candidates_path)
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "scale_tier": scale_tier,
        "heavy_job": False,
        "checkpoint_enabled": True,
        "resource_profile": "recent_2y_train_only_category_index" if candidate_materialization == "none" else "recent_2y_train_only_category_materialized_candidates",
        "runtime_seconds": round(perf_counter() - started, 6),
        "target_user_count": target_user_count,
        "candidate_materialization": candidate_materialization,
        "candidate_row_count": candidate_row_count,
        "profile_row_count": target_user_count,
        "config": {
            "limit_users": "all" if limit_users <= 0 else limit_users,
            "per_user": per_user,
            "seed_window": seed_window,
            "max_profile_buckets": max_profile_buckets,
            "category_bucket_cap_per_user": per_bucket_cap,
            "category_min_item_count": min_bucket_items,
            "fallback_bucket_count": fallback_bucket_count,
            "include_path_categories": include_path_categories,
            "eligible_user_buckets": sorted(allowed_buckets),
        },
        "source_signatures": source_signatures,
        **GOVERNANCE_FIELDS,
    }
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": "SMOKE_SCHEMA_VALIDATION_ONLY" if scale_tier == "smoke" else ("READY_RECENT2Y_TRAIN_ONLY_CATEGORY_INDEX_FORMAL" if candidate_materialization == "none" else "READY_RECENT2Y_TRAIN_ONLY_CATEGORY_FORMAL"),
        "run_id": run_id,
        "scale_tier": scale_tier,
        "purpose": "program_and_schema_validation_only" if scale_tier == "smoke" else "official_method_index_dataset_under_recent_2y_train_only_governance",
        "created_at": _utc_now(),
        "output_dir": str(output_dir),
        "train_only": True,
        "dataset_root": str(DEFAULT_DATASET_ROOT),
        "declared_input_paths": [str(path) for path in input_paths],
        "input_lineage": {
            "clean_manifest_path": str(clean_manifest_path),
            "lightweight_views_manifest_path": str(views_manifest_path),
            "governance_manifest_path": str(governance_manifest_path),
            "train_user_sequences_path": str(train_sequences_path),
            "canonical_items_path": str(canonical_items_path),
            "category_top_items_path": str(category_top_items_path),
            "category_recall_items_path": str(category_recall_items_path),
        },
        "eligible_users_path": str(eligible_users_path),
        "user_category_profile_path": str(profile_path),
        "category_top_items_index_path": str(category_top_items_index_path),
        "candidate_materialization": candidate_materialization,
        "candidates_path": str(candidates_path) if candidates_path is not None else None,
        "candidate_row_count": candidate_row_count,
        "target_user_count": target_user_count,
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "unique_item_count": coverage_audit["unique_item_count"],
        "source_signatures": source_signatures,
        **GOVERNANCE_FIELDS,
    }
    source_index_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.source_index_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": method_dataset_manifest["source_status"],
        "readiness": "READY" if scale_tier in {"formal", "all_eligible"} and coverage_audit["user_coverage_ratio"] >= 0.95 else "DIAGNOSTIC_ONLY",
        "run_id": run_id,
        "scale_tier": scale_tier,
        "created_at": method_dataset_manifest["created_at"],
        "output_dir": str(output_dir),
        "index_scope": "RECENT2Y_TRAIN_ONLY_CATEGORY_BUCKET_INDEX",
        "train_only": True,
        "method_dataset_manifest_path": str(output_dir / "method_dataset_manifest.json"),
        "source_index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "eligible_users_path": str(eligible_users_path),
        "user_category_profile_path": str(profile_path),
        "category_top_items_index_path": str(category_top_items_index_path),
        "candidate_materialization": candidate_materialization,
        "candidates_path": str(candidates_path) if candidates_path is not None else None,
        "candidate_row_count": candidate_row_count,
        "target_user_count": target_user_count,
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "unique_item_count": coverage_audit["unique_item_count"],
        "per_user_candidate_count": coverage_audit.get("per_user_candidate_count"),
        "required_artifacts": {name: str(output_dir / name) for name in _required_category_outputs(candidate_materialization)},
        "outputs": {
            "method_dataset_manifest": str(output_dir / "method_dataset_manifest.json"),
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "eligible_users": str(eligible_users_path),
            "user_category_profile": str(profile_path),
            "category_top_items_index": str(category_top_items_index_path),
            "coverage_audit": str(output_dir / "coverage_audit.json"),
            "undercoverage_audit": str(output_dir / "undercoverage_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
            **({"candidates": str(candidates_path)} if candidates_path is not None else {}),
        },
        "audit_statuses": {
            "coverage_audit": coverage_audit["status"],
            "undercoverage_audit": undercoverage_audit["status"],
            "resource_audit": resource_audit["status"],
            "no_holdout_audit": no_holdout_audit["status"],
            "method_dataset_manifest": method_dataset_manifest["status"],
        },
        "source_signatures": source_signatures,
        **GOVERNANCE_FIELDS,
    }

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    _assert_required_outputs(output_dir, _required_category_outputs(candidate_materialization))
    return source_index_manifest


def expand_category_candidates_for_users(
    *,
    source_index_manifest_path: Path,
    user_ids: Iterable[str],
    per_user: int | None = None,
    per_bucket_cap: int | None = None,
) -> list[dict[str, Any]]:
    source_index_manifest_path = _resolve_repo_path(source_index_manifest_path)
    source_manifest = read_json(source_index_manifest_path)
    if str(source_manifest.get("source") or "") != SOURCE:
        raise ValueError(f"source_index_manifest is not a {SOURCE} artifact: {source_index_manifest_path}")

    requested_user_ids = list(dict.fromkeys(str(user_id) for user_id in user_ids if str(user_id)))
    if not requested_user_ids:
        return []
    requested_user_set = set(requested_user_ids)
    outputs = source_manifest.get("outputs") if isinstance(source_manifest.get("outputs"), dict) else {}
    eligible_users_path = _manifest_path(source_manifest, outputs, "eligible_users_path", "eligible_users")
    profile_path = _manifest_path(source_manifest, outputs, "user_category_profile_path", "user_category_profile")
    category_top_items_index_path = _manifest_path(source_manifest, outputs, "category_top_items_index_path", "category_top_items_index")
    method_manifest_path = _manifest_path(source_manifest, outputs, "method_dataset_manifest_path", "method_dataset_manifest")
    method_manifest = read_json(method_manifest_path)
    input_lineage = method_manifest.get("input_lineage") if isinstance(method_manifest.get("input_lineage"), dict) else {}
    train_sequences_path = _resolve_repo_path(input_lineage.get("train_user_sequences_path") or method_manifest.get("train_user_sequences_path"))

    effective_per_user = int(per_user if per_user is not None else _manifest_config_value(source_manifest, method_manifest, "per_user", 80))
    effective_per_bucket_cap = int(per_bucket_cap if per_bucket_cap is not None else _manifest_config_value(source_manifest, method_manifest, "category_bucket_cap_per_user", 20))
    fallback_buckets = _manifest_fallback_buckets(outputs)
    if not fallback_buckets:
        fallback_buckets = _global_fallback_buckets_from_index(category_top_items_index_path, int(_manifest_config_value(source_manifest, method_manifest, "fallback_bucket_count", 8)))

    user_quality = _load_index_user_quality(eligible_users_path, requested_user_set)
    profiles = _load_index_user_profiles(profile_path, requested_user_set)
    sequences = _load_index_user_sequences(train_sequences_path, requested_user_set)
    bucket_top_items = _load_category_top_items_from_index(category_top_items_index_path)

    rows: list[dict[str, Any]] = []
    for user_id in requested_user_ids:
        if user_id not in user_quality:
            continue
        user_rows, _ = _candidate_rows_for_user(
            user_id=user_id,
            sequence=sequences.get(user_id, {"user_id": user_id, "recent_item_sequence": [], "recent_positive_item_sequence": []}),
            profile=profiles.get(user_id, []),
            user_quality=user_quality[user_id],
            bucket_top_items=bucket_top_items,
            fallback_buckets=fallback_buckets,
            per_user=effective_per_user,
            per_bucket_cap=effective_per_bucket_cap,
        )
        rows.extend(user_rows)
    return rows


def _manifest_path(source_manifest: dict[str, Any], outputs: dict[str, Any], manifest_key: str, output_key: str) -> Path:
    value = source_manifest.get(manifest_key) or outputs.get(output_key)
    if not value:
        raise ValueError(f"source_index_manifest missing {manifest_key}/{output_key}")
    return _resolve_repo_path(value)


def _manifest_config_value(source_manifest: dict[str, Any], method_manifest: dict[str, Any], key: str, default: Any) -> Any:
    outputs = source_manifest.get("outputs") if isinstance(source_manifest.get("outputs"), dict) else {}
    resource_path = outputs.get("resource_audit")
    if resource_path:
        resource_audit = read_json(_resolve_repo_path(resource_path))
        config = resource_audit.get("config") if isinstance(resource_audit.get("config"), dict) else {}
        if key in config:
            return config[key]
    config = source_manifest.get("config") if isinstance(source_manifest.get("config"), dict) else {}
    if key in config:
        return config[key]
    config = method_manifest.get("config") if isinstance(method_manifest.get("config"), dict) else {}
    return config.get(key, default)


def _manifest_fallback_buckets(outputs: dict[str, Any]) -> list[str]:
    coverage_path = outputs.get("coverage_audit") if outputs else None
    if not coverage_path:
        return []
    coverage_audit = read_json(_resolve_repo_path(coverage_path))
    fallback_usage = coverage_audit.get("fallback_usage") if isinstance(coverage_audit.get("fallback_usage"), dict) else {}
    return [str(bucket) for bucket in fallback_usage.get("fallback_buckets") or [] if bucket]


def _load_index_user_quality(path: Path, target_user_ids: set[str]) -> dict[str, dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id not in target_user_ids:
            continue
        users[user_id] = {
            "quality_bucket": row.get("quality_bucket"),
            "sequence_len": int(row.get("sequence_len") or 0),
            "positive_count": int(row.get("positive_count") or 0),
            "unique_item_count": int(row.get("unique_item_count") or 0),
        }
        if len(users) >= len(target_user_ids):
            break
    return users


def _load_index_user_profiles(path: Path, target_user_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    profiles: dict[str, list[dict[str, Any]]] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id not in target_user_ids:
            continue
        profiles[user_id] = [dict(bucket) for bucket in row.get("top_profile_buckets") or []]
        if len(profiles) >= len(target_user_ids):
            break
    return profiles


def _load_index_user_sequences(path: Path, target_user_ids: set[str]) -> dict[str, dict[str, Any]]:
    sequences: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id not in target_user_ids:
            continue
        sequences[user_id] = row
        if len(sequences) >= len(target_user_ids):
            break
    return sequences


def _load_category_top_items_from_index(path: Path) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in iter_jsonl(path):
        bucket = str(row.get("bucket") or "")
        if bucket:
            buckets[bucket] = [dict(item) for item in row.get("top_items") or []]
    return buckets


def _global_fallback_buckets_from_index(path: Path, limit: int) -> list[str]:
    bucket_top_items = _load_category_top_items_from_index(path)
    return _global_fallback_buckets(bucket_top_items, limit)


def _limit_users(value: Any, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"all", "none", "null", "unlimited"}:
            return 0
        return int(normalized)
    return int(value)


def _candidate_materialization_mode(method_config: dict[str, Any]) -> str:
    value = method_config.get("candidate_materialization")
    if value is None:
        value = "full" if bool(method_config.get("materialize_candidates", True)) else "none"
    mode = str(value).strip().lower()
    if mode not in {"full", "none"}:
        raise ValueError(f"unsupported candidate_materialization: {value}; expected full or none")
    return mode


def _required_category_outputs(candidate_materialization: str) -> tuple[str, ...]:
    base = (
        "method_dataset_manifest.json",
        "source_index_manifest.json",
        "eligible_users.jsonl",
        "user_category_profile.jsonl",
        "category_top_items_index.jsonl",
        "coverage_audit.json",
        "undercoverage_audit.json",
        "resource_audit.json",
        "no_holdout_audit.json",
    )
    if candidate_materialization == "full":
        return (*base[:2], "candidates.jsonl", *base[2:])
    return base


def _write_jsonl_record(handle: Any, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_category_top_items_index(path: Path, bucket_top_items: dict[str, list[dict[str, Any]]], min_bucket_items: int) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for bucket, items in sorted(bucket_top_items.items()):
            _write_jsonl_record(handle, {"bucket": bucket, "top_items": items, "item_count": len(items), "category_min_item_count": min_bucket_items, "train_only": True})


def _quality_bucket(quality: Any) -> str:
    if isinstance(quality, tuple):
        return str(quality[0] if len(quality) > 0 else "UNKNOWN")
    return str((quality or {}).get("quality_bucket") or "UNKNOWN")


def _quality_sequence_len(quality: Any) -> int:
    if isinstance(quality, tuple):
        return int(quality[1] if len(quality) > 1 else 0)
    return int((quality or {}).get("sequence_len") or 0)


def _quality_positive_count(quality: Any) -> int:
    if isinstance(quality, tuple):
        return int(quality[2] if len(quality) > 2 else 0)
    return int((quality or {}).get("positive_count") or 0)


def _quality_unique_item_count(quality: Any) -> int:
    if isinstance(quality, tuple):
        return int(quality[3] if len(quality) > 3 else 0)
    return int((quality or {}).get("unique_item_count") or 0)


def _eligible_user_row(user_id: str, quality: Any, profile: list[dict[str, Any]], sequence: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "quality_bucket": _quality_bucket(quality),
        "sequence_len": _quality_sequence_len(quality),
        "positive_count": _quality_positive_count(quality),
        "unique_item_count": _quality_unique_item_count(quality),
        "profile_bucket_count": len(profile),
        "has_train_sequence": bool(sequence.get("recent_item_sequence") or sequence.get("recent_positive_item_sequence")),
        "train_only": True,
    }


def _build_index_only_audits(
    *,
    train_sequences_path: Path,
    category_recall_items_path: Path,
    target_user_ids: list[str],
    user_quality: dict[str, dict[str, Any]],
    fallback_buckets: list[str],
    profile_path: Path,
    eligible_users_path: Path,
    bucket_stats: dict[str, Any],
    scale_tier: str,
    seed_window: int,
    max_profile_buckets: int,
    include_path_categories: bool,
    per_user: int,
    per_bucket_cap: int,
    min_bucket_items: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_user_set = set(target_user_ids)
    seen_for_seed: set[str] = set()
    seed_item_ids: set[str] = set()
    for row in iter_jsonl(train_sequences_path):
        user_id = str(row.get("user_id") or "")
        if user_id not in target_user_set:
            continue
        seen_for_seed.add(user_id)
        seed_item_ids.update(_seed_item_ids_from_sequence(row, seed_window))
        if len(seen_for_seed) >= len(target_user_set):
            break
    item_categories = _load_item_categories(category_recall_items_path, seed_item_ids)
    profile_bucket_counts: list[int] = []
    empty_profile_users: list[str] = []
    bucket_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: {"target_user_count": 0, "index_ready_user_count": 0})

    def process_user(user_id: str, sequence: dict[str, Any], profile_handle: Any, eligible_handle: Any) -> None:
        profile = _category_profile(
            sequence,
            item_categories,
            seed_window=seed_window,
            max_profile_buckets=max_profile_buckets,
            include_path_categories=include_path_categories,
        )
        quality = user_quality[user_id]
        _write_jsonl_record(profile_handle, _profile_row(user_id, quality, profile, sequence, seed_window))
        _write_jsonl_record(eligible_handle, _eligible_user_row(user_id, quality, profile, sequence))
        profile_bucket_counts.append(len(profile))
        bucket = str(_quality_bucket(quality) or "UNKNOWN")
        bucket_breakdown[bucket]["target_user_count"] += 1
        if profile or fallback_buckets:
            bucket_breakdown[bucket]["index_ready_user_count"] += 1
        if not profile:
            empty_profile_users.append(user_id)

    processed_users: set[str] = set()
    with profile_path.open("w", encoding="utf-8") as profile_handle, eligible_users_path.open("w", encoding="utf-8") as eligible_handle:
        for row in iter_jsonl(train_sequences_path):
            user_id = str(row.get("user_id") or "")
            if user_id not in target_user_set:
                continue
            processed_users.add(user_id)
            process_user(user_id, row, profile_handle, eligible_handle)
            if len(processed_users) >= len(target_user_set):
                break
        for user_id in target_user_ids:
            if user_id not in processed_users:
                process_user(user_id, {"user_id": user_id, "recent_item_sequence": [], "recent_positive_item_sequence": []}, profile_handle, eligible_handle)

    index_ready_user_count = sum(values["index_ready_user_count"] for values in bucket_breakdown.values())
    coverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "scale_tier": scale_tier,
        "coverage_definition": "index_ready_users_with_category_profile_or_train_only_fallback_bucket; candidates are generated on demand and not materialized",
        "target_user_count": len(target_user_ids),
        "candidate_materialization": "none",
        "candidate_row_count": 0,
        "unique_item_count": 0,
        "user_coverage_count": index_ready_user_count,
        "user_coverage_ratio": _ratio(index_ready_user_count, len(target_user_ids)),
        "per_user_candidate_count": None,
        "category_bucket_stats": bucket_stats,
        "category_diversity": {
            "per_user_distinct_category_count": None,
            "per_user_max_category_share": None,
            "category_bucket_cap_per_user": per_bucket_cap,
            "category_min_item_count": min_bucket_items,
            "computed_after_candidate_materialization": True,
        },
        "profile_quality": {
            "per_user_profile_bucket_count": _summary(profile_bucket_counts),
            "empty_profile_user_count": len(empty_profile_users),
            "empty_profile_user_sample": empty_profile_users[:20],
        },
        "fallback_usage": {
            "fallback_index_ready_user_count": len(empty_profile_users) if fallback_buckets else 0,
            "fallback_buckets": fallback_buckets,
            "definition": "profile empty or item category unresolved; generator backs off to train-only global main-category buckets",
        },
        "user_bucket_breakdown": {bucket: {**values, "coverage_ratio": _ratio(values["index_ready_user_count"], values["target_user_count"])} for bucket, values in sorted(bucket_breakdown.items())},
        "target_per_user": per_user,
        **GOVERNANCE_FIELDS,
    }
    undercoverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "source": SOURCE,
        "target_user_count": len(target_user_ids),
        "target_per_user": per_user,
        "empty_user_count": len(target_user_ids) - index_ready_user_count,
        "under_target_user_count": 0,
        "empty_user_sample": [],
        "under_target_user_sample": [],
        "reason_counts": {} if fallback_buckets else {"no_profile_and_no_fallback_bucket": len(empty_profile_users)},
        **GOVERNANCE_FIELDS,
    }
    return coverage_audit, undercoverage_audit


def _assert_train_only_governance(manifest: dict[str, Any]) -> None:
    if not manifest.get("train_only") or manifest.get("valid_used") or manifest.get("test_used") or manifest.get("holdout_used") or manifest.get("lopo_used"):
        raise ValueError("governance manifest is not train-only clean")


def _load_target_user_quality(path: Path, allowed_buckets: set[str], limit_users: int) -> dict[str, dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        bucket = str(row.get("quality_bucket_v2") or row.get("quality_bucket") or "")
        if bucket not in allowed_buckets:
            continue
        user_id = str(row.get("user_id") or "")
        if not user_id:
            continue
        users[user_id] = (bucket, int(row.get("sequence_len") or 0), int(row.get("positive_count") or 0), int(row.get("unique_item_count") or 0))
        if limit_users > 0 and len(users) >= limit_users:
            break
    return users


def _load_item_categories(path: Path, target_item_ids: set[str] | None = None) -> dict[str, tuple[str, ...]]:
    items: dict[str, tuple[str, ...]] = {}
    remaining = set(target_item_ids or [])
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if not item_id:
            continue
        if target_item_ids is not None and item_id not in remaining:
            continue
        main_category = _clean_category(row.get("main_category"))
        categories_flat = [_clean_category(value) for value in row.get("categories_flat") or [] if _clean_category(value)]
        buckets = []
        if main_category:
            buckets.append(sys.intern(f"main::{main_category}"))
        for category in categories_flat:
            buckets.append(sys.intern(f"path::{category}"))
        items[item_id] = tuple(dict.fromkeys(buckets))
        if target_item_ids is not None:
            remaining.discard(item_id)
            if not remaining:
                break
    return items


def _load_category_top_items(path: Path, min_bucket_items: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    raw_bucket_count = 0
    dropped_sparse = 0
    for row in iter_jsonl(path):
        raw_bucket_count += 1
        bucket = str(row.get("bucket") or "")
        items = [dict(item) for item in row.get("top_items") or [] if item.get("parent_asin")]
        if len(items) < min_bucket_items:
            dropped_sparse += 1
            continue
        buckets[bucket] = sorted(items, key=lambda item: (-float(item.get("score") or 0), -float(item.get("recent_pop_score") or 0), str(item.get("parent_asin"))))
    return buckets, {"raw_bucket_count": raw_bucket_count, "retained_bucket_count": len(buckets), "dropped_sparse_bucket_count": dropped_sparse, "category_min_item_count": min_bucket_items}


def _global_fallback_buckets(bucket_top_items: dict[str, list[dict[str, Any]]], limit: int) -> list[str]:
    scored = []
    for bucket, items in bucket_top_items.items():
        if not bucket.startswith("main::"):
            continue
        score = sum(float(item.get("score") or 0.0) for item in items[:10])
        scored.append((score, bucket))
    return [bucket for _, bucket in sorted(scored, reverse=True)[:limit]]


def _seed_item_ids_from_sequence(sequence: dict[str, Any], seed_window: int) -> set[str]:
    positives = [str(item) for item in sequence.get("recent_positive_item_sequence") or [] if item]
    seeds = positives[-seed_window:] if positives else [str(item) for item in (sequence.get("recent_item_sequence") or [])[-seed_window:] if item]
    return set(seeds)


def _seed_item_ids_from_sequences(sequences: list[dict[str, Any]], seed_window: int) -> set[str]:
    seed_item_ids: set[str] = set()
    for sequence in sequences:
        seed_item_ids.update(_seed_item_ids_from_sequence(sequence, seed_window))
    return seed_item_ids


def _load_target_sequences(path: Path, target_user_ids: set[str], limit_users: int) -> list[dict[str, Any]]:
    rows = []
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id not in target_user_ids:
            continue
        rows.append(row)
        if limit_users > 0 and len(rows) >= len(target_user_ids):
            break
    return rows


def _category_profile(
    sequence: dict[str, Any],
    item_categories: dict[str, tuple[str, ...]],
    *,
    seed_window: int,
    max_profile_buckets: int,
    include_path_categories: bool,
) -> list[dict[str, Any]]:
    positives = [str(item) for item in sequence.get("recent_positive_item_sequence") or [] if item]
    seeds = positives[-seed_window:] if positives else [str(item) for item in (sequence.get("recent_item_sequence") or [])[-seed_window:] if item]
    counter: Counter[str] = Counter()
    seed_hits: Counter[str] = Counter()
    for offset, item_id in enumerate(reversed(seeds), start=1):
        buckets = list(item_categories.get(item_id) or ())
        if not include_path_categories:
            buckets = [bucket for bucket in buckets if bucket.startswith("main::")]
        weight = 1.0 / math.sqrt(offset)
        for bucket in buckets:
            counter[bucket] += weight
            seed_hits[bucket] += 1
    total_weight = sum(counter.values())
    profile = []
    for rank, (bucket, weight) in enumerate(counter.most_common(max_profile_buckets), start=1):
        profile.append({"bucket": bucket, "weight": round(weight, 6), "share": round(weight / total_weight, 6) if total_weight else 0.0, "seed_hit_count": seed_hits[bucket], "rank": rank})
    return profile


def _profile_row(user_id: str, quality: Any, profile: list[dict[str, Any]], sequence: dict[str, Any], seed_window: int) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "quality_bucket": _quality_bucket(quality),
        "sequence_len": _quality_sequence_len(quality),
        "positive_count": _quality_positive_count(quality),
        "seed_window": seed_window,
        "seed_item_count": len(sequence.get("recent_positive_item_sequence") or sequence.get("recent_item_sequence") or []),
        "profile_bucket_count": len(profile),
        "top_profile_buckets": profile,
    }


def _candidate_rows_for_user(
    *,
    user_id: str,
    sequence: dict[str, Any],
    profile: list[dict[str, Any]],
    user_quality: dict[str, Any],
    bucket_top_items: dict[str, list[dict[str, Any]]],
    fallback_buckets: list[str],
    per_user: int,
    per_bucket_cap: int,
) -> tuple[list[dict[str, Any]], str | None]:
    seen = set(str(item) for item in sequence.get("recent_item_sequence") or [])
    seen.update(str(item) for item in sequence.get("recent_positive_item_sequence") or [])
    buckets = profile if profile else [{"bucket": bucket, "weight": 0.5, "share": 0.0, "rank": idx + 1, "seed_hit_count": 0} for idx, bucket in enumerate(fallback_buckets)]
    fallback_reason = None if profile else "empty_or_unresolved_category_profile"
    rows = []
    used_items = set(seen)
    bucket_counts: Counter[str] = Counter()
    for profile_bucket in buckets:
        bucket = str(profile_bucket["bucket"])
        candidates = bucket_top_items.get(bucket) or []
        if not candidates:
            continue
        for item in candidates:
            if len(rows) >= per_user:
                break
            if bucket_counts[bucket] >= per_bucket_cap:
                break
            item_id = str(item.get("parent_asin") or "")
            if not item_id or item_id in used_items:
                continue
            base_score = float(item.get("score") or 0.0)
            recent_score = float(item.get("recent_pop_score") or 0.0)
            profile_weight = float(profile_bucket.get("weight") or 0.0)
            score = base_score * (1.0 + profile_weight) + 0.01 * recent_score
            used_items.add(item_id)
            bucket_counts[bucket] += 1
            rows.append({
                "user_id": user_id,
                "item_id": item_id,
                "source": SOURCE,
                "canonical_source": SOURCE,
                "sources": [SOURCE],
                "score": round(score, 6),
                "rank": 0,
                "metadata": {
                    "parent_asin": item_id,
                    "category_bucket": bucket,
                    "profile_bucket_rank": int(profile_bucket.get("rank") or 0),
                    "profile_bucket_weight": profile_weight,
                    "profile_seed_hit_count": int(profile_bucket.get("seed_hit_count") or 0),
                    "base_category_pop_score": base_score,
                    "recent_pop_score": recent_score,
                    "quality_bucket": _quality_bucket(user_quality),
                    "fallback_reason": fallback_reason,
                    "source_scores": {SOURCE: round(score, 6)},
                },
            })
        if len(rows) >= per_user:
            break
    rows.sort(key=lambda row: (-float(row["score"]), str(row["item_id"])))
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    reason = None
    if not rows:
        reason = fallback_reason or "all_profile_buckets_missing_or_history_excluded"
    elif len(rows) < per_user:
        reason = "under_target_after_profile_and_history_filter"
    return rows, reason


def _coverage_audit(
    *,
    candidates: list[dict[str, Any]],
    target_user_ids: list[str],
    per_user_counts: dict[str, int],
    user_quality: dict[str, dict[str, Any]],
    bucket_stats: dict[str, Any],
    profile_rows: list[dict[str, Any]],
    scale_tier: str,
    per_user: int,
    per_bucket_cap: int,
    min_bucket_items: int,
) -> dict[str, Any]:
    user_coverage_count = sum(1 for count in per_user_counts.values() if count > 0)
    category_counts = Counter(str((row.get("metadata") or {}).get("category_bucket") or "UNKNOWN") for row in candidates)
    per_user_category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    fallback_rows = 0
    for row in candidates:
        user_id = str(row.get("user_id") or "")
        bucket = str((row.get("metadata") or {}).get("category_bucket") or "UNKNOWN")
        per_user_category_counts[user_id][bucket] += 1
        if (row.get("metadata") or {}).get("fallback_reason"):
            fallback_rows += 1
    bucket_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: {"target_user_count": 0, "covered_user_count": 0, "candidate_row_count": 0})
    for user_id, quality in user_quality.items():
        bucket = str(_quality_bucket(quality) or "UNKNOWN")
        bucket_breakdown[bucket]["target_user_count"] += 1
        if per_user_counts.get(user_id, 0) > 0:
            bucket_breakdown[bucket]["covered_user_count"] += 1
        bucket_breakdown[bucket]["candidate_row_count"] += per_user_counts.get(user_id, 0)
    distinct_category_counts = [len(per_user_category_counts[user_id]) for user_id in target_user_ids if per_user_counts.get(user_id, 0) > 0]
    max_category_shares = []
    for user_id in target_user_ids:
        total = per_user_counts.get(user_id, 0)
        if total > 0:
            max_category_shares.append(max(per_user_category_counts[user_id].values(), default=0) / total)
    profile_bucket_counts = [int(row.get("profile_bucket_count") or 0) for row in profile_rows]
    return {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "scale_tier": scale_tier,
        "target_user_count": len(target_user_ids),
        "candidate_row_count": len(candidates),
        "unique_item_count": len({str(row.get("item_id")) for row in candidates if row.get("item_id")}),
        "user_coverage_count": user_coverage_count,
        "user_coverage_ratio": _ratio(user_coverage_count, len(target_user_ids)),
        "per_user_candidate_count": _summary(list(per_user_counts.values())),
        "category_bucket_stats": bucket_stats,
        "category_bucket_count_in_candidates": len(category_counts),
        "category_bucket_top10": [{"bucket": bucket, "row_count": count, "share": _ratio(count, len(candidates))} for bucket, count in category_counts.most_common(10)],
        "category_diversity": {
            "per_user_distinct_category_count": _summary(distinct_category_counts),
            "per_user_max_category_share": _summary(max_category_shares),
            "users_single_category_only": sum(1 for value in distinct_category_counts if value == 1),
            "category_bucket_cap_per_user": per_bucket_cap,
            "category_min_item_count": min_bucket_items,
        },
        "profile_quality": {
            "per_user_profile_bucket_count": _summary(profile_bucket_counts),
            "empty_profile_user_count": sum(1 for value in profile_bucket_counts if value == 0),
        },
        "fallback_usage": {
            "fallback_candidate_row_count": fallback_rows,
            "fallback_candidate_share": _ratio(fallback_rows, len(candidates)),
            "definition": "profile empty or item category unresolved; backed off to train-only global main-category buckets",
        },
        "user_bucket_breakdown": {bucket: {**values, "coverage_ratio": _ratio(values["covered_user_count"], values["target_user_count"])} for bucket, values in sorted(bucket_breakdown.items())},
        "target_per_user": per_user,
        **GOVERNANCE_FIELDS,
    }


def _undercoverage_audit(target_user_ids: list[str], per_user_counts: dict[str, int], reasons: dict[str, str], per_user: int) -> dict[str, Any]:
    empty_users = [user_id for user_id in target_user_ids if per_user_counts.get(user_id, 0) <= 0]
    under_target_users = [user_id for user_id in target_user_ids if 0 < per_user_counts.get(user_id, 0) < per_user]
    reason_counts = Counter(reasons.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "source": SOURCE,
        "target_user_count": len(target_user_ids),
        "target_per_user": per_user,
        "empty_user_count": len(empty_users),
        "under_target_user_count": len(under_target_users),
        "empty_user_sample": empty_users[:20],
        "under_target_user_sample": under_target_users[:20],
        "reason_counts": dict(reason_counts),
        **GOVERNANCE_FIELDS,
    }


def _no_holdout_audit(input_paths: list[Path]) -> dict[str, Any]:
    forbidden = _forbidden_matches(input_paths)
    return {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS" if not forbidden else "BLOCKED",
        "source": SOURCE,
        "train_only": True,
        "read_files": [str(path) for path in input_paths],
        "forbidden_inputs": forbidden,
        "uses_holdout": False,
        "uses_valid": False,
        "uses_test": False,
        "uses_lopo": False,
        "uses_clean_10000": False,
        "uses_oracle": False,
        "uses_eval_label": False,
        **GOVERNANCE_FIELDS,
    }


def _counts_by_user(candidates: list[dict[str, Any]], target_user_ids: list[str]) -> dict[str, int]:
    counts = {user_id: 0 for user_id in target_user_ids}
    for row in candidates:
        user_id = str(row.get("user_id") or "")
        if user_id in counts:
            counts[user_id] += 1
    return counts


def _summary(values: list[int] | list[float]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    return {"min": ordered[0], "p50": median(ordered), "p90": ordered[int((len(ordered) - 1) * 0.9)], "max": ordered[-1]}


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _clean_category(value: Any) -> str:
    return str(value or "").strip()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_signature(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _forbidden_matches(paths: Iterable[Path]) -> list[str]:
    matches = []
    for path in paths:
        normalized = str(path).replace("\\", "/").lower()
        parts = [part for part in normalized.split("/") if part]
        if any(token in parts or f"_{token}_" in normalized or f".{token}." in normalized for token in FORBIDDEN_PATH_PARTS):
            matches.append(str(path))
    return sorted(set(matches))


def _precheck_output(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise ValueError(f"output already exists; pass --overwrite to replace: {output_dir}")
        shutil.rmtree(output_dir)


def _assert_required_outputs(output_dir: Path, required_outputs: tuple[str, ...] = REQUIRED_SOURCE_OUTPUTS) -> None:
    missing = [name for name in required_outputs if not (output_dir / name).exists()]
    if missing:
        raise ValueError(f"missing required outputs: {missing}")


def _config_path(config: dict[str, Any], default: Path, *keys: str) -> Path:
    for key in keys:
        value = config.get(key)
        if value:
            return _resolve_repo_path(value)
    return default.resolve()


def _resolve_repo_path(path: str | Path) -> Path:
    raw = str(path)
    normalized = raw.replace("\\", "/")
    marker = "/RS_agent/"
    if marker in normalized:
        normalized = normalized.split(marker, 1)[1]
    value = Path(normalized)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()
