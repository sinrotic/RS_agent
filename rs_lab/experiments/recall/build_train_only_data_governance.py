from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "train_only_data_governance_v1"
RECENT_2Y_DATASET_ROOT = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_CLEAN_MANIFEST = RECENT_2Y_DATASET_ROOT / "manifest.json"
DEFAULT_OUTPUT_DIR = RECENT_2Y_DATASET_ROOT / "train_only_governance"
FORBIDDEN_SCOPE_TOKENS = (
    "valid",
    "validation",
    "test",
    "holdout",
    "lopo",
    "eval_label",
    "oracle",
    "clean_10000",
    "pool1000",
)
FORBIDDEN_INPUT_NAMES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)
USER_QUALITY_BUCKETS_V2 = (
    "cold_start",
    "fallback_only",
    "medium_behavior",
    "sequence_sufficient",
    "collaborative_rich",
)
ITEM_QUALITY_BUCKETS_V2 = (
    "no_positive",
    "single_seed",
    "low_frequency",
    "mid_frequency",
    "cf_ready",
    "embedding_ready",
)
USER_QUALITY_BUCKET_V2_BY_LEGACY = {
    "cold_start": "cold_start",
    "fallback_only": "fallback_only",
    "medium_behavior": "medium_behavior",
    "two_tower_train_eligible": "sequence_sufficient",
    "heavy_cf_eligible": "collaborative_rich",
}
DEFAULT_THRESHOLDS = {
    "cold_start": {"sequence_len_max": 1, "positive_count_max": 1},
    "medium_behavior": {"positive_count_min": 4, "unique_item_count_min": 2},
    "heavy_cf_eligible": {"positive_count_min": 10, "unique_item_count_min": 5, "shared_item_user_count_min": 2},
    "two_tower_train_eligible": {"positive_count_min": 3, "unique_item_count_min": 2, "hot_item_min_freq": 3},
    "long_tail_item": {"frequency_lt": 3},
}
MIN_FREQ_UNIVERSES = (2, 3, 5, 10)
TOP_K_UNIVERSES = (50_000, 100_000, 200_000)
SCALE_TIERS = {
    "smoke": {"limit_users": 500, "limit_interactions": 20_000},
    "formal": {"limit_users": 0, "limit_interactions": 0},
}
DERIVED_DATASET_POLICIES = {
    "itemcf_strong": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "allowed_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "eligible_user_buckets": ["collaborative_rich"],
        "eligible_user_policy": "heavy_cf_eligible_only",
        "eligible_item_policy": "train_item_universe_with_idf_downweighting",
        "item_universe_policy": "train_item_universe_no_oracle_label_injection",
        "required_fields": ["user_id", "recent_positive_item_sequence", "parent_asin", "frequency", "user_count"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "diagnostic_itemcf_candidate_source",
        "acceptance_checks": ["train_only_inputs", "eligible_user_bucket_is_heavy_cf_eligible", "min_overlap_gte_2", "item_idf_or_super_hot_downweighting"],
        "min_overlap": 2,
        "item_weighting_policy": "item_idf_downweight_super_hot_items",
    },
    "itemcf_weak": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "allowed_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "eligible_user_buckets": ["collaborative_rich", "medium_behavior"],
        "eligible_user_policy": "heavy_cf_eligible_or_medium_behavior",
        "eligible_item_policy": "train_item_universe_with_idf_downweighting",
        "item_universe_policy": "train_item_universe_no_oracle_label_injection",
        "required_fields": ["user_id", "recent_positive_item_sequence", "parent_asin", "frequency", "user_count"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "diagnostic_itemcf_candidate_source",
        "acceptance_checks": ["train_only_inputs", "eligible_user_bucket_is_heavy_or_medium", "min_overlap_gte_2", "item_idf_or_super_hot_downweighting"],
        "min_overlap": 2,
        "item_weighting_policy": "item_idf_downweight_super_hot_items",
    },
    "two_tower": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["user_quality_profile.jsonl", "item_quality_profile.jsonl", "item_frequency_train.jsonl", "item_universe_summary.json", "user_sequences.train.jsonl"],
        "allowed_inputs": ["user_quality_profile.jsonl", "item_quality_profile.jsonl", "item_frequency_train.jsonl", "item_universe_summary.json", "user_sequences.train.jsonl"],
        "eligible_user_buckets": ["sequence_sufficient", "collaborative_rich", "medium_behavior"],
        "eligible_user_policy": "two_tower_train_eligible_or_above",
        "eligible_item_policy": "hot_item_universe_from_train_frequency",
        "item_universe_policy": "hot_item_universe_from_train_frequency",
        "recommended_hot_item_min_freq": DEFAULT_THRESHOLDS["two_tower_train_eligible"]["hot_item_min_freq"],
        "required_fields": ["user_id", "recent_positive_item_sequence", "parent_asin", "frequency"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "train_only_embedding_candidate_source",
        "acceptance_checks": ["train_only_inputs", "eligible_user_bucket_allowed", "hot_item_min_freq_applied", "no_eval_label_or_oracle_features"],
    },
    "usercf_recall": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "allowed_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "eligible_user_buckets": ["collaborative_rich"],
        "eligible_user_policy": "heavy_cf_eligible_only",
        "eligible_item_policy": "train_item_universe_with_idf_downweighting",
        "item_universe_policy": "train_item_universe_no_oracle_label_injection",
        "required_fields": ["user_id", "recent_positive_item_sequence", "parent_asin", "frequency", "user_count"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "diagnostic_usercf_candidate_source",
        "acceptance_checks": ["train_only_inputs", "eligible_user_bucket_is_heavy_cf_eligible", "min_overlap_gte_2", "item_idf_or_super_hot_downweighting"],
        "min_overlap": 2,
        "item_weighting_policy": "item_idf_downweight_super_hot_items",
    },
    "swing_recall": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "allowed_inputs": ["user_quality_profile.jsonl", "item_frequency_train.jsonl", "user_sequences.train.jsonl"],
        "eligible_user_buckets": ["collaborative_rich", "medium_behavior"],
        "eligible_user_policy": "heavy_cf_eligible_or_medium_behavior",
        "eligible_item_policy": "mid_frequency_items_with_super_hot_downweighting",
        "item_universe_policy": "train_item_universe_no_oracle_label_injection",
        "required_fields": ["user_id", "recent_positive_item_sequence", "parent_asin", "frequency", "user_count"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "diagnostic_swing_candidate_source",
        "acceptance_checks": ["train_only_inputs", "eligible_user_bucket_is_heavy_or_medium", "common_user_count_gte_2", "score_is_nonnegative", "mid_frequency_or_super_hot_policy_applied"],
        "common_user_count_min": 2,
        "score_policy": "nonnegative",
        "item_frequency_policy": "prefer_mid_frequency_downweight_super_hot",
    },
    "popular": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["item_frequency_train.jsonl"],
        "allowed_inputs": ["item_frequency_train.jsonl"],
        "eligible_user_buckets": ["cold_start", "fallback_only", "medium_behavior", "sequence_sufficient", "collaborative_rich"],
        "eligible_user_policy": "all_train_profiled_users",
        "eligible_item_policy": "train_item_frequency_only",
        "item_universe_policy": "train_item_universe_no_oracle_label_injection",
        "required_fields": ["parent_asin", "frequency"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "fallback_popular_candidate_source",
        "acceptance_checks": ["train_only_inputs", "rank_by_train_item_frequency", "no_non_train_popularity"],
    },
    "category": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["item_frequency_train.jsonl", "catalog_metadata_train_scope"],
        "allowed_inputs": ["item_frequency_train.jsonl", "catalog_metadata_train_scope"],
        "eligible_user_buckets": ["fallback_only", "medium_behavior", "sequence_sufficient", "collaborative_rich"],
        "eligible_user_policy": "users_with_train_profile_or_fallback_popular",
        "eligible_item_policy": "item_metadata_plus_train_category_popularity",
        "item_universe_policy": "train_item_universe_no_oracle_label_injection",
        "required_fields": ["parent_asin", "category", "frequency"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "category_popularity_candidate_source",
        "acceptance_checks": ["train_only_inputs", "category_min_item_count_gte_5", "popular_fallback_for_sparse_category"],
        "category_min_item_count": 5,
        "fallback_policy": "popular_fallback_when_category_too_sparse",
    },
    "semantic": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["catalog_metadata_train_scope", "title_metadata", "category_metadata", "user_quality_profile.jsonl"],
        "allowed_inputs": ["catalog_metadata_train_scope", "title_metadata", "category_metadata", "user_quality_profile.jsonl"],
        "eligible_user_buckets": ["fallback_only", "medium_behavior", "sequence_sufficient", "collaborative_rich"],
        "eligible_user_policy": "profile_metadata_only_no_eval_labels",
        "eligible_item_policy": "catalog_title_category_metadata_only",
        "item_universe_policy": "catalog_metadata_no_oracle_label_injection",
        "required_fields": ["user_id", "parent_asin", "title", "category"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "semantic_metadata_candidate_source",
        "acceptance_checks": ["train_only_inputs", "catalog_title_category_profile_metadata_only", "no_eval_label", "no_oracle", "similarity_threshold_recorded"],
        "similarity_threshold_policy": {"record_in_manifest": True, "tunable_train_only_metadata": True},
    },
    "co_visit_fallback_repair": {
        "method_dataset_policy": "train_only_method_dataset",
        "train_only_inputs": ["user_sequences.train.jsonl", "canonical_interactions.train.jsonl"],
        "allowed_inputs": ["user_sequences.train.jsonl", "canonical_interactions.train.jsonl"],
        "eligible_user_buckets": ["fallback_only", "medium_behavior", "sequence_sufficient", "collaborative_rich"],
        "eligible_user_policy": "users_requiring_fallback_repair_from_train_sessions",
        "eligible_item_policy": "train_session_co_visit_only",
        "item_universe_policy": "train_item_universe_no_oracle_label_injection",
        "required_fields": ["user_id", "recent_positive_item_sequence", "parent_asin", "timestamp"],
        "forbidden_scopes": ["valid", "test", "holdout", "lopo", "oracle", "eval_label"],
        "output_role": "fallback_repair_candidate_source",
        "acceptance_checks": ["train_only_session_or_co_visit_inputs", "co_visit_count_gte_2", "no_eval_label_or_oracle_features"],
        "co_visit_count_min": 2,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build train-only governance artifacts from the recent 2y train split.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--cold-start-sequence-len-max", type=int, default=DEFAULT_THRESHOLDS["cold_start"]["sequence_len_max"])
    parser.add_argument("--cold-start-positive-count-max", type=int, default=DEFAULT_THRESHOLDS["cold_start"]["positive_count_max"])
    parser.add_argument("--medium-positive-count-min", type=int, default=DEFAULT_THRESHOLDS["medium_behavior"]["positive_count_min"])
    parser.add_argument("--medium-unique-item-count-min", type=int, default=DEFAULT_THRESHOLDS["medium_behavior"]["unique_item_count_min"])
    parser.add_argument("--heavy-positive-count-min", type=int, default=DEFAULT_THRESHOLDS["heavy_cf_eligible"]["positive_count_min"])
    parser.add_argument("--heavy-unique-item-count-min", type=int, default=DEFAULT_THRESHOLDS["heavy_cf_eligible"]["unique_item_count_min"])
    parser.add_argument("--heavy-shared-item-user-count-min", type=int, default=DEFAULT_THRESHOLDS["heavy_cf_eligible"]["shared_item_user_count_min"])
    parser.add_argument("--two-tower-positive-count-min", type=int, default=DEFAULT_THRESHOLDS["two_tower_train_eligible"]["positive_count_min"])
    parser.add_argument("--two-tower-unique-item-count-min", type=int, default=DEFAULT_THRESHOLDS["two_tower_train_eligible"]["unique_item_count_min"])
    parser.add_argument("--two-tower-hot-item-min-freq", type=int, default=DEFAULT_THRESHOLDS["two_tower_train_eligible"]["hot_item_min_freq"])
    parser.add_argument("--long-tail-frequency-lt", type=int, default=DEFAULT_THRESHOLDS["long_tail_item"]["frequency_lt"])
    parser.add_argument("--scale-tier", choices=tuple(SCALE_TIERS), default="smoke")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional smoke limit over user_sequences.train.jsonl rows; 0 means full train users.")
    parser.add_argument("--limit-interactions", type=int, default=None, help="Optional smoke limit over canonical_interactions.train.jsonl rows; 0 means full train interactions.")
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_train_only_data_governance(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    thresholds: dict[str, dict[str, int]] | None = None,
    scale_tier: str = "smoke",
    limit_users: int | None = None,
    limit_interactions: int | None = None,
    min_free_bytes: int = 0,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    thresholds = _merge_thresholds(thresholds)
    limits = _resolve_limits(scale_tier=scale_tier, limit_users=limit_users, limit_interactions=limit_interactions)
    _validate_limits(limits["limit_users"], limits["limit_interactions"], min_free_bytes)

    clean_manifest_path = clean_manifest_path.resolve()
    output_dir = output_dir.resolve()
    clean_manifest = read_json(clean_manifest_path)
    _reject_forbidden_scope_payload(clean_manifest, context="clean_manifest")
    train_interactions_path = _resolve_train_interactions_path(clean_manifest_path, clean_manifest)
    train_sequences_path = _resolve_train_sequences_path(clean_manifest_path, clean_manifest)
    canonical_items_path = _resolve_canonical_items_path(clean_manifest_path, clean_manifest)
    _precheck_input_path(clean_manifest_path, expected_name="manifest.json")
    _precheck_input_path(train_interactions_path, expected_name="canonical_interactions.train.jsonl")
    _precheck_input_path(train_sequences_path, expected_name="user_sequences.train.jsonl")
    _precheck_input_path(canonical_items_path, expected_name="canonical_items.jsonl")
    _precheck_output_dir(output_dir, overwrite)

    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if disk_free_start < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below --min-free-bytes: {disk_free_start} < {min_free_bytes}")
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)

    interaction_stats = _scan_train_interactions(train_interactions_path, limits["limit_interactions"])
    canonical_items = _scan_canonical_items(canonical_items_path)
    artifact_paths = _artifact_paths(output_dir)
    item_summary = _write_item_artifacts(
        artifact_paths=artifact_paths,
        item_stats=interaction_stats["item_stats"],
        canonical_items=canonical_items,
        total_positive_events=interaction_stats["total_positive_events"],
        total_positive_user_item_pairs=interaction_stats["total_positive_user_item_pairs"],
        thresholds=thresholds,
    )
    user_summary = _write_user_artifacts(
        train_sequences_path=train_sequences_path,
        artifact_paths=artifact_paths,
        user_stats=interaction_stats["user_stats"],
        item_stats=interaction_stats["item_stats"],
        thresholds=thresholds,
        limit_users=limits["limit_users"],
    )
    leakage_audit = _leakage_audit(
        clean_manifest_path=clean_manifest_path,
        clean_manifest=clean_manifest,
        train_interactions_path=train_interactions_path,
        train_sequences_path=train_sequences_path,
        canonical_items_path=canonical_items_path,
        output_dir=output_dir,
    )
    write_json(artifact_paths["leakage_audit"], leakage_audit)

    generated_at = datetime.now(timezone.utc).isoformat()
    lineage = {
        "source_layer": "recent_2y",
        "derived_layer": "recent_2y_train_only_governance",
        "mutation_policy": "recent_2y_dataset_is_read_only; governance artifacts are derived outputs",
        "input_files": {
            "clean_manifest": str(clean_manifest_path),
            "canonical_interactions_train": str(train_interactions_path),
            "user_sequences_train": str(train_sequences_path),
            "canonical_items": str(canonical_items_path),
        },
        "allowed_inputs": ["manifest.json", "canonical_interactions.train.jsonl", "user_sequences.train.jsonl", "canonical_items.jsonl"],
        "input_hashes": {
            "clean_manifest_sha256": _file_sha256(clean_manifest_path),
            "canonical_interactions_train_sha256": _file_sha256(train_interactions_path),
            "user_sequences_train_sha256": _file_sha256(train_sequences_path),
            "canonical_items_sha256": _file_sha256(canonical_items_path),
        },
    }
    eligible_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": generated_at,
        "train_only": True,
        "manifest_role": "eligible_user_quality_policy",
        "thresholds": thresholds,
        "quality_bucket_summary_path": str(artifact_paths["quality_bucket_summary"]),
        "user_quality_profile_path": str(artifact_paths["user_quality_profile"]),
        "item_quality_profile_path": str(artifact_paths["item_quality_profile"]),
        "item_quality_summary_path": str(artifact_paths["item_quality_summary"]),
        "bucket_counts": user_summary["bucket_counts"],
        "bucket_ratios": user_summary["bucket_ratios"],
        "eligibility_counts": user_summary["eligibility_counts"],
        "lineage": lineage,
        "leakage_audit_path": str(artifact_paths["leakage_audit"]),
        "derived_dataset_policies": DERIVED_DATASET_POLICIES,
    }
    write_json(artifact_paths["eligible_user_quality_manifest"], eligible_manifest)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": generated_at,
        "output_dir": str(output_dir),
        "train_only": True,
        "valid_used": False,
        "test_used": False,
        "holdout_used": False,
        "lopo_used": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "recent_2y_modified": False,
        "clean_full_modified": False,
        "thresholds": thresholds,
        "lineage": lineage,
        "artifacts": {name: str(path) for name, path in artifact_paths.items()},
        "quality_bucket_summary": user_summary,
        "item_universe_summary": item_summary,
        "item_quality_summary": item_summary,
        "derived_dataset_policies": DERIVED_DATASET_POLICIES,
        "resource_scale_policy": {"scale_tier": scale_tier, "default_tier": "formal", "scale_tiers": SCALE_TIERS},
        "limits": limits,
        "resource_summary": {
            "disk_free_bytes_start": disk_free_start,
            "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
            "runtime_seconds": round(perf_counter() - started, 6),
        },
    }
    write_json(artifact_paths["manifest"], manifest)
    return manifest


