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

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_two_tower_method_dataset_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_GOVERNANCE_MANIFEST = ROOT / "outputs" / "recall" / "data_governance" / "train_only_v1" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_method_datasets" / "two_tower" / "train_only_v1"
FORBIDDEN_SCOPE_TOKENS = ("valid", "validation", "test", "holdout", "lopo", "eval_label", "oracle", "clean_10000", "pool1000")
FORBIDDEN_INPUT_NAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_OUTPUT_NAMES = {
    "source_index_manifest.json",
    "candidates.jsonl",
    "artifact_manifest.json",
    "item_embeddings.jsonl",
    "user_embeddings.jsonl",
    "two_tower_recall_index.jsonl",
}
FORBIDDEN_MANIFEST_FIELDS = {
    "source_index_manifest_path",
    "artifact_manifest_path",
    "embedding_path",
    "index_path",
    "candidates",
    "candidate_path",
}
OUTPUT_FILES = {
    "two_tower_train_samples": "two_tower_train_samples.jsonl",
    "negative_item_universe": "negative_item_universe.jsonl",
    "training_item_universe": "training_item_universe.jsonl",
    "method_dataset_manifest": "method_dataset_manifest.json",
    "leakage_audit": "leakage_audit.json",
}
SCALE_TIERS = {
    "smoke": {"limit_users": 500, "max_samples": 20_000, "negative_ratio": 3, "max_items_per_user": 30},
    "diagnostic": {"limit_users": 50_000, "max_samples": 800_000, "negative_ratio": 5, "max_items_per_user": 50},
    "local_formal": {"limit_users": 150_000, "max_samples": 2_000_000, "negative_ratio": 5, "max_items_per_user": 80},
}
ELIGIBLE_USER_BUCKETS = {"sequence_sufficient", "collaborative_rich", "medium_behavior"}
ELIGIBLE_ITEM_BUCKETS = {"embedding_ready"}
NEGATIVE_UNIVERSE_POLICY = "p1_item_quality_profile_v2_embedding_ready_joined_with_item_frequency_train"
TARGET_ITEM_POLICY = "train_only_sequence_positive_targets_not_constrained_to_negative_universe"
TRAINING_ITEM_UNIVERSE_POLICY = "negative_universe_plus_sampled_train_sequence_targets"
PER_USER_NEGATIVE_UNIVERSE_POLICY = "global_negative_universe_minus_user_known_history_and_current_target"
PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY = "deterministic_diversified_rotated_negatives_after_per_user_exclusions"
EVAL_TARGET_UNIVERSE_POLICY = "phase1_not_built"
ELIGIBLE_TARGET_UNIVERSE_POLICY = "sampled_train_sequence_targets_only"
FORBIDDEN_DATA_USES = ["training", "negative_sampling", "index_build", "official_candidate_generation"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build independent train-only pool500 TwoTower method dataset artifacts.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--governance-manifest", default=str(DEFAULT_GOVERNANCE_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--scale-tier", choices=tuple(SCALE_TIERS), default="local_formal")
    parser.add_argument("--limit-users", type=int, default=None)
    parser.add_argument("--limit-interactions", type=int, default=0)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--negative-ratio", type=int, default=None)
    parser.add_argument("--max-items-per-user", type=int, default=None)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_two_tower_method_dataset(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    governance_manifest_path: Path = DEFAULT_GOVERNANCE_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    scale_tier: str = "local_formal",
    limit_users: int | None = None,
    limit_interactions: int = 0,
    max_samples: int | None = None,
    negative_ratio: int | None = None,
    max_items_per_user: int | None = None,
    min_free_bytes: int = 0,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    limits = _resolve_limits(
        scale_tier=scale_tier,
        limit_users=limit_users,
        limit_interactions=limit_interactions,
        max_samples=max_samples,
        negative_ratio=negative_ratio,
        max_items_per_user=max_items_per_user,
        min_free_bytes=min_free_bytes,
    )
    _validate_limits(**limits)

    clean_manifest_path = clean_manifest_path.resolve()
    governance_manifest_path = governance_manifest_path.resolve()
    output_dir = output_dir.resolve()
    _precheck_input_path(clean_manifest_path, expected_name="manifest.json")
    _precheck_input_path(governance_manifest_path, expected_name="manifest.json")
    _precheck_output_dir(output_dir, overwrite)

    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if disk_free_start < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below --min-free-bytes: {disk_free_start} < {min_free_bytes}")

    clean_manifest = read_json(clean_manifest_path)
    governance_manifest = read_json(governance_manifest_path)
    _reject_forbidden_payload(clean_manifest, context="clean_manifest")
    _validate_governance_manifest(governance_manifest)
    train_sequences_path = _resolve_train_sequences_path(clean_manifest_path, clean_manifest)
    canonical_items_path = _resolve_canonical_items_path(clean_manifest_path, clean_manifest)
    artifact_paths = _resolve_governance_artifacts(governance_manifest_path, governance_manifest)
    read_files = [clean_manifest_path, governance_manifest_path, train_sequences_path, canonical_items_path, *artifact_paths.values()]
    for path in read_files:
        _precheck_train_scope_path(path)

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)

    user_profiles = _load_user_profiles(artifact_paths["user_quality_profile"])
    negative_universe, universe_audit = _load_negative_universe(
        item_quality_profile_path=artifact_paths["item_quality_profile"],
        item_frequency_train_path=artifact_paths["item_frequency_train"],
    )
    universe_path = output_dir / OUTPUT_FILES["negative_item_universe"]
    _write_jsonl(universe_path, negative_universe)

    samples_path = output_dir / OUTPUT_FILES["two_tower_train_samples"]
    sample_stats = _write_train_samples(
        samples_path=samples_path,
        train_sequences_path=train_sequences_path,
        eligible_user_profiles=user_profiles,
        negative_universe=negative_universe,
        limit_users=limits["limit_users"],
        limit_interactions=limits["limit_interactions"],
        max_samples=limits["max_samples"],
        negative_ratio=limits["negative_ratio"],
        max_items_per_user=limits["max_items_per_user"],
    )
    sample_target_item_counts = sample_stats.pop("_sample_target_item_counts")
    training_universe_path = output_dir / OUTPUT_FILES["training_item_universe"]
    training_universe_stats = _write_training_item_universe(
        path=training_universe_path,
        negative_universe=negative_universe,
        sample_target_item_counts=sample_target_item_counts,
        item_quality_profile_path=artifact_paths["item_quality_profile"],
        item_frequency_train_path=artifact_paths["item_frequency_train"],
        canonical_items_path=canonical_items_path,
    )
    universe_definitions = _phase1_universe_definitions()
    data_usage_boundary = _phase1_data_usage_boundary()
    target_coverage_stats = _target_coverage_stats(
        sample_target_item_counts=sample_target_item_counts,
        negative_universe=negative_universe,
        training_universe_stats=training_universe_stats,
    )

    output_paths = {name: str(output_dir / file_name) for name, file_name in OUTPUT_FILES.items()}
    resource_scale_policy = _resource_scale_policy(scale_tier, limits)
    leakage_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only": True,
        "valid_used": False,
        "test_used": False,
        "holdout_used": False,
        "lopo_used": False,
        "oracle_used": False,
        "embedding_or_index_used": False,
        "read_files": [str(path) for path in read_files],
        "negative_universe_sources": [str(artifact_paths["item_quality_profile"]), str(artifact_paths["item_frequency_train"])],
        "forbidden_output_names": sorted(FORBIDDEN_OUTPUT_NAMES),
        "forbidden_manifest_fields": sorted(FORBIDDEN_MANIFEST_FIELDS),
    }
    write_json(output_dir / OUTPUT_FILES["leakage_audit"], leakage_audit)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "two_tower",
        "dataset_role": "train_only_two_tower_method_dataset",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "clean_manifest_path": str(clean_manifest_path),
        "governance_manifest_path": str(governance_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "canonical_items_path": str(canonical_items_path),
        "input_artifacts": {name: str(path) for name, path in artifact_paths.items()},
        "negative_universe_policy": NEGATIVE_UNIVERSE_POLICY,
        "target_item_policy": TARGET_ITEM_POLICY,
        "training_item_universe_policy": TRAINING_ITEM_UNIVERSE_POLICY,
        "per_user_negative_universe_policy": PER_USER_NEGATIVE_UNIVERSE_POLICY,
        "per_example_negative_universe_policy": PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY,
        "eval_target_universe_policy": EVAL_TARGET_UNIVERSE_POLICY,
        "eligible_target_universe_policy": ELIGIBLE_TARGET_UNIVERSE_POLICY,
        "eval_target_universe_available": False,
        "retrieval_item_universe_available": False,
        "universe_definitions": universe_definitions,
        "data_usage_boundary": data_usage_boundary,
        "eligible_user_buckets": sorted(ELIGIBLE_USER_BUCKETS),
        "eligible_item_quality_bucket_v2": sorted(ELIGIBLE_ITEM_BUCKETS),
        "limits": limits,
        "resource_scale_policy": resource_scale_policy,
        "stats": {**universe_audit, **sample_stats, **training_universe_stats, **target_coverage_stats},
        "outputs": output_paths,
        "input_hashes": {path.name: _file_sha256(path) for path in read_files},
        "output_hashes": {name: _file_sha256(Path(path)) for name, path in output_paths.items() if Path(path).is_file()},
        "resource_summary": {
            "disk_free_bytes_start": disk_free_start,
            "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
            "runtime_seconds": round(perf_counter() - started, 6),
        },
    }
    _assert_manifest_has_no_forbidden_fields(manifest)
    write_json(output_dir / OUTPUT_FILES["method_dataset_manifest"], manifest)
    return manifest


