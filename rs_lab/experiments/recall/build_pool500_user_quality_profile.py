from __future__ import annotations

import argparse
import hashlib
import json
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
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_user_quality_profile_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_user_quality" / "target500_train_only"
DEFAULT_LIMIT_USERS = 500
DEFAULT_MAX_ITEMS_PER_USER = 100
DEFAULT_MAX_ITEM_METADATA_ROWS = 0
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
    "holdout",
)
FORBIDDEN_INPUT_NAMES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)
BUCKET_THRESHOLDS = {
    "heavy_cf_eligible": {
        "positive_count_min": 20,
        "unique_item_count_min": 10,
        "category_count_min": 2,
        "shared_item_neighbor_count_min": 3,
    },
    "medium_behavior": {
        "positive_count_min": 5,
        "unique_item_count_min": 3,
        "category_count_min": 1,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build batch-scoped train-only pool500 user_quality profiling artifacts.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit-users", type=int, default=DEFAULT_LIMIT_USERS)
    parser.add_argument("--max-items-per-user", type=int, default=DEFAULT_MAX_ITEMS_PER_USER)
    parser.add_argument("--max-item-metadata-rows", type=int, default=DEFAULT_MAX_ITEM_METADATA_ROWS)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_user_quality_profile(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit_users: int = DEFAULT_LIMIT_USERS,
    max_items_per_user: int = DEFAULT_MAX_ITEMS_PER_USER,
    max_item_metadata_rows: int = DEFAULT_MAX_ITEM_METADATA_ROWS,
    min_free_bytes: int = 0,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    _validate_caps(limit_users, max_items_per_user, max_item_metadata_rows, min_free_bytes)

    clean_manifest_path = clean_manifest_path.resolve()
    output_dir = output_dir.resolve()
    _precheck_path(clean_manifest_path)
    _precheck_output_dir(output_dir, overwrite)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if disk_free_start < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below --min-free-bytes: {disk_free_start} < {min_free_bytes}")

    clean_manifest = read_json(clean_manifest_path)
    train_sequences_path = _resolve_train_sequences_path(clean_manifest_path, clean_manifest)
    item_metadata_path = _resolve_item_metadata_path(clean_manifest_path, clean_manifest)
    _precheck_train_path(train_sequences_path)
    _precheck_item_metadata_path(item_metadata_path)

    sequences, load_audit = _load_batch_sequences(train_sequences_path, limit_users, max_items_per_user)
    target_items = {item_id for profile in sequences for item_id in profile["unique_items"]}
    item_categories, metadata_audit = _load_item_categories(item_metadata_path, target_items, max_item_metadata_rows)
    shared_neighbors = _shared_item_neighbor_counts(sequences)
    profiles = [
        _profile_user(sequence, item_categories, shared_neighbors.get(sequence["user_id"], 0))
        for sequence in sequences
    ]

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)

    summary = _quality_bucket_summary(profiles)
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "scope": "batch_scoped_train_only_user_quality_profile",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "read_files": [str(train_sequences_path), str(item_metadata_path)],
        "forbidden_inputs": [str(train_sequences_path.parent / name) for name in FORBIDDEN_INPUT_NAMES],
        "uses_valid": False,
        "uses_test": False,
        "uses_holdout": False,
        "limit_users": limit_users,
        "max_items_per_user": max_items_per_user,
        "max_item_metadata_rows": max_item_metadata_rows,
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "runtime_seconds": round(perf_counter() - started, 6),
        **load_audit,
        **metadata_audit,
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "diagnostic_limited_train_users",
        "policy_role": "eligibility_policy_not_recall_source",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "item_metadata_path": str(item_metadata_path),
        "clean_manifest_sha256": _file_sha256(clean_manifest_path),
        "train_user_sequences_sha256": _file_sha256(train_sequences_path),
        "item_metadata_sha256": _file_sha256(item_metadata_path),
        "limit_users": limit_users,
        "quality_buckets": ["heavy_cf_eligible", "medium_behavior", "fallback_only"],
        "bucket_thresholds": BUCKET_THRESHOLDS,
        "required_profile_fields": [
            "user_id",
            "positive_count",
            "unique_item_count",
            "category_count",
            "recent_sequence_length",
            "shared_item_neighbor_count",
            "quality_bucket",
            "eligible_for_usercf",
            "eligible_for_itemcf",
            "eligible_for_swing",
            "fallback_only",
        ],
        "profiles": profiles,
        "summary_path": str(output_dir / "quality_bucket_summary.json"),
        "resource_audit_path": str(output_dir / "resource_audit.json"),
    }
    write_json(output_dir / "eligible_user_quality_manifest.json", manifest)
    write_json(output_dir / "quality_bucket_summary.json", summary)
    write_json(output_dir / "resource_audit.json", resource_audit)
    return manifest


def _validate_caps(limit_users: int, max_items_per_user: int, max_item_metadata_rows: int, min_free_bytes: int) -> None:
    if limit_users <= 0:
        raise ValueError("--limit-users must be positive for batch-scoped user_quality profiling")
    if max_items_per_user <= 0:
        raise ValueError("--max-items-per-user must be positive")
    if max_item_metadata_rows < 0:
        raise ValueError("--max-item-metadata-rows must be non-negative")
    if min_free_bytes < 0:
        raise ValueError("--min-free-bytes must be non-negative")


def _resolve_repo_path(clean_manifest_path: Path, raw_path: Any) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (clean_manifest_path.parent / path).resolve()


def _resolve_train_sequences_path(clean_manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path")
    if not raw_path:
        raise ValueError("user_quality profiling requires clean_manifest.train_user_sequences_path")
    return _resolve_repo_path(clean_manifest_path, raw_path)


def _resolve_item_metadata_path(clean_manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("canonical_items_path")
    if not raw_path:
        raise ValueError("user_quality profiling requires clean_manifest.canonical_items_path")
    return _resolve_repo_path(clean_manifest_path, raw_path)


def _precheck_path(path: Path) -> None:
    lowered = str(path).replace("\\", "/").lower()
    if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
        raise ValueError(f"Forbidden holdout/10k/pool1000 path is not allowed: {path}")
    if path.name.lower() in FORBIDDEN_INPUT_NAMES:
        raise ValueError(f"Forbidden non-train input is not allowed: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)


def _precheck_output_dir(output_dir: Path, overwrite: bool) -> None:
    lowered = str(output_dir).replace("\\", "/").lower()
    if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
        raise ValueError(f"Forbidden holdout/10k/pool1000 output path is not allowed: {output_dir}")
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")


def _precheck_train_path(path: Path) -> None:
    _precheck_path(path)
    if path.name != "user_sequences.train.jsonl":
        raise ValueError(f"user_quality profiling must read user_sequences.train.jsonl, got {path.name}")


def _precheck_item_metadata_path(path: Path) -> None:
    _precheck_path(path)
    if path.name != "canonical_items.jsonl":
        raise ValueError(f"user_quality profiling must read canonical_items.jsonl, got {path.name}")


def _load_batch_sequences(path: Path, limit_users: int, max_items_per_user: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    profiles = []
    rows_scanned = 0
    raw_positive_event_count = 0
    for row in iter_jsonl(path):
        rows_scanned += 1
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        positive_items = _sequence_items(row.get("recent_positive_item_sequence", []))
        recent_items = _sequence_items(row.get("recent_item_sequence", [])) or positive_items
        unique_items = _recent_unique_items(positive_items, max_items_per_user)
        raw_positive_event_count += len(positive_items)
        profiles.append(
            {
                "user_id": user_id,
                "positive_count": len(positive_items),
                "recent_sequence_length": len(recent_items),
                "unique_items": unique_items,
            }
        )
        if len(profiles) >= limit_users:
            break
    return profiles, {
        "rows_scanned": rows_scanned,
        "profiled_user_count": len(profiles),
        "raw_positive_event_count": raw_positive_event_count,
    }


def _sequence_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _recent_unique_items(items: list[str], max_items_per_user: int) -> list[str]:
    return list(dict.fromkeys(reversed(items[-max_items_per_user:])))


def _load_item_categories(path: Path, target_items: set[str], max_rows: int) -> tuple[dict[str, set[str]], dict[str, Any]]:
    categories_by_item: dict[str, set[str]] = {}
    rows_scanned = 0
    for row in iter_jsonl(path):
        rows_scanned += 1
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if item_id in target_items:
            categories_by_item[item_id] = _row_categories(row)
        if max_rows and rows_scanned >= max_rows:
            break
        if target_items and len(categories_by_item) >= len(target_items):
            break
    return categories_by_item, {
        "item_metadata_rows_scanned": rows_scanned,
        "target_item_count": len(target_items),
        "target_item_metadata_hit_count": len(categories_by_item),
    }


def _row_categories(row: dict[str, Any]) -> set[str]:
    values: list[str] = []
    for key in ("main_category", "category"):
        if row.get(key):
            values.append(str(row[key]))
    categories_flat = row.get("categories_flat")
    if isinstance(categories_flat, list):
        values.extend(str(category) for category in categories_flat if category)
    source_categories = row.get("source_categories")
    if isinstance(source_categories, list):
        values.extend(str(category) for category in source_categories if category)
    return {value for value in values if value}


def _shared_item_neighbor_counts(sequences: list[dict[str, Any]]) -> dict[str, int]:
    item_users: dict[str, set[str]] = defaultdict(set)
    user_items = {sequence["user_id"]: set(sequence["unique_items"]) for sequence in sequences}
    for user_id, items in user_items.items():
        for item_id in items:
            item_users[item_id].add(user_id)
    neighbor_counts: dict[str, int] = {}
    for user_id, items in user_items.items():
        neighbors = set()
        for item_id in items:
            neighbors.update(item_users[item_id])
        neighbors.discard(user_id)
        neighbor_counts[user_id] = len(neighbors)
    return neighbor_counts


def _profile_user(sequence: dict[str, Any], item_categories: dict[str, set[str]], shared_item_neighbor_count: int) -> dict[str, Any]:
    unique_items = sequence["unique_items"]
    categories = set()
    for item_id in unique_items:
        categories.update(item_categories.get(item_id, set()))
    profile = {
        "user_id": sequence["user_id"],
        "positive_count": sequence["positive_count"],
        "unique_item_count": len(unique_items),
        "category_count": len(categories),
        "recent_sequence_length": sequence["recent_sequence_length"],
        "shared_item_neighbor_count": shared_item_neighbor_count,
    }
    bucket = _quality_bucket(profile)
    profile.update(
        {
            "quality_bucket": bucket,
            "eligible_for_usercf": bucket == "heavy_cf_eligible",
            "eligible_for_itemcf": bucket in {"heavy_cf_eligible", "medium_behavior"},
            "eligible_for_swing": bucket in {"heavy_cf_eligible", "medium_behavior"},
            "fallback_only": bucket == "fallback_only",
        }
    )
    return profile


def _quality_bucket(profile: dict[str, int]) -> str:
    heavy = BUCKET_THRESHOLDS["heavy_cf_eligible"]
    if (
        profile["positive_count"] >= heavy["positive_count_min"]
        and profile["unique_item_count"] >= heavy["unique_item_count_min"]
        and profile["category_count"] >= heavy["category_count_min"]
        and profile["shared_item_neighbor_count"] >= heavy["shared_item_neighbor_count_min"]
    ):
        return "heavy_cf_eligible"
    medium = BUCKET_THRESHOLDS["medium_behavior"]
    if (
        profile["positive_count"] >= medium["positive_count_min"]
        and profile["unique_item_count"] >= medium["unique_item_count_min"]
        and profile["category_count"] >= medium["category_count_min"]
    ):
        return "medium_behavior"
    return "fallback_only"


def _quality_bucket_summary(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = Counter(profile["quality_bucket"] for profile in profiles)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "profiled_user_count": len(profiles),
        "bucket_counts": {bucket: buckets.get(bucket, 0) for bucket in ("heavy_cf_eligible", "medium_behavior", "fallback_only")},
        "eligible_counts": {
            "usercf": sum(1 for profile in profiles if profile["eligible_for_usercf"]),
            "itemcf": sum(1 for profile in profiles if profile["eligible_for_itemcf"]),
            "swing": sum(1 for profile in profiles if profile["eligible_for_swing"]),
            "fallback_only": sum(1 for profile in profiles if profile["fallback_only"]),
        },
        "policy_mapping": {
            "usercf_recall": "heavy_cf_eligible",
            "itemcf_weak": "heavy_cf_eligible_or_medium_behavior",
            "itemcf_strong": "heavy_cf_eligible",
            "swing_recall": "heavy_cf_eligible_or_medium_behavior",
            "category": "medium_behavior_or_fallback",
            "popular": "fallback_only",
        },
        "readiness_claim": "diagnostic_policy_artifact_only_not_pool500_final_ready",
    }


def _existing_ancestor(path: Path) -> Path:
    current = path.resolve()
    while not current.exists():
        if current.parent == current:
            return current
        current = current.parent
    return current


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    manifest = build_pool500_user_quality_profile(
        clean_manifest_path=Path(args.clean_manifest),
        output_dir=Path(args.output_dir),
        limit_users=args.limit_users,
        max_items_per_user=args.max_items_per_user,
        max_item_metadata_rows=args.max_item_metadata_rows,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "profiled_user_count": len(manifest["profiles"]),
                "manifest_path": str(Path(args.output_dir) / "eligible_user_quality_manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