def load_governance_manifest(path: str | Path) -> dict[str, Any]:
    manifest = read_json(Path(path))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unexpected governance schema_version: {manifest.get('schema_version')}")
    if manifest.get("train_only") is not True:
        raise ValueError("Governance manifest must be train_only")
    return manifest


def method_dataset_policies(manifest: dict[str, Any]) -> dict[str, Any]:
    policies = manifest.get("derived_dataset_policies")
    if not isinstance(policies, dict):
        raise ValueError("Governance manifest missing derived_dataset_policies")
    return policies


def _merge_thresholds(overrides: dict[str, dict[str, int]] | None) -> dict[str, dict[str, int]]:
    merged = {name: dict(values) for name, values in DEFAULT_THRESHOLDS.items()}
    for group, values in (overrides or {}).items():
        merged.setdefault(group, {}).update(values)
    return merged


def _resolve_limits(*, scale_tier: str, limit_users: int | None, limit_interactions: int | None) -> dict[str, int]:
    if scale_tier not in SCALE_TIERS:
        raise ValueError(f"Unsupported scale_tier: {scale_tier}")
    tier_limits = SCALE_TIERS[scale_tier]
    return {
        "limit_users": tier_limits["limit_users"] if limit_users is None else limit_users,
        "limit_interactions": tier_limits["limit_interactions"] if limit_interactions is None else limit_interactions,
    }