def _resolve_limits(
    *,
    scale_tier: str,
    limit_users: int | None,
    limit_interactions: int,
    max_samples: int | None,
    negative_ratio: int | None,
    max_items_per_user: int | None,
    min_free_bytes: int,
) -> dict[str, int]:
    if scale_tier not in SCALE_TIERS:
        raise ValueError(f"Unsupported scale_tier: {scale_tier}")
    tier_limits = SCALE_TIERS[scale_tier]
    return {
        "limit_users": tier_limits["limit_users"] if limit_users is None else limit_users,
        "limit_interactions": limit_interactions,
        "max_samples": tier_limits["max_samples"] if max_samples is None else max_samples,
        "negative_ratio": tier_limits["negative_ratio"] if negative_ratio is None else negative_ratio,
        "max_items_per_user": tier_limits["max_items_per_user"] if max_items_per_user is None else max_items_per_user,
        "min_free_bytes": min_free_bytes,
    }


def _resource_scale_policy(scale_tier: str, limits: dict[str, int]) -> dict[str, Any]:
    return {
        "input_scope": "governance_train_only",
        "scale_tier": scale_tier,
        "default_tier": "local_formal",
        "scale_tiers": SCALE_TIERS,
        "selection_policy_version": "p2_method_dataset_policy_v1",
        "selection_strategy": {
            "policy_name": "two_tower_sequence_v1",
            "sampling_unit": "user_sequence",
            "preserve_order": True,
            "sequence_contract": "future_history_items_to_target_item",
            "exclude_non_train_future_events": True,
        },
        "sample_strategy": "sequence_to_target_transition_contract",
        "target_item_policy": TARGET_ITEM_POLICY,
        "training_item_universe_policy": TRAINING_ITEM_UNIVERSE_POLICY,
        "eligible_user_buckets": sorted(ELIGIBLE_USER_BUCKETS),
        "eligible_item_quality_bucket_v2": sorted(ELIGIBLE_ITEM_BUCKETS),
        "negative_universe_policy": NEGATIVE_UNIVERSE_POLICY,
        "per_user_negative_universe_policy": PER_USER_NEGATIVE_UNIVERSE_POLICY,
        "per_example_negative_universe_policy": PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY,
        "eval_target_universe_policy": EVAL_TARGET_UNIVERSE_POLICY,
        "eligible_target_universe_policy": ELIGIBLE_TARGET_UNIVERSE_POLICY,
        "limits": dict(limits),
        "p2_contract_scope": "method_dataset_only",
    }