def _validate_limits(limit_users: int, limit_interactions: int, min_free_bytes: int) -> None:
    if limit_users < 0:
        raise ValueError("limit_users must be non-negative")
    if limit_interactions < 0:
        raise ValueError("limit_interactions must be non-negative")
    if min_free_bytes < 0:
        raise ValueError("min_free_bytes must be non-negative")


def _resolve_repo_path(manifest_path: Path, raw_path: Any) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (manifest_path.parent / path).resolve()


def _resolve_train_interactions_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    split_paths = manifest.get("split_paths")
    if not isinstance(split_paths, dict) or not split_paths.get("train"):
        raise ValueError("clean manifest must provide split_paths.train")
    return _resolve_repo_path(manifest_path, split_paths["train"])


def _resolve_train_sequences_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path")
    if not raw_path:
        raise ValueError("clean manifest must provide train_user_sequences_path")
    return _resolve_repo_path(manifest_path, raw_path)


def _resolve_canonical_items_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("canonical_items_path")
    if not raw_path:
        raise ValueError("clean manifest must provide canonical_items_path")
    return _resolve_repo_path(manifest_path, raw_path)


def _precheck_input_path(path: Path, *, expected_name: str) -> None:
    lowered = str(path).replace("\\", "/").lower()
    if path.name != expected_name:
        raise ValueError(f"Expected {expected_name}, got {path.name}")
    if path.name in {"canonical_interactions.train.jsonl", "user_sequences.train.jsonl", "canonical_items.jsonl", "manifest.json"}:
        if _path_has_forbidden_scope(path.parent):
            raise ValueError(f"Forbidden non-train path is not allowed: {path}")
    if any(name == path.name.lower() for name in FORBIDDEN_INPUT_NAMES):
        raise ValueError(f"Forbidden non-train input is not allowed: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)


def _precheck_output_dir(output_dir: Path, overwrite: bool) -> None:
    if _path_has_forbidden_scope(output_dir):
        raise ValueError(f"Forbidden output path is not allowed: {output_dir}")
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")


def _scan_train_interactions(path: Path, limit_interactions: int) -> dict[str, Any]:
    item_stats: dict[str, dict[str, Any]] = {}
    total_rows = 0
    positive_rows = 0
    for row in iter_jsonl(path):
        total_rows += 1
        if limit_interactions and total_rows > limit_interactions:
            break
        if str(row.get("split", "train")).lower() != "train":
            raise ValueError(f"Non-train row found in train interactions: split={row.get('split')}")
        item_id = str(row.get("parent_asin") or "")
        if not item_id:
            continue
        category = _optional_str(row.get("category"))
        main_category = _optional_str(row.get("main_category"))
        brand = _optional_str(row.get("brand"))
        store = _optional_str(row.get("store"))
        item = item_stats.setdefault(
            item_id,
            {
                "frequency": 0,
                "user_count": 0,
                "positive_users": set(),
                "train_interaction_count": 0,
                "train_positive_count": 0,
                "train_strong_positive_count": 0,
                "categories": Counter(),
                "main_categories": Counter(),
                "brands": Counter(),
                "stores": Counter(),
            },
        )
        item["train_interaction_count"] += 1
        if category:
            item["categories"][category] += 1
        if main_category:
            item["main_categories"][main_category] += 1
        if brand:
            item["brands"][brand] += 1
        if store:
            item["stores"][store] += 1
        if not row.get("label_binary"):
            continue
        positive_rows += 1
        item["frequency"] += 1
        item["train_positive_count"] += 1
        item["train_strong_positive_count"] += 1
        user_id = str(row.get("user_id") or "")
        if user_id:
            item["positive_users"].add(user_id)
            item["user_count"] = len(item["positive_users"])
    return {
        "total_rows_scanned": min(total_rows, limit_interactions or total_rows),
        "total_positive_events": positive_rows,
        "total_positive_user_item_pairs": sum(len(stats["positive_users"]) for stats in item_stats.values()),
        "item_stats": item_stats,
        "user_stats": {},
    }


def _write_item_artifacts(
    *,
    artifact_paths: dict[str, Path],
    item_stats: dict[str, dict[str, Any]],
    canonical_items: dict[str, dict[str, Any]],
    total_positive_events: int,
    total_positive_user_item_pairs: int,
    thresholds: dict[str, dict[str, int]],
) -> dict[str, Any]:
    long_tail_threshold = thresholds["long_tail_item"]["frequency_lt"]
    all_item_ids = set(canonical_items) | set(item_stats)
    sorted_items = sorted(all_item_ids, key=lambda item_id: (-int(item_stats.get(item_id, {}).get("frequency", 0)), item_id))
    category_counts: dict[str, int] = defaultdict(int)
    for item_id, stats in item_stats.items():
        category = _counter_top(stats["categories"])
        if category:
            category_counts[category] += int(stats["frequency"])
    category_ranks = {category: rank for rank, (category, _) in enumerate(sorted(category_counts.items(), key=lambda item: (-item[1], item[0])), start=1)}
    long_tail_count = 0
    long_tail_event_count = 0
    item_bucket_counts: Counter[str] = Counter()
    with (
        artifact_paths["item_frequency_train"].open("w", encoding="utf-8") as frequency_sink,
        artifact_paths["long_tail_item_profile"].open("w", encoding="utf-8") as long_tail_sink,
        artifact_paths["item_quality_profile"].open("w", encoding="utf-8") as quality_sink,
    ):
        for global_rank, item_id in enumerate(sorted_items, start=1):
            stats = item_stats.get(item_id) or _empty_item_stats()
            metadata = canonical_items.get(item_id, {})
            frequency = int(stats["frequency"])
            user_count = int(stats["user_count"])
            category = _counter_top(stats["categories"]) or _optional_str(metadata.get("category"))
            main_category = _counter_top(stats["main_categories"]) or _optional_str(metadata.get("main_category"))
            quality = _item_quality_record(
                item_id=item_id,
                stats=stats,
                metadata=metadata,
                global_rank=global_rank,
                category=category,
                main_category=main_category,
                category_rank=category_ranks.get(category),
                thresholds=thresholds,
            )
            item_bucket_counts[quality["quality_bucket_v2"]] += 1
            record = {
                "parent_asin": item_id,
                "frequency": frequency,
                "user_count": user_count,
                "category": category,
                "brand": _counter_top(stats["brands"]) or _optional_str(metadata.get("brand")),
                "store": _counter_top(stats["stores"]) or _optional_str(metadata.get("store")),
                "is_long_tail": frequency < long_tail_threshold,
            }
            frequency_sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            quality_sink.write(json.dumps(quality, ensure_ascii=False) + "\n")
            if record["is_long_tail"]:
                long_tail_count += 1
                long_tail_event_count += frequency
                long_tail_sink.write(json.dumps(record, ensure_ascii=False) + "\n")
    sorted_item_stats = [(item_id, item_stats.get(item_id) or _empty_item_stats()) for item_id in sorted_items]
    universe_by_min_freq = {
        f"min_freq_gte_{min_freq}": _item_universe_stats_from_iter(
            (stats for _, stats in sorted_item_stats if int(stats["frequency"]) >= min_freq),
            total_positive_events,
            total_positive_user_item_pairs,
        )
        for min_freq in MIN_FREQ_UNIVERSES
    }
    universe_by_top_k = {
        f"top_{top_k}": _item_universe_stats_from_iter(
            (stats for _, stats in sorted_item_stats[:top_k]),
            total_positive_events,
            total_positive_user_item_pairs,
        )
        for top_k in TOP_K_UNIVERSES
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "total_item_count": len(sorted_items),
        "total_positive_events": total_positive_events,
        "total_positive_user_item_pairs": total_positive_user_item_pairs,
        "user_count_semantics": "unique_positive_user_count deduplicates user_id; positive_event_count preserves event rows",
        "item_quality_profile_path": str(artifact_paths["item_quality_profile"]),
        "item_quality_summary_path": str(artifact_paths["item_quality_summary"]),
        "item_quality_bucket_v2_enum": list(ITEM_QUALITY_BUCKETS_V2),
        "item_quality_bucket_v2_counts": {bucket: item_bucket_counts.get(bucket, 0) for bucket in ITEM_QUALITY_BUCKETS_V2},
        "long_tail_policy": {"frequency_lt": long_tail_threshold},
        "long_tail_item_count": long_tail_count,
        "long_tail_positive_event_count": long_tail_event_count,
        "long_tail_positive_event_share": _ratio(long_tail_event_count, total_positive_events),
        "universes_by_min_freq": universe_by_min_freq,
        "universes_by_top_k": universe_by_top_k,
    }
    write_json(artifact_paths["item_universe_summary"], summary)
    write_json(artifact_paths["item_quality_summary"], summary)
    return summary


def _scan_canonical_items(path: Path) -> dict[str, dict[str, Any]]:
    items = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if item_id:
            items[item_id] = row
    return items


def _empty_item_stats() -> dict[str, Any]:
    return {
        "frequency": 0,
        "user_count": 0,
        "positive_users": set(),
        "train_interaction_count": 0,
        "train_positive_count": 0,
        "train_strong_positive_count": 0,
        "categories": Counter(),
        "main_categories": Counter(),
        "brands": Counter(),
        "stores": Counter(),
    }


def _item_quality_record(
    *,
    item_id: str,
    stats: dict[str, Any],
    metadata: dict[str, Any],
    global_rank: int,
    category: str | None,
    main_category: str | None,
    category_rank: int | None,
    thresholds: dict[str, dict[str, int]],
) -> dict[str, Any]:
    positive_event_count = int(stats["frequency"])
    unique_positive_user_count = int(stats["user_count"])
    title = _optional_str(metadata.get("title") or metadata.get("title_clean"))
    title_ready = bool(title)
    category_ready = bool(category or main_category)
    text_ready = title_ready and category_ready
    semantic_ready = text_ready
    cf_ready = unique_positive_user_count >= thresholds["heavy_cf_eligible"]["shared_item_user_count_min"]
    two_tower_ready = positive_event_count >= thresholds["two_tower_train_eligible"]["hot_item_min_freq"] and text_ready
    fallback_ready = positive_event_count > 0 or category_ready
    quality_bucket_v2, bucket_reason = _item_quality_bucket_v2(
        positive_event_count=positive_event_count,
        unique_positive_user_count=unique_positive_user_count,
        text_ready=text_ready,
        thresholds=thresholds,
    )
    dropped_reasons = []
    if not text_ready:
        dropped_reasons.append("missing_text_or_category")
    if positive_event_count == 0:
        dropped_reasons.append("no_train_positive")
    return {
        "parent_asin": item_id,
        "positive_event_count": positive_event_count,
        "unique_positive_user_count": unique_positive_user_count,
        "train_interaction_count": int(stats["train_interaction_count"]),
        "train_positive_count": int(stats["train_positive_count"]),
        "train_strong_positive_count": int(stats["train_strong_positive_count"]),
        "global_pop_rank": global_rank,
        "category": category,
        "main_category": main_category,
        "category_pop_rank": category_rank,
        "title_ready": title_ready,
        "category_ready": category_ready,
        "text_ready": text_ready,
        "semantic_ready": semantic_ready,
        "cf_ready": cf_ready,
        "two_tower_ready": two_tower_ready,
        "fallback_ready": fallback_ready,
        "hotness_bucket": _hotness_bucket(positive_event_count, thresholds),
        "quality_bucket": _legacy_item_quality_bucket(positive_event_count),
        "quality_bucket_v2": quality_bucket_v2,
        "bucket_reason": bucket_reason,
        "dropped_reasons": dropped_reasons,
        "train_only": True,
        "source_layer": "recent_2y_train_only_governance",
    }


def _item_quality_bucket_v2(*, positive_event_count: int, unique_positive_user_count: int, text_ready: bool, thresholds: dict[str, dict[str, int]]) -> tuple[str, str]:
    if positive_event_count == 0:
        return "no_positive", "no train positive events"
    if unique_positive_user_count <= 1:
        return "single_seed", "only one unique positive user"
    if positive_event_count >= thresholds["two_tower_train_eligible"]["hot_item_min_freq"] and text_ready:
        return "embedding_ready", "hot train item with text metadata"
    if unique_positive_user_count >= thresholds["heavy_cf_eligible"]["shared_item_user_count_min"]:
        return "cf_ready", "enough unique positive users for collaborative signal"
    if positive_event_count >= thresholds["medium_behavior"]["positive_count_min"]:
        return "mid_frequency", "medium train positive volume"
    return "low_frequency", "limited train positive volume"


def _legacy_item_quality_bucket(positive_event_count: int) -> str:
    if positive_event_count == 0:
        return "no_positive"
    if positive_event_count == 1:
        return "single_seed"
    return "train_positive"


def _hotness_bucket(positive_event_count: int, thresholds: dict[str, dict[str, int]]) -> str:
    if positive_event_count == 0:
        return "none"
    if positive_event_count < thresholds["long_tail_item"]["frequency_lt"]:
        return "long_tail"
    if positive_event_count >= thresholds["two_tower_train_eligible"]["hot_item_min_freq"]:
        return "hot"
    return "mid"


def _write_user_artifacts(
    *,
    train_sequences_path: Path,
    artifact_paths: dict[str, Path],
    user_stats: dict[str, dict[str, Any]],
    item_stats: dict[str, dict[str, Any]],
    thresholds: dict[str, dict[str, int]],
    limit_users: int,
) -> dict[str, Any]:
    bucket_counts: Counter[str] = Counter()
    eligibility_counts: Counter[str] = Counter()
    users_scanned = 0
    with artifact_paths["user_quality_profile"].open("w", encoding="utf-8") as profile_sink, artifact_paths["cold_start_user_profile"].open("w", encoding="utf-8") as cold_sink:
        for row in iter_jsonl(train_sequences_path):
            users_scanned += 1
            if limit_users and users_scanned > limit_users:
                break
            user_id = str(row.get("user_id") or "")
            if not user_id:
                continue
            profile = _profile_user(row, user_stats.get(user_id), item_stats, thresholds)
            bucket_counts[profile["quality_bucket_v2"]] += 1
            for key in ("eligible_for_itemcf_strong", "eligible_for_itemcf_weak", "eligible_for_two_tower"):
                if profile[key]:
                    eligibility_counts[key] += 1
            profile_sink.write(json.dumps(profile, ensure_ascii=False) + "\n")
            if profile["quality_bucket"] == "cold_start":
                cold_sink.write(json.dumps(profile, ensure_ascii=False) + "\n")
    total_users = sum(bucket_counts.values())
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "profiled_user_count": total_users,
        "users_scanned": min(users_scanned, limit_users or users_scanned),
        "bucket_counts": {bucket: bucket_counts.get(bucket, 0) for bucket in USER_QUALITY_BUCKETS_V2},
        "bucket_ratios": {bucket: _ratio(bucket_counts.get(bucket, 0), total_users) for bucket in USER_QUALITY_BUCKETS_V2},
        "legacy_bucket_mapping": USER_QUALITY_BUCKET_V2_BY_LEGACY,
        "eligibility_counts": dict(eligibility_counts),
        "policy_mapping": {
            "itemcf_strong": "heavy_cf_eligible",
            "itemcf_weak": "heavy_cf_eligible_or_medium_behavior",
            "two_tower": "two_tower_train_eligible_or_above_with_hot_item_universe",
        },
    }
    write_json(artifact_paths["quality_bucket_summary"], summary)
    return summary


def _profile_user(row: dict[str, Any], interaction_stats: dict[str, Any] | None, item_stats: dict[str, dict[str, Any]], thresholds: dict[str, dict[str, int]]) -> dict[str, Any]:
    recent_items = _sequence_items(row.get("recent_item_sequence"))
    positive_items = _sequence_items(row.get("recent_positive_item_sequence"))
    sequence_len = _optional_int(row.get("sequence_len")) or len(recent_items)
    positive_count = int(interaction_stats["positive_count"]) if interaction_stats else (_optional_int(row.get("positive_sequence_len")) or len(positive_items))
    unique_items = set(interaction_stats["items"]) if interaction_stats else set(positive_items)
    unique_item_count = len(unique_items)
    positive_timestamps = [_optional_int(value) for value in _list_or_empty(row.get("recent_positive_timestamp_sequence"))]
    positive_timestamps = [value for value in positive_timestamps if value is not None]
    last_timestamp = interaction_stats.get("last_timestamp") if interaction_stats else (max(positive_timestamps) if positive_timestamps else None)
    first_timestamp = interaction_stats.get("first_timestamp") if interaction_stats else (min(positive_timestamps) if positive_timestamps else None)
    item_user_counts = [int(item_stats[item_id]["user_count"]) for item_id in unique_items if item_id in item_stats]
    max_item_user_count = max(item_user_counts, default=0)
    avg_item_user_count = round(sum(item_user_counts) / len(item_user_counts), 6) if item_user_counts else 0.0
    hot_item_min_freq = thresholds["two_tower_train_eligible"]["hot_item_min_freq"]
    hot_item_hit_count = sum(1 for item_id in unique_items if item_id in item_stats and int(item_stats[item_id]["frequency"]) >= hot_item_min_freq)
    bucket = _quality_bucket(
        sequence_len=sequence_len,
        positive_count=positive_count,
        unique_item_count=unique_item_count,
        max_item_user_count=max_item_user_count,
        hot_item_hit_count=hot_item_hit_count,
        thresholds=thresholds,
    )
    bucket_v2 = USER_QUALITY_BUCKET_V2_BY_LEGACY[bucket]
    return {
        "user_id": str(row.get("user_id")),
        "sequence_len": sequence_len,
        "positive_count": positive_count,
        "unique_item_count": unique_item_count,
        "recent_activity": {"first_timestamp": first_timestamp, "last_timestamp": last_timestamp},
        "shared_item_neighbor_signal": {
            "max_item_user_count": max_item_user_count,
            "avg_item_user_count": avg_item_user_count,
            "shared_item_hit": max_item_user_count >= thresholds["heavy_cf_eligible"]["shared_item_user_count_min"],
        },
        "hot_item_hit_count": hot_item_hit_count,
        "quality_bucket": bucket,
        "quality_bucket_v2": bucket_v2,
        "eligible_for_itemcf_strong": bucket_v2 == "collaborative_rich",
        "eligible_for_itemcf_weak": bucket_v2 in {"collaborative_rich", "medium_behavior"},
        "eligible_for_two_tower": bucket_v2 in {"collaborative_rich", "medium_behavior", "sequence_sufficient"},
        "eligible_for_usercf": bucket_v2 == "collaborative_rich",
        "eligible_for_swing": bucket_v2 in {"collaborative_rich", "medium_behavior"},
        "eligible_for_sequence_model": bucket_v2 in {"collaborative_rich", "medium_behavior", "sequence_sufficient"},
    }