def _phase1_universe_definitions() -> dict[str, Any]:
    return {
        "schema_version": "pool500_two_tower_phase1_universe_definitions_v1",
        "phase": "phase1_manifest_only",
        "training_item_universe": {
            "available": True,
            "artifact": OUTPUT_FILES["training_item_universe"],
            "policy": TRAINING_ITEM_UNIVERSE_POLICY,
        },
        "retrieval_item_universe": {
            "available": False,
            "reason": "phase1_not_built",
            "candidate_generation_allowed": False,
        },
        "global_negative_universe": {
            "available": True,
            "artifact": OUTPUT_FILES["negative_item_universe"],
            "policy": NEGATIVE_UNIVERSE_POLICY,
        },
        "per_user_negative_universe_policy": {
            "available": True,
            "policy": PER_USER_NEGATIVE_UNIVERSE_POLICY,
        },
        "per_example_negative_universe_policy": {
            "available": True,
            "policy": PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY,
        },
        "eval_target_universe": {
            "available": False,
            "policy": EVAL_TARGET_UNIVERSE_POLICY,
            "reason": "phase1_not_built",
        },
        "eligible_target_universe": {
            "available": True,
            "policy": ELIGIBLE_TARGET_UNIVERSE_POLICY,
        },
    }


def _phase1_data_usage_boundary() -> dict[str, Any]:
    restricted_artifact = {
        "allowed_uses": ["diagnostic_eval_only"],
        "forbidden_uses": list(FORBIDDEN_DATA_USES),
    }
    return {
        "schema_version": "pool500_two_tower_data_usage_boundary_v1",
        "diagnostic_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "label_artifacts": restricted_artifact,
        "oracle_artifacts": restricted_artifact,
        "diagnostic_oracle_artifacts": restricted_artifact,
    }