def _quality_bucket(*, sequence_len: int, positive_count: int, unique_item_count: int, max_item_user_count: int, hot_item_hit_count: int, thresholds: dict[str, dict[str, int]]) -> str:
    heavy = thresholds["heavy_cf_eligible"]
    if positive_count >= heavy["positive_count_min"] and unique_item_count >= heavy["unique_item_count_min"] and max_item_user_count >= heavy["shared_item_user_count_min"]:
        return "heavy_cf_eligible"
    two_tower = thresholds["two_tower_train_eligible"]
    if positive_count >= two_tower["positive_count_min"] and unique_item_count >= two_tower["unique_item_count_min"] and hot_item_hit_count > 0:
        return "two_tower_train_eligible"
    medium = thresholds["medium_behavior"]
    if positive_count >= medium["positive_count_min"] and unique_item_count >= medium["unique_item_count_min"]:
        return "medium_behavior"
    cold = thresholds["cold_start"]
    if sequence_len <= cold["sequence_len_max"] or positive_count <= cold["positive_count_max"]:
        return "cold_start"
    return "fallback_only"


def _item_universe_stats_from_iter(retained_stats: Iterable[dict[str, Any]], total_positive_events: int, total_positive_user_item_pairs: int) -> dict[str, Any]:
    retained_item_count = 0
    event_count = 0
    user_item_pair_count = 0
    for stats in retained_stats:
        retained_item_count += 1
        event_count += int(stats["frequency"])
        user_item_pair_count += int(stats["user_count"])
    return {
        "retained_item_count": retained_item_count,
        "positive_event_count": event_count,
        "positive_event_coverage": _ratio(event_count, total_positive_events),
        "positive_user_item_pair_count": user_item_pair_count,
        "positive_user_item_coverage": _ratio(user_item_pair_count, total_positive_user_item_pairs),
    }