def _target_coverage_stats(*, sample_target_item_counts: Counter[str], negative_universe: list[dict[str, Any]], training_universe_stats: dict[str, Any]) -> dict[str, Any]:
    target_items = set(sample_target_item_counts)
    negative_items = {str(row["parent_asin"]) for row in negative_universe}
    targets_in_negative = target_items & negative_items
    target_occurrences = sum(sample_target_item_counts.values())
    target_occurrences_in_negative = sum(count for item_id, count in sample_target_item_counts.items() if item_id in negative_items)
    return {
        "raw_target_occurrence_count": target_occurrences,
        "eligible_target_occurrence_count": target_occurrences,
        "excluded_target_occurrence_count": 0,
        "sample_target_items_in_training_universe_count": training_universe_stats["training_item_universe_positive_target_count"],
        "sample_target_items_missing_training_universe_count": 0,
        "sample_target_items_in_negative_universe_count": len(targets_in_negative),
        "sample_target_items_outside_negative_universe_count": len(target_items - negative_items),
        "sample_target_occurrences_in_negative_universe_count": target_occurrences_in_negative,
        "sample_target_occurrences_outside_negative_universe_count": target_occurrences - target_occurrences_in_negative,
        "retrieval_item_universe_available": False,
        "retrieval_item_universe_coverage_status": "phase1_not_built",
        "eval_target_universe_available": False,
        "eval_target_universe_coverage_status": "phase1_not_built",
    }


def _validate_limits(limit_users: int, limit_interactions: int, max_samples: int, negative_ratio: int, max_items_per_user: int, min_free_bytes: int) -> None:
    if limit_users <= 0:
        raise ValueError("limit_users must be positive")
    if limit_interactions < 0:
        raise ValueError("limit_interactions must be non-negative")
    if max_samples <= 0:
        raise ValueError("max_samples must be positive")
    if negative_ratio <= 0:
        raise ValueError("negative_ratio must be positive")
    if max_items_per_user <= 0:
        raise ValueError("max_items_per_user must be positive")
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


def _resolve_train_sequences_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path")
    if not raw_path:
        raise ValueError("clean manifest must provide train_user_sequences_path")
    path = _resolve_repo_path(manifest_path, raw_path)
    if path.name != "user_sequences.train.jsonl":
        raise ValueError(f"TwoTower dataset builder must read user_sequences.train.jsonl, got {path.name}")
    return path


def _resolve_canonical_items_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("canonical_items_path")
    if not raw_path:
        raise ValueError("clean manifest must provide canonical_items_path")
    path = _resolve_repo_path(manifest_path, raw_path)
    if path.name != "canonical_items.jsonl":
        raise ValueError(f"TwoTower dataset builder must read canonical_items.jsonl, got {path.name}")
    return path