def _leakage_audit(
    *,
    clean_manifest_path: Path,
    clean_manifest: dict[str, Any],
    train_interactions_path: Path,
    train_sequences_path: Path,
    canonical_items_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    _reject_forbidden_scope_payload(clean_manifest, context="clean_manifest")
    read_files = [str(clean_manifest_path), str(train_interactions_path), str(train_sequences_path), str(canonical_items_path)]
    forbidden_inputs = [str(train_interactions_path.parent / name) for name in FORBIDDEN_INPUT_NAMES]
    scanned_paths = [*read_files, str(output_dir)]
    forbidden_hits = [path for path in scanned_paths if _is_forbidden_runtime_path(Path(path))]
    if forbidden_hits:
        raise ValueError(f"Forbidden governance path detected: {forbidden_hits}")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only": True,
        "valid_used": False,
        "test_used": False,
        "holdout_used": False,
        "lopo_used": False,
        "read_files": read_files,
        "forbidden_inputs": forbidden_inputs,
        "forbidden_path_scan": {"scanned_path_count": len(scanned_paths), "hits": []},
        "recent_2y_modified": False,
        "clean_full_modified": False,
    }


def _reject_forbidden_scope_payload(value: Any, *, context: str) -> None:
    hits = list(_forbidden_scope_hits(value, context))
    if hits:
        raise ValueError(f"Forbidden governance scope detected: {hits[:5]}")


def _forbidden_scope_hits(value: Any, context: str) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_context = f"{context}.{key}"
            if context == "clean_manifest.split_paths" and str(key) != "train":
                continue
            if context in {"clean_manifest.window_policy.splits", "clean_manifest.counts.interactions"}:
                yield from _forbidden_scope_hits(nested, key_context)
                continue
            if _text_has_forbidden_scope(str(key)):
                yield key_context
            yield from _forbidden_scope_hits(nested, key_context)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _forbidden_scope_hits(nested, f"{context}[{index}]")
    elif isinstance(value, (str, Path)):
        if _text_has_forbidden_scope(str(value)):
            yield context


def _text_has_forbidden_scope(value: str) -> bool:
    lowered = value.replace("\\", "/").lower()
    if "eval_label" in lowered or "clean_10000" in lowered:
        return True
    parts = {part for part in re.split(r"[^a-z0-9]+", lowered) if part}
    return bool(parts & set(FORBIDDEN_SCOPE_TOKENS))


def _is_forbidden_runtime_path(path: Path) -> bool:
    name = path.name.lower()
    if name in FORBIDDEN_INPUT_NAMES:
        return True
    allowed_train_names = {"canonical_interactions.train.jsonl", "user_sequences.train.jsonl", "canonical_items.jsonl", "manifest.json"}
    if name in allowed_train_names:
        return False
    return _path_has_forbidden_scope(path)