def _resolve_governance_artifacts(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("governance manifest missing artifacts")
    required = ("user_quality_profile", "item_quality_profile", "item_frequency_train")
    missing = [name for name in required if not artifacts.get(name)]
    if missing:
        raise ValueError(f"governance manifest missing required P1 artifacts: {missing}")
    return {name: _resolve_repo_path(manifest_path, artifacts[name]) for name in required}


def _validate_governance_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schema_version") != "train_only_data_governance_v1":
        raise ValueError(f"Unexpected governance schema_version: {manifest.get('schema_version')}")
    if manifest.get("train_only") is not True:
        raise ValueError("governance manifest must be train_only")
    policies = manifest.get("derived_dataset_policies")
    if not isinstance(policies, dict) or "two_tower" not in policies:
        raise ValueError("governance manifest missing two_tower derived dataset policy")
    policy = policies["two_tower"]
    if "item_quality_profile.jsonl" not in policy.get("train_only_inputs", []):
        raise ValueError("two_tower policy must require item_quality_profile.jsonl")


def _precheck_input_path(path: Path, *, expected_name: str) -> None:
    if path.name != expected_name:
        raise ValueError(f"Expected {expected_name}, got {path.name}")
    _precheck_train_scope_path(path)


def _precheck_train_scope_path(path: Path) -> None:
    if _path_has_forbidden_scope(path):
        raise ValueError(f"Forbidden non-train path is not allowed: {path}")
    if path.name in FORBIDDEN_OUTPUT_NAMES:
        raise ValueError(f"Forbidden source/index artifact is not allowed: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)


def _precheck_output_dir(output_dir: Path, overwrite: bool) -> None:
    if _path_has_forbidden_scope(output_dir):
        raise ValueError(f"Forbidden output path is not allowed: {output_dir}")
    if output_dir.name in FORBIDDEN_OUTPUT_NAMES:
        raise ValueError(f"Forbidden output artifact name is not allowed: {output_dir}")
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")


def _path_has_forbidden_scope(path: Path) -> bool:
    lowered = str(path).replace("\\", "/").lower()
    parts = {part.lower() for part in path.parts}
    return (
        path.name.lower() in FORBIDDEN_INPUT_NAMES
        or bool(parts & set(FORBIDDEN_SCOPE_TOKENS))
        or "eval_label" in lowered
        or "clean_10000" in lowered
        or "source_index" in lowered
        or "embedding" in lowered
        or "faiss" in lowered
        or "/ann/" in lowered
    )


def _reject_forbidden_payload(value: Any, *, context: str) -> None:
    hits = list(_forbidden_payload_hits(value, context))
    if hits:
        raise ValueError(f"Forbidden non-train scope detected: {hits[:5]}")


def _forbidden_payload_hits(value: Any, context: str):
    if isinstance(value, dict):
        for key, nested in value.items():
            if context == "clean_manifest.split_paths" and str(key) != "train":
                continue
            yield from _forbidden_payload_hits(nested, f"{context}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _forbidden_payload_hits(nested, f"{context}[{index}]")
    elif isinstance(value, (str, Path)):
        path = Path(str(value))
        parts = {part.lower() for part in path.parts}
        if path.name.lower() in FORBIDDEN_INPUT_NAMES or parts & set(FORBIDDEN_SCOPE_TOKENS):
            yield context


def _load_user_profiles(path: Path) -> dict[str, dict[str, Any]]:
    profiles = {}
    missing_bucket = 0
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if not user_id:
            continue
        if "quality_bucket_v2" not in row:
            missing_bucket += 1
            continue
        bucket = str(row["quality_bucket_v2"])
        if bucket in ELIGIBLE_USER_BUCKETS and bool(row.get("eligible_for_two_tower", bucket in ELIGIBLE_USER_BUCKETS)):
            profiles[user_id] = row
    if missing_bucket:
        raise ValueError("P1 user_quality_profile missing required quality_bucket_v2 field")
    if not profiles:
        raise ValueError("P1 user_quality_profile produced no eligible two_tower users")
    return profiles


def _load_negative_universe(*, item_quality_profile_path: Path, item_frequency_train_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frequency_by_item = {}
    for row in iter_jsonl(item_frequency_train_path):
        item_id = str(row.get("parent_asin") or "")
        if item_id:
            frequency_by_item[item_id] = row
    if not frequency_by_item:
        raise ValueError("P1 item_frequency_train is empty")

    rows = []
    bucket_counts: Counter[str] = Counter()
    missing_v2 = 0
    for row in iter_jsonl(item_quality_profile_path):
        item_id = str(row.get("parent_asin") or "")
        if not item_id:
            continue
        bucket = row.get("quality_bucket_v2")
        if not bucket:
            missing_v2 += 1
            continue
        bucket = str(bucket)
        bucket_counts[bucket] += 1
        frequency = frequency_by_item.get(item_id)
        if bucket not in ELIGIBLE_ITEM_BUCKETS or frequency is None:
            continue
        rows.append(
            {
                "parent_asin": item_id,
                "frequency": int(frequency.get("frequency", row.get("positive_event_count", 0)) or 0),
                "user_count": int(frequency.get("user_count", row.get("unique_positive_user_count", 0)) or 0),
                "quality_bucket_v2": bucket,
                "global_pop_rank": int(row.get("global_pop_rank", len(rows) + 1) or len(rows) + 1),
                "source_layer": "p1_governance_train_only",
            }
        )
    if missing_v2:
        raise ValueError("P1 item_quality_profile missing required quality_bucket_v2 field")
    if not rows:
        raise ValueError("P1 item_quality_profile has no embedding_ready negative universe items")
    rows.sort(key=lambda row: (-int(row["frequency"]), int(row["global_pop_rank"]), str(row["parent_asin"])))
    return rows, {
        "negative_universe_item_count": len(rows),
        "item_quality_bucket_v2_counts": dict(sorted(bucket_counts.items())),
        "negative_universe_source_files": [str(item_quality_profile_path), str(item_frequency_train_path)],
    }


def _write_train_samples(
    *,
    samples_path: Path,
    train_sequences_path: Path,
    eligible_user_profiles: dict[str, dict[str, Any]],
    negative_universe: list[dict[str, Any]],
    limit_users: int,
    limit_interactions: int,
    max_samples: int,
    negative_ratio: int,
    max_items_per_user: int,
) -> dict[str, Any]:
    negative_items = [str(row["parent_asin"]) for row in negative_universe]
    negative_item_set = set(negative_items)
    rows_scanned = 0
    eligible_users_seen = 0
    interactions_seen = 0
    sample_count = 0
    skipped_target_not_in_universe = 0
    targets_outside_negative_universe = 0
    negatives_per_sample: list[int] = []
    target_item_counts: Counter[str] = Counter()
    used_negative_item_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    negative_item_count_under_requested_count = 0
    with samples_path.open("w", encoding="utf-8") as sink:
        for row in iter_jsonl(train_sequences_path):
            rows_scanned += 1
            user_id = str(row.get("user_id") or "")
            profile = eligible_user_profiles.get(user_id)
            if profile is None:
                continue
            eligible_users_seen += 1
            bucket_counts[str(profile["quality_bucket_v2"])] += 1
            positives = _recent_unique_items(row.get("recent_positive_item_sequence"), max_items_per_user)
            known_items = set(_recent_unique_items(row.get("recent_item_sequence"), max_items_per_user * 2)) | set(positives)
            for target_index in range(1, len(positives)):
                target_item = positives[target_index]
                interactions_seen += 1
                if limit_interactions and interactions_seen > limit_interactions:
                    return _sample_stats(
                        rows_scanned,
                        eligible_users_seen,
                        interactions_seen - 1,
                        sample_count,
                        negatives_per_sample,
                        bucket_counts,
                        skipped_target_not_in_universe,
                        targets_outside_negative_universe,
                        target_item_counts,
                        used_negative_item_counts,
                        negative_item_count_under_requested_count,
                        negative_ratio,
                    )
                if target_item not in negative_item_set:
                    targets_outside_negative_universe += 1
                history_items = positives[:target_index]
                excluded_items = known_items | set(history_items) | {target_item}
                eligible_negatives = [item_id for item_id in negative_items if item_id not in excluded_items]
                negatives = _deterministic_rotated_negatives(
                    eligible_negatives,
                    user_id=user_id,
                    target_item=target_item,
                    target_index=target_index,
                    negative_ratio=negative_ratio,
                )
                if not negatives:
                    continue
                if len(negatives) < negative_ratio:
                    negative_item_count_under_requested_count += 1
                sink.write(
                    json.dumps(
                        {
                            "user_id": user_id,
                            "history_items": history_items,
                            "target_item": target_item,
                            "positive_item_id": target_item,
                            "negative_item_ids": negatives,
                            "target_item_source": "train_only_user_sequence",
                            "label": 1,
                            "source": "two_tower_method_dataset",
                            "quality_bucket": profile.get("quality_bucket"),
                            "quality_bucket_v2": profile["quality_bucket_v2"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                sample_count += 1
                target_item_counts[target_item] += 1
                used_negative_item_counts.update(negatives)
                negatives_per_sample.append(len(negatives))
                if sample_count >= max_samples:
                    return _sample_stats(
                        rows_scanned,
                        eligible_users_seen,
                        interactions_seen,
                        sample_count,
                        negatives_per_sample,
                        bucket_counts,
                        skipped_target_not_in_universe,
                        targets_outside_negative_universe,
                        target_item_counts,
                        used_negative_item_counts,
                        negative_item_count_under_requested_count,
                        negative_ratio,
                    )
            if eligible_users_seen >= limit_users:
                break
    return _sample_stats(
        rows_scanned,
        eligible_users_seen,
        interactions_seen,
        sample_count,
        negatives_per_sample,
        bucket_counts,
        skipped_target_not_in_universe,
        targets_outside_negative_universe,
        target_item_counts,
        used_negative_item_counts,
        negative_item_count_under_requested_count,
        negative_ratio,
    )


def _sample_stats(
    rows_scanned: int,
    eligible_users_seen: int,
    interactions_seen: int,
    sample_count: int,
    negatives_per_sample: list[int],
    bucket_counts: Counter[str],
    skipped_target_not_in_universe: int,
    targets_outside_negative_universe: int,
    target_item_counts: Counter[str],
    used_negative_item_counts: Counter[str],
    negative_item_count_under_requested_count: int,
    negative_ratio: int,
) -> dict[str, Any]:
    used_negative_occurrences = sum(used_negative_item_counts.values())
    top10_occurrences = sum(count for _, count in used_negative_item_counts.most_common(10))
    return {
        "train_sequence_rows_scanned": rows_scanned,
        "eligible_user_count": eligible_users_seen,
        "positive_interactions_seen": interactions_seen,
        "target_items_skipped_not_in_negative_universe": skipped_target_not_in_universe,
        "target_items_outside_negative_universe": targets_outside_negative_universe,
        "train_sample_count": sample_count,
        "negative_item_count_min": min(negatives_per_sample, default=0),
        "negative_item_count_max": max(negatives_per_sample, default=0),
        "negative_item_count_mean": round(sum(negatives_per_sample) / sample_count, 6) if sample_count else 0.0,
        "negative_item_count_under_requested_count": negative_item_count_under_requested_count,
        "negative_ratio_requested": negative_ratio,
        "sample_target_item_count": len(target_item_counts),
        "used_negative_distinct_item_count": len(used_negative_item_counts),
        "used_negative_item_occurrence_count": used_negative_occurrences,
        "used_negative_item_coverage_ratio": round(len(used_negative_item_counts) / used_negative_occurrences, 6) if used_negative_occurrences else 0.0,
        "negative_item_usage_top1_count": used_negative_item_counts.most_common(1)[0][1] if used_negative_item_counts else 0,
        "negative_item_usage_top10_share": round(top10_occurrences / used_negative_occurrences, 6) if used_negative_occurrences else 0.0,
        "used_quality_bucket_counts": dict(sorted(bucket_counts.items())),
        "_sample_target_item_counts": target_item_counts,
    }


def _deterministic_rotated_negatives(eligible_negatives: list[str], *, user_id: str, target_item: str, target_index: int, negative_ratio: int) -> list[str]:
    if not eligible_negatives:
        return []
    digest = hashlib.sha256(f"{user_id}␟{target_item}␟{target_index}".encode("utf-8")).digest()
    offset = int.from_bytes(digest[:8], "big") % len(eligible_negatives)
    rotated = eligible_negatives[offset:] + eligible_negatives[:offset]
    return rotated[:negative_ratio]


def _write_training_item_universe(
    *,
    path: Path,
    negative_universe: list[dict[str, Any]],
    sample_target_item_counts: Counter[str],
    item_quality_profile_path: Path,
    item_frequency_train_path: Path,
    canonical_items_path: Path,
) -> dict[str, Any]:
    negative_by_item = {str(row["parent_asin"]): row for row in negative_universe}
    target_ids = set(sample_target_item_counts)
    universe_ids = set(negative_by_item) | target_ids
    frequency_by_target = _load_target_frequency(item_frequency_train_path, target_ids)
    quality_by_target = _load_target_quality(item_quality_profile_path, target_ids)
    metadata_by_item = _load_item_metadata(canonical_items_path, universe_ids)
    written: set[str] = set()
    missing_quality = 0
    missing_frequency = 0
    positive_target_metadata_incomplete = 0
    with path.open("w", encoding="utf-8") as sink:
        for item_id, row in sorted(negative_by_item.items(), key=lambda item: (-int(item[1].get("frequency", 0)), int(item[1].get("global_pop_rank", 0)), item[0])):
            roles = ["negative_candidate"]
            if item_id in target_ids:
                roles.append("positive_target")
            universe_row = _training_universe_row(item_id, row, roles, sample_target_item_counts.get(item_id, 0), metadata_by_item.get(item_id, {}))
            if "positive_target" in roles and _positive_target_metadata_incomplete(universe_row):
                positive_target_metadata_incomplete += 1
            sink.write(json.dumps(universe_row, ensure_ascii=False) + "\n")
            written.add(item_id)
        for item_id in sorted(target_ids - written):
            quality = quality_by_target.get(item_id)
            frequency = frequency_by_target.get(item_id)
            if quality is None:
                missing_quality += 1
                quality = {"parent_asin": item_id, "quality_bucket_v2": "missing_p1_quality", "global_pop_rank": 0}
            if frequency is None:
                missing_frequency += 1
                frequency = {"frequency": quality.get("positive_event_count", 0), "user_count": quality.get("unique_positive_user_count", 0)}
            row = {
                "parent_asin": item_id,
                "frequency": int(frequency.get("frequency", quality.get("positive_event_count", 0)) or 0),
                "user_count": int(frequency.get("user_count", quality.get("unique_positive_user_count", 0)) or 0),
                "quality_bucket_v2": str(quality.get("quality_bucket_v2") or "missing_p1_quality"),
                "global_pop_rank": int(quality.get("global_pop_rank", 0) or 0),
                "source_layer": "p1_governance_train_only",
            }
            universe_row = _training_universe_row(item_id, row, ["positive_target"], sample_target_item_counts[item_id], metadata_by_item.get(item_id, {}))
            if _positive_target_metadata_incomplete(universe_row):
                positive_target_metadata_incomplete += 1
            sink.write(json.dumps(universe_row, ensure_ascii=False) + "\n")
            written.add(item_id)
    return {
        "training_item_universe_item_count": len(written),
        "training_item_universe_policy": TRAINING_ITEM_UNIVERSE_POLICY,
        "training_item_universe_negative_candidate_count": len(negative_by_item),
        "training_item_universe_positive_target_count": len(target_ids),
        "training_item_universe_metadata_item_count": len(metadata_by_item),
        "training_item_universe_target_items_missing_p1_quality": missing_quality,
        "training_item_universe_target_items_missing_frequency": missing_frequency,
        "training_item_universe_positive_target_metadata_incomplete_count": positive_target_metadata_incomplete,
    }


def _training_universe_row(item_id: str, row: dict[str, Any], roles: list[str], sample_target_count: int, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "parent_asin": item_id,
        "item_id": item_id,
        "frequency": int(row.get("frequency", 0) or 0),
        "user_count": int(row.get("user_count", 0) or 0),
        "quality_bucket_v2": str(row.get("quality_bucket_v2") or "unknown"),
        "global_pop_rank": int(row.get("global_pop_rank", 0) or 0),
        "item_roles": roles,
        "sample_target_count": int(sample_target_count),
        "title_clean": _metadata_text(metadata, "title_clean", "title"),
        "main_category": _metadata_text(metadata, "main_category", "category"),
        "category": _metadata_text(metadata, "category", "main_category"),
        "description_text": _metadata_text(metadata, "description_text", "description"),
        "features_text": _metadata_list_text(metadata, "features_text", "features"),
        "item_text": _metadata_item_text(metadata),
        "categories_flat": _metadata_list_text(metadata, "categories_flat", "categories"),
        "source_layer": str(row.get("source_layer") or "p1_governance_train_only"),
    }


def _positive_target_metadata_incomplete(row: dict[str, Any]) -> bool:
    return not row.get("title_clean") or not row.get("item_text") or not (row.get("main_category") or row.get("category"))


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list):
            text = " ".join(str(item) for item in value if item)
        else:
            text = str(value or "")
        if text:
            return text
    return ""


def _metadata_item_text(metadata: dict[str, Any]) -> str:
    direct = _metadata_text(metadata, "item_text")
    if direct:
        return direct
    return " ".join(
        value
        for value in (
            _metadata_text(metadata, "title_clean", "title"),
            _metadata_text(metadata, "main_category", "category"),
            _metadata_text(metadata, "description_text", "description"),
            _metadata_list_text(metadata, "features_text", "features"),
        )
        if value
    )


def _metadata_list_text(metadata: dict[str, Any], *keys: str) -> str:
    return _metadata_text(metadata, *keys)


def _load_target_frequency(path: Path, target_ids: set[str]) -> dict[str, dict[str, Any]]:
    rows = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if item_id in target_ids:
            rows[item_id] = row
    return rows


def _load_target_quality(path: Path, target_ids: set[str]) -> dict[str, dict[str, Any]]:
    rows = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if item_id in target_ids:
            rows[item_id] = row
    return rows


def _load_item_metadata(path: Path, item_ids: set[str]) -> dict[str, dict[str, Any]]:
    rows = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if item_id in item_ids:
            rows[item_id] = row
            if len(rows) == len(item_ids):
                break
    return rows


def _recent_unique_items(raw_items: Any, max_items: int) -> list[str]:
    if not isinstance(raw_items, list):
        return []
    rows = []
    seen = set()
    for item in reversed(raw_items[-max_items:]):
        item_id = str(item)
        if item_id and item_id not in seen:
            seen.add(item_id)
            rows.append(item_id)
    rows.reverse()
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _assert_manifest_has_no_forbidden_fields(value: Any) -> None:
    hits = list(_forbidden_manifest_field_hits(value, "manifest"))
    if hits:
        raise ValueError(f"Forbidden manifest field detected: {hits[:5]}")


def _forbidden_manifest_field_hits(value: Any, context: str):
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if key_text in FORBIDDEN_MANIFEST_FIELDS:
                yield f"{context}.{key_text}"
            yield from _forbidden_manifest_field_hits(nested, f"{context}.{key_text}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _forbidden_manifest_field_hits(nested, f"{context}[{index}]")


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


def main() -> None:
    args = parse_args()
    manifest = build_pool500_two_tower_method_dataset(
        clean_manifest_path=Path(args.clean_manifest),
        governance_manifest_path=Path(args.governance_manifest),
        output_dir=Path(args.output_dir),
        scale_tier=args.scale_tier,
        limit_users=args.limit_users,
        limit_interactions=args.limit_interactions,
        max_samples=args.max_samples,
        negative_ratio=args.negative_ratio,
        max_items_per_user=args.max_items_per_user,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "method_dataset_manifest": manifest["outputs"]["method_dataset_manifest"],
                "train_sample_count": manifest["stats"]["train_sample_count"],
                "negative_universe_item_count": manifest["stats"]["negative_universe_item_count"],
                "training_item_universe_item_count": manifest["stats"]["training_item_universe_item_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