def _path_has_forbidden_scope(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & set(FORBIDDEN_SCOPE_TOKENS):
        return True
    lowered = str(path).replace("\\", "/").lower()
    return "eval_label" in lowered or "clean_10000" in lowered or "pool1000" in lowered or "oracle" in lowered


def _artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "user_quality_profile": output_dir / "user_quality_profile.jsonl",
        "eligible_user_quality_manifest": output_dir / "eligible_user_quality_manifest.json",
        "quality_bucket_summary": output_dir / "quality_bucket_summary.json",
        "item_frequency_train": output_dir / "item_frequency_train.jsonl",
        "item_universe_summary": output_dir / "item_universe_summary.json",
        "item_quality_profile": output_dir / "item_quality_profile.jsonl",
        "item_quality_summary": output_dir / "item_quality_summary.json",
        "cold_start_user_profile": output_dir / "cold_start_user_profile.jsonl",
        "long_tail_item_profile": output_dir / "long_tail_item_profile.jsonl",
        "leakage_audit": output_dir / "leakage_audit.json",
        "manifest": output_dir / "manifest.json",
    }


def _counter_top(counter: Counter[str]) -> str | None:
    if not counter:
        return None
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _sequence_items(value: Any) -> list[str]:
    return [str(item) for item in _list_or_empty(value) if item]


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _ratio(numerator: int, denominator: int) -> float:
    return 0.0 if denominator == 0 else round(numerator / denominator, 6)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_ancestor(path: Path) -> Path:
    current = path.resolve()
    while not current.exists():
        if current.parent == current:
            return current
        current = current.parent
    return current


def _thresholds_from_args(args: argparse.Namespace) -> dict[str, dict[str, int]]:
    return {
        "cold_start": {"sequence_len_max": args.cold_start_sequence_len_max, "positive_count_max": args.cold_start_positive_count_max},
        "medium_behavior": {"positive_count_min": args.medium_positive_count_min, "unique_item_count_min": args.medium_unique_item_count_min},
        "heavy_cf_eligible": {"positive_count_min": args.heavy_positive_count_min, "unique_item_count_min": args.heavy_unique_item_count_min, "shared_item_user_count_min": args.heavy_shared_item_user_count_min},
        "two_tower_train_eligible": {"positive_count_min": args.two_tower_positive_count_min, "unique_item_count_min": args.two_tower_unique_item_count_min, "hot_item_min_freq": args.two_tower_hot_item_min_freq},
        "long_tail_item": {"frequency_lt": args.long_tail_frequency_lt},
    }


def main() -> None:
    args = parse_args()
    manifest = build_train_only_data_governance(
        clean_manifest_path=Path(args.clean_manifest),
        output_dir=Path(args.output_dir),
        thresholds=_thresholds_from_args(args),
        scale_tier=args.scale_tier,
        limit_users=args.limit_users,
        limit_interactions=args.limit_interactions,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "output_dir": manifest["output_dir"],
                "profiled_user_count": manifest["quality_bucket_summary"]["profiled_user_count"],
                "total_item_count": manifest["item_universe_summary"]["total_item_count"],
                "leakage_audit_path": manifest["artifacts"]["leakage_audit"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
