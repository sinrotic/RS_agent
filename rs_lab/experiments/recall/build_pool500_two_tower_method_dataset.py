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
RECENT_WINDOW_SAMPLE_SCHEMA_VERSION = "recent_window_two_tower_train_sample_v1"
RECENT_WINDOW_BUILDER_VERSION = "recent_window_two_tower_method_dataset_builder_v1"
RECENT_WINDOW_TARGET_ITEM_SOURCE = "train_positive"
TARGET_ITEM_SOURCE_ENUM = ("heldout_interaction", "train_positive", "candidate_pool", "manual_debug", "unknown")
LEGACY_TARGET_ITEM_SOURCE_MIGRATIONS = {
    "train_only_user_sequence": "train_positive",
    "recent_window_train_only_user_sequence_positive_event": "train_positive",
}
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m" / "manifest.json"
DEFAULT_GOVERNANCE_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_recent_2y_1m_3m" / "train_only_governance" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_method_datasets" / "recent_2y" / "two_tower" / "smoke"
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
    "two_tower_dssm_item_vocab_manifest": "two_tower_dssm_item_vocab_manifest.json",
    "method_dataset_manifest": "method_dataset_manifest.json",
    "leakage_audit": "leakage_audit.json",
}
SCALE_TIERS = {
    "smoke": {"limit_users": 500, "max_samples": 20_000, "negative_ratio": 3, "max_items_per_user": 30},
    "formal": {"limit_users": 0, "max_samples": 0, "negative_ratio": 5, "max_items_per_user": 80},
    "sparse_aware_smoke": {"limit_users": 500, "max_samples": 20_000, "negative_ratio": 3, "max_items_per_user": 80},
    "sparse_aware_formal": {"limit_users": 0, "max_samples": 0, "negative_ratio": 5, "max_items_per_user": 120},
}
ELIGIBLE_USER_BUCKETS = {"sequence_sufficient", "collaborative_rich", "medium_behavior"}
ELIGIBLE_ITEM_BUCKETS = {"embedding_ready"}
SPARSE_AWARE_TARGET_ITEM_BUCKETS = {"embedding_ready", "cf_ready", "mid_frequency"}
SPARSE_AWARE_NEGATIVE_ITEM_BUCKETS = {"embedding_ready", "cf_ready", "mid_frequency"}
NEGATIVE_UNIVERSE_POLICY = "p1_item_quality_profile_v2_embedding_ready_joined_with_item_frequency_train"
SPARSE_AWARE_NEGATIVE_UNIVERSE_POLICY = "sparse_aware_v1_embedding_cf_mid_frequency_train_only"
TARGET_ITEM_POLICY = "train_only_sequence_positive_targets_not_constrained_to_negative_universe"
SPARSE_AWARE_TARGET_ITEM_POLICY = "sparse_aware_v1_post_item_pruned_train_positive_targets"
TRAINING_ITEM_UNIVERSE_POLICY = "negative_universe_plus_sampled_train_sequence_targets"
PER_USER_NEGATIVE_UNIVERSE_POLICY = "global_negative_universe_minus_user_known_history_and_current_target"
PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY = "deterministic_diversified_rotated_negatives_after_per_user_exclusions"
HARD_NEGATIVE_POLICY_NONE = "none"
HARD_NEGATIVE_POLICY_SAME_CATEGORY_POPULAR = "same_category_popular_train_only"
HARD_NEGATIVE_POLICY_SAME_CATEGORY_MIXED = "same_category_popular_tail_global_train_only"
HARD_NEGATIVE_POLICIES = (HARD_NEGATIVE_POLICY_NONE, HARD_NEGATIVE_POLICY_SAME_CATEGORY_POPULAR, HARD_NEGATIVE_POLICY_SAME_CATEGORY_MIXED)
HARD_NEGATIVE_SOURCE_SAME_CATEGORY_POPULAR = "canonical_items_metadata_category_joined_with_train_only_popularity_universe"
HARD_NEGATIVE_SOURCE_SAME_CATEGORY_TAIL = "canonical_items_metadata_category_joined_with_train_only_tail_universe"
HARD_NEGATIVE_SOURCE_GLOBAL_ROTATED = "train_only_global_negative_universe_rotated_fill"
EVAL_TARGET_UNIVERSE_POLICY = "phase1_not_built"
ELIGIBLE_TARGET_UNIVERSE_POLICY = "sampled_train_sequence_targets_only"
FORBIDDEN_DATA_USES = ["training", "negative_sampling", "index_build", "official_candidate_generation"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build independent train-only pool500 TwoTower method dataset artifacts.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--governance-manifest", default=str(DEFAULT_GOVERNANCE_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--scale-tier", choices=tuple(SCALE_TIERS), default="smoke")
    parser.add_argument("--limit-users", type=int, default=None)
    parser.add_argument("--limit-interactions", type=int, default=0)
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--negative-ratio", type=int, default=None)
    parser.add_argument("--max-items-per-user", type=int, default=None)
    parser.add_argument("--hard-negative-policy", choices=HARD_NEGATIVE_POLICIES, default=HARD_NEGATIVE_POLICY_NONE)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_two_tower_method_dataset(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    governance_manifest_path: Path = DEFAULT_GOVERNANCE_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    scale_tier: str = "smoke",
    limit_users: int | None = None,
    limit_interactions: int = 0,
    max_samples: int | None = None,
    negative_ratio: int | None = None,
    max_items_per_user: int | None = None,
    hard_negative_policy: str = HARD_NEGATIVE_POLICY_NONE,
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
    if hard_negative_policy not in HARD_NEGATIVE_POLICIES:
        raise ValueError(f"Unsupported hard_negative_policy: {hard_negative_policy}")

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
    canonical_train_interactions_path = _resolve_canonical_train_interactions_path(clean_manifest_path, clean_manifest)
    canonical_items_path = _resolve_canonical_items_path(clean_manifest_path, clean_manifest)
    artifact_paths = _resolve_governance_artifacts(governance_manifest_path, governance_manifest)
    history_source_hash = _file_sha256(train_sequences_path)
    target_source_hash = history_source_hash
    negative_universe_source_path = artifact_paths["item_frequency_train"]
    negative_universe_source_hash = _file_sha256(negative_universe_source_path)
    read_files = [clean_manifest_path, governance_manifest_path, train_sequences_path, canonical_items_path, *artifact_paths.values()]
    for path in read_files:
        _precheck_train_scope_path(path)

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)

    sparse_aware = _is_sparse_aware_tier(scale_tier)
    user_profiles = _load_user_profiles(artifact_paths["user_quality_profile"])
    negative_universe, trainable_target_items, universe_audit, item_sparse_lookup = _load_item_policy_universes(
        item_quality_profile_path=artifact_paths["item_quality_profile"],
        item_frequency_train_path=artifact_paths["item_frequency_train"],
        sparse_aware=sparse_aware,
    )
    negative_universe_policy = SPARSE_AWARE_NEGATIVE_UNIVERSE_POLICY if sparse_aware else NEGATIVE_UNIVERSE_POLICY
    target_item_policy = SPARSE_AWARE_TARGET_ITEM_POLICY if sparse_aware else TARGET_ITEM_POLICY
    eligible_item_buckets = SPARSE_AWARE_NEGATIVE_ITEM_BUCKETS if sparse_aware else ELIGIBLE_ITEM_BUCKETS
    universe_path = output_dir / OUTPUT_FILES["negative_item_universe"]
    _write_jsonl(universe_path, negative_universe)
    hard_negative_index = _build_hard_negative_index(
        policy=hard_negative_policy,
        canonical_items_path=canonical_items_path,
        negative_universe=negative_universe,
    )

    samples_path = output_dir / OUTPUT_FILES["two_tower_train_samples"]
    sample_stats = _write_train_samples(
        samples_path=samples_path,
        train_sequences_path=train_sequences_path,
        eligible_user_profiles=user_profiles,
        negative_universe=negative_universe,
        trainable_target_items=trainable_target_items if sparse_aware else None,
        item_sparse_lookup=item_sparse_lookup,
        hard_negative_index=hard_negative_index,
        sparse_aware=sparse_aware,
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
    dssm_item_vocab_manifest_path = output_dir / OUTPUT_FILES["two_tower_dssm_item_vocab_manifest"]
    dssm_item_vocab_manifest = _write_two_tower_dssm_item_vocab_manifest(
        path=dssm_item_vocab_manifest_path,
        item_vocab_path=training_universe_path,
        item_count=training_universe_stats["training_item_universe_item_count"],
        clean_manifest_path=clean_manifest_path,
        governance_manifest_path=governance_manifest_path,
        train_sequences_path=train_sequences_path,
        canonical_train_interactions_path=canonical_train_interactions_path,
        canonical_items_path=canonical_items_path,
        artifact_paths=artifact_paths,
        scale_tier=scale_tier,
        negative_universe_policy=negative_universe_policy,
        target_item_policy=target_item_policy,
    )
    universe_definitions = _phase1_universe_definitions(negative_universe_policy=negative_universe_policy, target_item_policy=target_item_policy)
    data_usage_boundary = _phase1_data_usage_boundary()
    target_coverage_stats = _target_coverage_stats(
        sample_target_item_counts=sample_target_item_counts,
        negative_universe=negative_universe,
        training_universe_stats=training_universe_stats,
    )

    output_paths = {name: str(output_dir / file_name) for name, file_name in OUTPUT_FILES.items()}
    resource_scale_policy = _resource_scale_policy(
        scale_tier,
        limits,
        negative_universe_policy=negative_universe_policy,
        target_item_policy=target_item_policy,
        eligible_item_buckets=eligible_item_buckets,
        hard_negative_policy=hard_negative_policy,
    )
    leakage_audit = {
        "schema_version": SCHEMA_VERSION,
        "recent_window_sample_schema_version": RECENT_WINDOW_SAMPLE_SCHEMA_VERSION,
        "builder_version": RECENT_WINDOW_BUILDER_VERSION,
        "status": "PASS",
        "train_only": True,
        "valid_used": False,
        "test_used": False,
        "holdout_used": False,
        "lopo_used": False,
        "oracle_used": False,
        "embedding_or_index_used": False,
        "read_files": [str(path) for path in read_files],
        "history_source_path": str(train_sequences_path),
        "history_source_hash": history_source_hash,
        "target_source_path": str(train_sequences_path),
        "target_source_hash": target_source_hash,
        "window_policy": _recent_window_policy(clean_manifest),
        "negative_universe_sources": [str(artifact_paths["item_quality_profile"]), str(artifact_paths["item_frequency_train"])],
        "negative_universe_source_path": str(negative_universe_source_path),
        "negative_universe_source_hash": negative_universe_source_hash,
        "negative_sampling_policy": {
            "global_universe_policy": negative_universe_policy,
            "per_user_policy": PER_USER_NEGATIVE_UNIVERSE_POLICY,
            "per_example_policy": PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY,
            "hard_negative_policy": hard_negative_policy,
            "hard_negative_enabled": hard_negative_policy != HARD_NEGATIVE_POLICY_NONE,
            "hard_negative_sources": _hard_negative_sources(hard_negative_policy),
            "forbidden_sources": ["valid", "test", "holdout", "oracle", "eval_label"],
            "source_scope": "train_only_item_universe",
            "excludes_target_item": True,
            "excludes_user_known_history": True,
            "excludes_items_after_target_window_boundary": True,
        },
        "target_item_source_enum": list(TARGET_ITEM_SOURCE_ENUM),
        "target_item_source_p2_forbidden": ["manual_debug", "unknown"],
        "target_item_source_legacy_migrations": LEGACY_TARGET_ITEM_SOURCE_MIGRATIONS,
        "forbidden_output_names": sorted(FORBIDDEN_OUTPUT_NAMES),
        "forbidden_manifest_fields": sorted(FORBIDDEN_MANIFEST_FIELDS),
    }
    write_json(output_dir / OUTPUT_FILES["leakage_audit"], leakage_audit)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "recent_window_sample_schema_version": RECENT_WINDOW_SAMPLE_SCHEMA_VERSION,
        "builder_version": RECENT_WINDOW_BUILDER_VERSION,
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
        "history_source_path": str(train_sequences_path),
        "history_source_hash": history_source_hash,
        "target_source_path": str(train_sequences_path),
        "target_source_hash": target_source_hash,
        "target_item_source_enum": list(TARGET_ITEM_SOURCE_ENUM),
        "target_item_source_p2_forbidden": ["manual_debug", "unknown"],
        "target_item_source_legacy_migrations": LEGACY_TARGET_ITEM_SOURCE_MIGRATIONS,
        "window_policy": _recent_window_policy(clean_manifest),
        "leakage_audit_path": str(output_dir / OUTPUT_FILES["leakage_audit"]),
        "train_user_sequences_path": str(train_sequences_path),
        "canonical_items_path": str(canonical_items_path),
        "input_artifacts": {name: str(path) for name, path in artifact_paths.items()},
        "negative_universe_policy": negative_universe_policy,
        "negative_universe_source_path": str(negative_universe_source_path),
        "negative_universe_source_hash": negative_universe_source_hash,
        "negative_sampling_policy": {
            "global_universe_policy": negative_universe_policy,
            "per_user_policy": PER_USER_NEGATIVE_UNIVERSE_POLICY,
            "per_example_policy": PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY,
            "hard_negative_policy": hard_negative_policy,
            "hard_negative_enabled": hard_negative_policy != HARD_NEGATIVE_POLICY_NONE,
            "hard_negative_sources": _hard_negative_sources(hard_negative_policy),
            "forbidden_sources": ["valid", "test", "holdout", "oracle", "eval_label"],
            "source_scope": "train_only_item_universe",
            "excludes_target_item": True,
            "excludes_user_known_history": True,
            "excludes_items_after_target_window_boundary": True,
        },
        "target_item_policy": target_item_policy,
        "training_item_universe_policy": TRAINING_ITEM_UNIVERSE_POLICY,
        "per_user_negative_universe_policy": PER_USER_NEGATIVE_UNIVERSE_POLICY,
        "per_example_negative_universe_policy": PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY,
        "hard_negative_policy": hard_negative_policy,
        "hard_negative_enabled": hard_negative_policy != HARD_NEGATIVE_POLICY_NONE,
        "hard_negative_sources": _hard_negative_sources(hard_negative_policy),
        "eval_target_universe_policy": EVAL_TARGET_UNIVERSE_POLICY,
        "eligible_target_universe_policy": ELIGIBLE_TARGET_UNIVERSE_POLICY,
        "eval_target_universe_available": False,
        "retrieval_item_universe_available": False,
        "universe_definitions": universe_definitions,
        "data_usage_boundary": data_usage_boundary,
        "eligible_user_buckets": sorted(ELIGIBLE_USER_BUCKETS),
        "eligible_item_quality_bucket_v2": sorted(eligible_item_buckets),
        "limits": limits,
        "resource_scale_policy": resource_scale_policy,
        "stats": {**universe_audit, **sample_stats, **training_universe_stats, **target_coverage_stats},
        "outputs": output_paths,
        "dssm_item_vocab_manifest": dssm_item_vocab_manifest,
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


def _resource_scale_policy(
    scale_tier: str,
    limits: dict[str, int],
    *,
    negative_universe_policy: str = NEGATIVE_UNIVERSE_POLICY,
    target_item_policy: str = TARGET_ITEM_POLICY,
    eligible_item_buckets: set[str] = ELIGIBLE_ITEM_BUCKETS,
    hard_negative_policy: str = HARD_NEGATIVE_POLICY_NONE,
) -> dict[str, Any]:
    return {
        "input_scope": "governance_train_only_recent_2y",
        "scale_tier": scale_tier,
        "default_tier": "formal",
        "formal_scale_policy": {
            "scale_mode": "agent_managed",
            "quantity_caps": "unlimited",
            "data_window": "recent_2y",
            "limit_users": 0,
            "max_samples": 0,
        },
        "scale_tiers": SCALE_TIERS,
        "selection_policy_version": "p2_method_dataset_policy_recent_2y_v1",
        "selection_strategy": {
            "policy_name": "two_tower_sequence_v1",
            "sampling_unit": "user_sequence",
            "preserve_order": True,
            "sequence_contract": "future_history_items_to_target_item",
            "exclude_non_train_future_events": True,
        },
        "sample_strategy": "sequence_to_target_transition_contract",
        "target_item_policy": target_item_policy,
        "training_item_universe_policy": TRAINING_ITEM_UNIVERSE_POLICY,
        "eligible_user_buckets": sorted(ELIGIBLE_USER_BUCKETS),
        "eligible_item_quality_bucket_v2": sorted(eligible_item_buckets),
        "negative_universe_policy": negative_universe_policy,
        "per_user_negative_universe_policy": PER_USER_NEGATIVE_UNIVERSE_POLICY,
        "per_example_negative_universe_policy": PER_EXAMPLE_NEGATIVE_UNIVERSE_POLICY,
        "hard_negative_policy": hard_negative_policy,
        "hard_negative_enabled": hard_negative_policy != HARD_NEGATIVE_POLICY_NONE,
        "hard_negative_sources": _hard_negative_sources(hard_negative_policy),
        "eval_target_universe_policy": EVAL_TARGET_UNIVERSE_POLICY,
        "eligible_target_universe_policy": ELIGIBLE_TARGET_UNIVERSE_POLICY,
        "limits": dict(limits),
        "p2_contract_scope": "method_dataset_only",
    }


def _phase1_universe_definitions(*, negative_universe_policy: str = NEGATIVE_UNIVERSE_POLICY, target_item_policy: str = TARGET_ITEM_POLICY) -> dict[str, Any]:
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
            "policy": negative_universe_policy,
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
            "target_item_policy": target_item_policy,
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
    if limit_users < 0:
        raise ValueError("limit_users must be non-negative; use 0 for unlimited")
    if limit_interactions < 0:
        raise ValueError("limit_interactions must be non-negative")
    if max_samples < 0:
        raise ValueError("max_samples must be non-negative; use 0 for unlimited")
    if negative_ratio <= 0:
        raise ValueError("negative_ratio must be positive")
    if max_items_per_user <= 0:
        raise ValueError("max_items_per_user must be positive")
    if min_free_bytes < 0:
        raise ValueError("min_free_bytes must be non-negative")


def _resolve_repo_path(manifest_path: Path, raw_path: Any) -> Path:
    raw_text = str(raw_path)
    normalized = raw_text.replace("\\", "/")
    for marker in ("data/", "outputs/", "configs/"):
        if marker in normalized:
            repo_relative = Path(normalized[normalized.index(marker) :])
            root_candidate = (ROOT / repo_relative).resolve()
            if root_candidate.exists():
                return root_candidate
    path = Path(raw_text)
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


def _resolve_canonical_train_interactions_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    split_paths = manifest.get("split_paths") if isinstance(manifest.get("split_paths"), dict) else {}
    raw_path = split_paths.get("train") or manifest.get("canonical_interactions_train_path")
    if not raw_path:
        candidate = manifest_path.parent / "canonical_interactions.train.jsonl"
        if candidate.is_file():
            return candidate.resolve()
        raise ValueError("clean manifest must provide split_paths.train or canonical_interactions_train_path")
    path = _resolve_repo_path(manifest_path, raw_path)
    if path.name != "canonical_interactions.train.jsonl":
        raise ValueError(f"TwoTower dataset builder must reference canonical_interactions.train.jsonl, got {path.name}")
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


def _is_sparse_aware_tier(scale_tier: str) -> bool:
    return scale_tier.startswith("sparse_aware_")


def _load_negative_universe(*, item_quality_profile_path: Path, item_frequency_train_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows, _, stats, _ = _load_item_policy_universes(
        item_quality_profile_path=item_quality_profile_path,
        item_frequency_train_path=item_frequency_train_path,
        sparse_aware=False,
    )
    return rows, stats


def _load_item_policy_universes(
    *,
    item_quality_profile_path: Path,
    item_frequency_train_path: Path,
    sparse_aware: bool,
) -> tuple[list[dict[str, Any]], set[str], dict[str, Any], dict[str, dict[str, Any]]]:
    frequency_by_item = {}
    for row in iter_jsonl(item_frequency_train_path):
        item_id = str(row.get("parent_asin") or "")
        if item_id:
            frequency_by_item[item_id] = row
    if not frequency_by_item:
        raise ValueError("P1 item_frequency_train is empty")

    negative_rows = []
    trainable_target_items: set[str] = set()
    item_lookup: dict[str, dict[str, Any]] = {}
    bucket_counts: Counter[str] = Counter()
    negative_bucket_counts: Counter[str] = Counter()
    target_bucket_counts: Counter[str] = Counter()
    frequency_bucket_counts: Counter[str] = Counter()
    user_count_bucket_counts: Counter[str] = Counter()
    pop_rank_bucket_counts: Counter[str] = Counter()
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
        if frequency is None:
            continue
        frequency_value = int(frequency.get("frequency", row.get("positive_event_count", 0)) or 0)
        user_count = int(frequency.get("user_count", row.get("unique_positive_user_count", 0)) or 0)
        global_pop_rank = int(row.get("global_pop_rank", len(item_lookup) + 1) or len(item_lookup) + 1)
        policy_row = {
            "parent_asin": item_id,
            "frequency": frequency_value,
            "user_count": user_count,
            "quality_bucket_v2": bucket,
            "global_pop_rank": global_pop_rank,
            "source_layer": "p1_governance_train_only",
        }
        item_lookup[item_id] = policy_row
        if _is_trainable_target_item(bucket, frequency_value, user_count, sparse_aware=sparse_aware):
            trainable_target_items.add(item_id)
            target_bucket_counts[bucket] += 1
        if _is_negative_universe_item(bucket, sparse_aware=sparse_aware):
            negative_rows.append(policy_row)
            negative_bucket_counts[bucket] += 1
            frequency_bucket_counts[_count_bucket(frequency_value)] += 1
            user_count_bucket_counts[_count_bucket(user_count)] += 1
            pop_rank_bucket_counts[_popularity_bucket(frequency_value, global_pop_rank)] += 1
    if missing_v2:
        raise ValueError("P1 item_quality_profile missing required quality_bucket_v2 field")
    if not negative_rows:
        raise ValueError("P1 item_quality_profile has no eligible negative universe items")
    negative_rows.sort(key=lambda row: (-int(row["frequency"]), int(row["global_pop_rank"]), str(row["parent_asin"])))
    return negative_rows, trainable_target_items, {
        "negative_universe_item_count": len(negative_rows),
        "item_quality_bucket_v2_counts": dict(sorted(bucket_counts.items())),
        "governance_item_quality_bucket_v2_counts": dict(sorted(bucket_counts.items())),
        "negative_universe_quality_bucket_v2_counts": dict(sorted(negative_bucket_counts.items())),
        "negative_universe_frequency_bucket_counts": dict(sorted(frequency_bucket_counts.items())),
        "negative_universe_user_count_bucket_counts": dict(sorted(user_count_bucket_counts.items())),
        "negative_universe_pop_rank_bucket_counts": dict(sorted(pop_rank_bucket_counts.items())),
        "trainable_positive_target_universe_item_count": len(trainable_target_items),
        "trainable_positive_target_universe_quality_bucket_v2_counts": dict(sorted(target_bucket_counts.items())),
        "negative_universe_source_files": [str(item_quality_profile_path), str(item_frequency_train_path)],
    }, item_lookup


def _is_trainable_target_item(bucket: str, frequency: int, user_count: int, *, sparse_aware: bool) -> bool:
    if not sparse_aware:
        return bucket in ELIGIBLE_ITEM_BUCKETS
    if bucket in SPARSE_AWARE_TARGET_ITEM_BUCKETS:
        return frequency >= 2 and user_count >= 2
    return bucket == "low_frequency" and frequency >= 2 and user_count >= 2


def _is_negative_universe_item(bucket: str, *, sparse_aware: bool) -> bool:
    if not sparse_aware:
        return bucket in ELIGIBLE_ITEM_BUCKETS
    return bucket in SPARSE_AWARE_NEGATIVE_ITEM_BUCKETS


def _hard_negative_sources(policy: str) -> list[str]:
    if policy == HARD_NEGATIVE_POLICY_NONE:
        return []
    if policy == HARD_NEGATIVE_POLICY_SAME_CATEGORY_POPULAR:
        return [HARD_NEGATIVE_SOURCE_SAME_CATEGORY_POPULAR]
    if policy == HARD_NEGATIVE_POLICY_SAME_CATEGORY_MIXED:
        return [HARD_NEGATIVE_SOURCE_SAME_CATEGORY_POPULAR, HARD_NEGATIVE_SOURCE_SAME_CATEGORY_TAIL, HARD_NEGATIVE_SOURCE_GLOBAL_ROTATED]
    raise ValueError(f"Unsupported hard negative policy: {policy}")


def _build_hard_negative_index(*, policy: str, canonical_items_path: Path, negative_universe: list[dict[str, Any]]) -> dict[str, Any]:
    if policy == HARD_NEGATIVE_POLICY_NONE:
        return {"policy": HARD_NEGATIVE_POLICY_NONE, "source": "", "category_count": 0, "item_count": 0}
    if policy not in {HARD_NEGATIVE_POLICY_SAME_CATEGORY_POPULAR, HARD_NEGATIVE_POLICY_SAME_CATEGORY_MIXED}:
        raise ValueError(f"Unsupported hard negative policy: {policy}")

    negative_rank = {str(row["parent_asin"]): rank for rank, row in enumerate(negative_universe)}
    negative_items = set(negative_rank)
    item_categories: dict[str, list[str]] = {}
    candidates_by_category: dict[str, list[str]] = {}
    for row in iter_jsonl(canonical_items_path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not item_id:
            continue
        categories = _item_category_tokens(row)
        if not categories:
            continue
        item_categories[item_id] = categories
        if item_id not in negative_items:
            continue
        for category in categories:
            candidates_by_category.setdefault(category, []).append(item_id)

    popular_candidates_by_category: dict[str, list[str]] = {}
    tail_candidates_by_category: dict[str, list[str]] = {}
    for category, candidates in candidates_by_category.items():
        unique_candidates = list(dict.fromkeys(candidates))
        popular_candidates_by_category[category] = sorted(unique_candidates, key=lambda item_id: (negative_rank[item_id], item_id))
        tail_candidates_by_category[category] = sorted(unique_candidates, key=lambda item_id: (-negative_rank[item_id], item_id))
    return {
        "policy": policy,
        "source": "+".join(_hard_negative_sources(policy)),
        "sources": _hard_negative_sources(policy),
        "item_categories": item_categories,
        "candidates_by_category": popular_candidates_by_category,
        "popular_candidates_by_category": popular_candidates_by_category,
        "tail_candidates_by_category": tail_candidates_by_category,
        "category_count": len(popular_candidates_by_category),
        "item_count": len({item_id for candidates in popular_candidates_by_category.values() for item_id in candidates}),
    }


def _item_category_tokens(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("main_category", "category", "categories_flat", "categories_path", "source_categories"):
        raw = row.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item)
        else:
            text = str(raw or "")
            if not text:
                continue
            values.extend(part.strip() for part in text.replace(">", "|").replace("/", "|").split("|") if part.strip())
    return list(dict.fromkeys(value.lower() for value in values if value))


def _same_category_hard_negatives(
    *,
    target_item: str,
    item_categories: dict[str, list[str]],
    candidates_by_category: dict[str, list[str]],
    excluded_items: set[str],
    sample_index: int,
    target_index: int,
    negative_ratio: int,
) -> list[str]:
    categories = item_categories.get(target_item, [])
    if not categories:
        return []
    candidates = _category_candidates(categories, candidates_by_category, excluded_items)
    return _rotate_candidates(candidates, sample_index=sample_index, target_index=target_index, limit=negative_ratio)


def _mixed_hard_negatives(
    *,
    target_item: str,
    item_categories: dict[str, list[str]],
    popular_candidates_by_category: dict[str, list[str]],
    tail_candidates_by_category: dict[str, list[str]],
    negative_items: list[str],
    excluded_items: set[str],
    user_id: str,
    sample_index: int,
    target_index: int,
    negative_ratio: int,
) -> tuple[list[str], dict[str, int]]:
    popular_limit = max(1, negative_ratio // 2)
    tail_limit = max(1, negative_ratio // 4) if negative_ratio >= 3 else 0
    global_limit = max(0, negative_ratio - popular_limit - tail_limit)
    categories = item_categories.get(target_item, [])
    negatives: list[str] = []
    counts = {"same_category_popular": 0, "same_category_tail": 0, "global_rotated": 0}

    popular_candidates = _category_candidates(categories, popular_candidates_by_category, excluded_items)
    popular = _rotate_candidates(popular_candidates, sample_index=sample_index, target_index=target_index, limit=popular_limit)
    negatives.extend(popular)
    counts["same_category_popular"] = len(popular)

    remaining_exclusions = excluded_items | set(negatives)
    tail_candidates = _category_candidates(categories, tail_candidates_by_category, remaining_exclusions)
    tail = _rotate_candidates(tail_candidates, sample_index=sample_index + len(popular), target_index=target_index, limit=tail_limit)
    negatives.extend(tail)
    counts["same_category_tail"] = len(tail)

    remaining = negative_ratio - len(negatives)
    if remaining > 0:
        global_negatives = _deterministic_rotated_negatives(
            negative_items,
            excluded_items=excluded_items | set(negatives),
            user_id=user_id,
            target_item=target_item,
            target_index=target_index,
            sample_index=sample_index,
            negative_ratio=remaining,
        )
        negatives.extend(global_negatives)
        counts["global_rotated"] = len(global_negatives)
    elif global_limit == 0:
        counts["global_rotated"] = 0

    return negatives[:negative_ratio], counts


def _category_candidates(categories: list[str], candidates_by_category: dict[str, list[str]], excluded_items: set[str]) -> list[str]:
    candidates: list[str] = []
    for category in categories:
        candidates.extend(candidates_by_category.get(category, []))
    return [item_id for item_id in dict.fromkeys(candidates) if item_id not in excluded_items]


def _rotate_candidates(candidates: list[str], *, sample_index: int, target_index: int, limit: int) -> list[str]:
    if not candidates or limit <= 0:
        return []
    offset = (sample_index + target_index) % len(candidates)
    rotated = [*candidates[offset:], *candidates[:offset]]
    return rotated[:limit]


def _write_train_samples(
    *,
    samples_path: Path,
    train_sequences_path: Path,
    eligible_user_profiles: dict[str, dict[str, Any]],
    negative_universe: list[dict[str, Any]],
    trainable_target_items: set[str] | None,
    item_sparse_lookup: dict[str, dict[str, Any]],
    hard_negative_index: dict[str, Any],
    sparse_aware: bool,
    limit_users: int,
    limit_interactions: int,
    max_samples: int,
    negative_ratio: int,
    max_items_per_user: int,
) -> dict[str, Any]:
    negative_items = [str(row["parent_asin"]) for row in negative_universe]
    negative_item_set = set(negative_items)
    target_item_set = trainable_target_items or set()
    hard_negative_policy = str(hard_negative_index.get("policy", HARD_NEGATIVE_POLICY_NONE))
    hard_negative_enabled = hard_negative_policy != HARD_NEGATIVE_POLICY_NONE
    item_categories = hard_negative_index.get("item_categories", {}) if hard_negative_enabled else {}
    hard_negative_candidates_by_category = hard_negative_index.get("candidates_by_category", {}) if hard_negative_enabled else {}
    hard_negative_popular_candidates_by_category = hard_negative_index.get("popular_candidates_by_category", {}) if hard_negative_enabled else {}
    hard_negative_tail_candidates_by_category = hard_negative_index.get("tail_candidates_by_category", {}) if hard_negative_enabled else {}
    rows_scanned = 0
    eligible_users_seen = 0
    interactions_seen = 0
    sample_count = 0
    skipped_target_not_in_universe = 0
    targets_outside_negative_universe = 0
    negatives_per_sample: list[int] = []
    target_item_counts: Counter[str] = Counter()
    used_negative_item_counts: Counter[str] = Counter()
    eligible_user_bucket_counts: Counter[str] = Counter()
    sample_emitting_user_bucket_counts: Counter[str] = Counter()
    train_sample_bucket_counts: Counter[str] = Counter()
    sample_emitting_user_ids: set[str] = set()
    pre_positive_count_buckets: Counter[str] = Counter()
    post_positive_count_buckets: Counter[str] = Counter()
    post_transition_count_buckets: Counter[str] = Counter()
    retention_ratio_buckets: Counter[str] = Counter()
    user_quality_transition_counts: Counter[str] = Counter()
    retained_user_count = 0
    user_drop_reason_counts: Counter[str] = Counter()
    sample_drop_reason_counts: Counter[str] = Counter()
    target_outside_quality_bucket_counts: Counter[str] = Counter()
    target_outside_frequency_bucket_counts: Counter[str] = Counter()
    negative_item_count_under_requested_count = 0
    hard_negative_item_counts: Counter[str] = Counter()
    hard_negative_component_counts: Counter[str] = Counter()
    hard_negative_match_count = 0
    hard_negative_fallback_count = 0

    def finish(final_interactions_seen: int) -> dict[str, Any]:
        return _sample_stats(
            rows_scanned,
            eligible_users_seen,
            final_interactions_seen,
            sample_count,
            negatives_per_sample,
            eligible_user_bucket_counts,
            skipped_target_not_in_universe,
            targets_outside_negative_universe,
            target_item_counts,
            used_negative_item_counts,
            negative_item_count_under_requested_count,
            negative_ratio,
            {
                "sparse_aware_dataset": sparse_aware,
                "pre_item_filter_user_count": eligible_users_seen,
                "post_item_filter_user_count": retained_user_count,
                "post_item_filter_dropped_user_count": sum(user_drop_reason_counts.values()),
                "post_item_filter_drop_reason_counts": dict(sorted(user_drop_reason_counts.items())),
                "sample_drop_reason_counts": dict(sorted(sample_drop_reason_counts.items())),
                "pre_item_filter_positive_count_buckets": dict(sorted(pre_positive_count_buckets.items())),
                "post_item_filter_positive_count_buckets": dict(sorted(post_positive_count_buckets.items())),
                "post_item_filter_transition_count_buckets": dict(sorted(post_transition_count_buckets.items())),
                "post_item_filter_retention_ratio_buckets": dict(sorted(retention_ratio_buckets.items())),
                "user_quality_post_filter_transition_counts": dict(sorted(user_quality_transition_counts.items())),
                "eligible_user_quality_bucket_counts": dict(sorted(eligible_user_bucket_counts.items())),
                "sample_emitting_user_count": len(sample_emitting_user_ids),
                "sample_emitting_user_quality_bucket_counts": dict(sorted(sample_emitting_user_bucket_counts.items())),
                "train_sample_quality_bucket_counts": dict(sorted(train_sample_bucket_counts.items())),
                "target_outside_negative_universe_quality_bucket_counts": dict(sorted(target_outside_quality_bucket_counts.items())),
                "target_outside_negative_universe_frequency_bucket_counts": dict(sorted(target_outside_frequency_bucket_counts.items())),
                "hard_negative_policy": str(hard_negative_index.get("policy", HARD_NEGATIVE_POLICY_NONE)),
                "hard_negative_enabled": hard_negative_enabled,
                "hard_negative_source": str(hard_negative_index.get("source", "")),
                "hard_negative_category_count": int(hard_negative_index.get("category_count", 0)),
                "hard_negative_item_count": int(hard_negative_index.get("item_count", 0)),
                "hard_negative_sample_match_count": hard_negative_match_count,
                "hard_negative_sample_fallback_count": hard_negative_fallback_count,
                "hard_negative_used_distinct_item_count": len(hard_negative_item_counts),
                "hard_negative_used_item_occurrence_count": sum(hard_negative_item_counts.values()),
                "hard_negative_component_counts": dict(sorted(hard_negative_component_counts.items())),
            },
        )

    with samples_path.open("w", encoding="utf-8") as sink:
        for row in iter_jsonl(train_sequences_path):
            rows_scanned += 1
            user_id = str(row.get("user_id") or "")
            profile = eligible_user_profiles.get(user_id)
            if profile is None:
                continue
            eligible_users_seen += 1
            user_bucket = str(profile["quality_bucket_v2"])
            eligible_user_bucket_counts[user_bucket] += 1
            raw_positives = _recent_unique_item_events(
                row.get("recent_positive_item_sequence"),
                row.get("recent_positive_timestamp_sequence"),
                max_items_per_user,
            )
            positives = [event for event in raw_positives if event["item_id"] in target_item_set] if sparse_aware else raw_positives
            pre_count = len(raw_positives)
            post_count = len(positives)
            post_unique_count = len({event["item_id"] for event in positives})
            post_transition_count = max(0, post_count - 1)
            pre_positive_count_buckets[_count_bucket(pre_count)] += 1
            post_positive_count_buckets[_count_bucket(post_count)] += 1
            post_transition_count_buckets[_count_bucket(post_transition_count)] += 1
            retention_ratio_buckets[_ratio_bucket(post_count / pre_count if pre_count else 0.0)] += 1
            post_bucket = _post_filter_user_bucket(post_count, post_unique_count, post_transition_count)
            user_quality_transition_counts[f"{user_bucket}->{post_bucket}"] += 1
            drop_reason = _post_filter_drop_reason(post_count, post_unique_count, post_transition_count)
            if sparse_aware and drop_reason:
                user_drop_reason_counts[drop_reason] += 1
                if limit_users and eligible_users_seen >= limit_users:
                    break
                continue
            retained_user_count += 1
            known_items = set(_recent_unique_items(row.get("recent_item_sequence"), 0)) | {event["item_id"] for event in raw_positives}
            emitted_for_user = False
            for target_index in range(1, len(positives)):
                target_event = positives[target_index]
                target_item = target_event["item_id"]
                target_time = target_event["timestamp"]
                interactions_seen += 1
                if limit_interactions and interactions_seen > limit_interactions:
                    return finish(interactions_seen - 1)
                if target_item not in negative_item_set:
                    targets_outside_negative_universe += 1
                    target_policy_row = item_sparse_lookup.get(target_item, {})
                    target_outside_quality_bucket_counts[str(target_policy_row.get("quality_bucket_v2") or "missing_p1_quality")] += 1
                    target_outside_frequency_bucket_counts[_count_bucket(int(target_policy_row.get("frequency", 0) or 0))] += 1
                history_events = positives[:target_index]
                history_items = [event["item_id"] for event in history_events]
                history_times = [event["timestamp"] for event in history_events]
                _validate_recent_window_sample_times(history_items, history_times, target_time)
                excluded_items = known_items | set(history_items) | {target_item}
                if hard_negative_enabled:
                    if hard_negative_policy == HARD_NEGATIVE_POLICY_SAME_CATEGORY_MIXED:
                        negatives, component_counts = _mixed_hard_negatives(
                            target_item=target_item,
                            item_categories=item_categories,
                            popular_candidates_by_category=hard_negative_popular_candidates_by_category,
                            tail_candidates_by_category=hard_negative_tail_candidates_by_category,
                            negative_items=negative_items,
                            excluded_items=excluded_items,
                            user_id=user_id,
                            sample_index=sample_count,
                            target_index=target_index,
                            negative_ratio=negative_ratio,
                        )
                        hard_negative_component_counts.update(component_counts)
                    else:
                        negatives = _same_category_hard_negatives(
                            target_item=target_item,
                            item_categories=item_categories,
                            candidates_by_category=hard_negative_candidates_by_category,
                            excluded_items=excluded_items,
                            sample_index=sample_count,
                            target_index=target_index,
                            negative_ratio=negative_ratio,
                        )
                        hard_negative_component_counts.update({"same_category_popular": len(negatives)})
                    if negatives:
                        hard_negative_match_count += 1
                        hard_negative_item_counts.update(negatives)
                    else:
                        hard_negative_fallback_count += 1
                        negatives = _deterministic_rotated_negatives(
                            negative_items,
                            excluded_items=excluded_items,
                            user_id=user_id,
                            target_item=target_item,
                            target_index=target_index,
                            sample_index=sample_count,
                            negative_ratio=negative_ratio,
                        )
                        hard_negative_component_counts.update({"fallback_global_rotated": len(negatives)})
                else:
                    negatives = _deterministic_rotated_negatives(
                        negative_items,
                        excluded_items=excluded_items,
                        user_id=user_id,
                        target_item=target_item,
                        target_index=target_index,
                        sample_index=sample_count,
                        negative_ratio=negative_ratio,
                    )
                if not negatives:
                    if sparse_aware:
                        sample_drop_reason_counts["dropped_no_available_negatives"] += 1
                    continue
                if len(negatives) < negative_ratio:
                    negative_item_count_under_requested_count += 1
                sink.write(
                    json.dumps(
                        {
                            "user_id": user_id,
                            "schema_version": RECENT_WINDOW_SAMPLE_SCHEMA_VERSION,
                            "history_items": history_items,
                            "history_times": history_times,
                            "history_max_time": max(history_times),
                            "target_item": target_item,
                            "target_time": target_time,
                            "positive_item_id": target_item,
                            "negative_item_ids": negatives,
                            "target_item_source": RECENT_WINDOW_TARGET_ITEM_SOURCE,
                            "label": 1,
                            "source": "two_tower_method_dataset",
                            "quality_bucket": profile.get("quality_bucket"),
                            "quality_bucket_v2": user_bucket,
                            "post_item_filter_positive_count": post_count,
                            "post_item_filter_transition_count": post_transition_count,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                sample_count += 1
                emitted_for_user = True
                target_item_counts[target_item] += 1
                used_negative_item_counts.update(negatives)
                negatives_per_sample.append(len(negatives))
                train_sample_bucket_counts[user_bucket] += 1
                if max_samples and sample_count >= max_samples:
                    if emitted_for_user and user_id not in sample_emitting_user_ids:
                        sample_emitting_user_ids.add(user_id)
                        sample_emitting_user_bucket_counts[user_bucket] += 1
                    return finish(interactions_seen)
            if emitted_for_user and user_id not in sample_emitting_user_ids:
                sample_emitting_user_ids.add(user_id)
                sample_emitting_user_bucket_counts[user_bucket] += 1
            if limit_users and eligible_users_seen >= limit_users:
                break
    return finish(interactions_seen)


def _post_filter_user_bucket(post_positive_count: int, post_unique_item_count: int, post_transition_count: int) -> str:
    if post_positive_count <= 0:
        return "zero_post_prune_positive"
    if post_positive_count == 1:
        return "single_post_prune_positive"
    if post_unique_item_count < 2:
        return "unique_lt_min"
    if post_transition_count < 1:
        return "no_target_transition"
    return "sample_eligible"


def _post_filter_drop_reason(post_positive_count: int, post_unique_item_count: int, post_transition_count: int) -> str | None:
    if post_positive_count <= 0:
        return "dropped_zero_post_prune_positive"
    if post_positive_count == 1:
        return "dropped_single_post_prune_positive"
    if post_unique_item_count < 2:
        return "dropped_unique_lt_min"
    if post_transition_count < 1:
        return "dropped_no_target_transition"
    return None


def _ratio_bucket(value: float) -> str:
    if value <= 0:
        return "zero"
    if value < 0.25:
        return "000_024pct"
    if value < 0.5:
        return "025_049pct"
    if value < 0.75:
        return "050_074pct"
    if value < 1.0:
        return "075_099pct"
    return "100pct"


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
    extra_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    used_negative_occurrences = sum(used_negative_item_counts.values())
    top10_occurrences = sum(count for _, count in used_negative_item_counts.most_common(10))
    stats = {
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
    if extra_stats:
        stats.update(extra_stats)
    return stats


def _deterministic_rotated_negatives(
    negative_items: list[str],
    *,
    excluded_items: set[str],
    user_id: str,
    target_item: str,
    target_index: int,
    sample_index: int,
    negative_ratio: int,
) -> list[str]:
    if not negative_items:
        return []
    offset = (sample_index + target_index) % len(negative_items)
    negatives = []
    for index in range(len(negative_items)):
        item_id = negative_items[(offset + index) % len(negative_items)]
        if item_id in excluded_items:
            continue
        negatives.append(item_id)
        if len(negatives) >= negative_ratio:
            break
    return negatives


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
    role_counts: Counter[str] = Counter()
    quality_role_counts: Counter[str] = Counter()
    side_feature_counts: dict[str, Counter[str]] = {
        "item_quality_token": Counter(),
        "item_pop_bucket_token": Counter(),
        "item_user_count_bucket_token": Counter(),
    }
    with path.open("w", encoding="utf-8") as sink:
        for item_id, row in sorted(negative_by_item.items(), key=lambda item: (-int(item[1].get("frequency", 0)), int(item[1].get("global_pop_rank", 0)), item[0])):
            roles = ["negative_candidate"]
            if item_id in target_ids:
                roles.append("positive_target")
            universe_row = _training_universe_row(item_id, row, roles, sample_target_item_counts.get(item_id, 0), metadata_by_item.get(item_id, {}))
            if "positive_target" in roles and _positive_target_metadata_incomplete(universe_row):
                positive_target_metadata_incomplete += 1
            _update_training_universe_role_counts(role_counts, quality_role_counts, universe_row)
            _update_side_feature_counts(side_feature_counts, universe_row)
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
            _update_training_universe_role_counts(role_counts, quality_role_counts, universe_row)
            _update_side_feature_counts(side_feature_counts, universe_row)
            sink.write(json.dumps(universe_row, ensure_ascii=False) + "\n")
            written.add(item_id)
    return {
        "training_item_universe_item_count": len(written),
        "training_item_universe_policy": TRAINING_ITEM_UNIVERSE_POLICY,
        "training_item_universe_negative_candidate_count": len(negative_by_item),
        "training_item_universe_positive_target_count": len(target_ids),
        "training_item_universe_role_counts": dict(sorted(role_counts.items())),
        "training_item_universe_quality_role_counts": dict(sorted(quality_role_counts.items())),
        "training_item_universe_metadata_item_count": len(metadata_by_item),
        "training_item_universe_target_items_missing_p1_quality": missing_quality,
        "training_item_universe_target_items_missing_frequency": missing_frequency,
        "training_item_universe_positive_target_metadata_incomplete_count": positive_target_metadata_incomplete,
        "training_item_universe_side_feature_fields": list(side_feature_counts),
        "training_item_universe_side_feature_coverage": {
            field: sum(counter.values()) for field, counter in side_feature_counts.items()
        },
        "training_item_universe_side_feature_bucket_counts": {
            field: dict(sorted(counter.items())) for field, counter in side_feature_counts.items()
        },
    }


def _training_universe_row(item_id: str, row: dict[str, Any], roles: list[str], sample_target_count: int, metadata: dict[str, Any]) -> dict[str, Any]:
    frequency = int(row.get("frequency", 0) or 0)
    user_count = int(row.get("user_count", 0) or 0)
    quality_bucket = str(row.get("quality_bucket_v2") or "unknown")
    global_pop_rank = int(row.get("global_pop_rank", 0) or 0)
    return {
        "parent_asin": item_id,
        "item_id": item_id,
        "frequency": frequency,
        "user_count": user_count,
        "quality_bucket_v2": quality_bucket,
        "global_pop_rank": global_pop_rank,
        "item_quality_token": f"item_quality:{quality_bucket}",
        "item_pop_bucket_token": f"item_pop:{_popularity_bucket(frequency, global_pop_rank)}",
        "item_user_count_bucket_token": f"item_user_count:{_count_bucket(user_count)}",
        "item_roles": roles,
        "sample_target_count": int(sample_target_count),
        "title_clean": _metadata_text(metadata, "title_clean", "title", "description_text", "description", "features_text", "features", "categories_path", "main_category", "category"),
        "main_category": _metadata_text(metadata, "main_category", "category"),
        "category": _metadata_text(metadata, "category", "main_category"),
        "description_text": _metadata_text(metadata, "description_text", "description"),
        "features_text": _metadata_list_text(metadata, "features_text", "features"),
        "item_text": _metadata_item_text(metadata),
        "categories_flat": _metadata_list_text(metadata, "categories_flat", "categories"),
        "source_layer": str(row.get("source_layer") or "p1_governance_train_only"),
    }


def _write_two_tower_dssm_item_vocab_manifest(
    *,
    path: Path,
    item_vocab_path: Path,
    item_count: int,
    clean_manifest_path: Path,
    governance_manifest_path: Path,
    train_sequences_path: Path,
    canonical_train_interactions_path: Path,
    canonical_items_path: Path,
    artifact_paths: dict[str, Path],
    scale_tier: str,
    negative_universe_policy: str,
    target_item_policy: str,
) -> dict[str, Any]:
    manifest = {
        "schema_version": "two_tower_item_vocab_v1",
        "item_vocab_path": str(item_vocab_path),
        "source_paths": {
            "clean_manifest": str(clean_manifest_path),
            "governance_manifest": str(governance_manifest_path),
            "canonical_interactions_train": str(canonical_train_interactions_path),
            "user_sequences_train": str(train_sequences_path),
            "canonical_items_metadata": str(canonical_items_path),
            "user_quality_profile": str(artifact_paths["user_quality_profile"]),
            "item_quality_profile": str(artifact_paths["item_quality_profile"]),
            "item_frequency_train": str(artifact_paths["item_frequency_train"]),
        },
        "item_count": int(item_count),
        "original_item_count": int(item_count),
        "filtered_item_count": 0,
        "min_frequency": 1,
        "metadata_join_added_items": False,
        "universe_policy": TRAINING_ITEM_UNIVERSE_POLICY,
        "negative_universe_policy": negative_universe_policy,
        "target_item_policy": target_item_policy,
        "scale_tier": scale_tier,
        "source_name": "two_tower_dssm",
        "variant": "dssm",
        "text_fields": ["title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"],
        "side_feature_fields": ["item_quality_token", "item_pop_bucket_token", "item_user_count_bucket_token"],
        "forbidden_sources": ["popular_recall.jsonl", "category_recall_items.jsonl", "valid", "test", "holdout", "eval_label", "oracle", "pool1000"],
        "content_hash": f"sha256:{_file_sha256(item_vocab_path)}",
    }
    write_json(path, manifest)
    return manifest


def _update_training_universe_role_counts(role_counts: Counter[str], quality_role_counts: Counter[str], row: dict[str, Any]) -> None:
    roles = set(row.get("item_roles") or [])
    if "negative_candidate" in roles and "positive_target" in roles:
        role = "both"
    elif "negative_candidate" in roles:
        role = "negative_only"
    elif "positive_target" in roles:
        role = "target_only"
    else:
        role = "unknown"
    role_counts[role] += 1
    quality_role_counts[f"{row.get('quality_bucket_v2', 'unknown')}:{role}"] += 1


def _update_side_feature_counts(side_feature_counts: dict[str, Counter[str]], row: dict[str, Any]) -> None:
    for field, counter in side_feature_counts.items():
        token = str(row.get(field) or "")
        if token:
            counter[token] += 1


def _popularity_bucket(frequency: int, global_pop_rank: int) -> str:
    if global_pop_rank > 0:
        if global_pop_rank <= 100:
            return "rank_000001_000100"
        if global_pop_rank <= 1000:
            return "rank_000101_001000"
        if global_pop_rank <= 10000:
            return "rank_001001_010000"
        if global_pop_rank <= 100000:
            return "rank_010001_100000"
        return "rank_100001_plus"
    return _count_bucket(frequency)


def _count_bucket(value: int) -> str:
    if value <= 0:
        return "zero"
    if value == 1:
        return "one"
    if value <= 5:
        return "002_005"
    if value <= 20:
        return "006_020"
    if value <= 100:
        return "021_100"
    if value <= 1000:
        return "101_1000"
    return "1001_plus"


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
    return [event["item_id"] for event in _recent_unique_item_events(raw_items, None, max_items)]


def _recent_unique_item_events(raw_items: Any, raw_times: Any, max_items: int) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    if raw_times is not None and (not isinstance(raw_times, list) or len(raw_times) != len(raw_items)):
        raise ValueError("recent-window sample history times must align with items")
    rows = []
    seen = set()
    item_window = raw_items if max_items <= 0 else raw_items[-max_items:]
    time_window = (raw_times if max_items <= 0 else raw_times[-max_items:]) if isinstance(raw_times, list) else [None] * len(item_window)
    for item, timestamp in reversed(list(zip(item_window, time_window, strict=True))):
        item_id = str(item)
        if item_id and item_id not in seen:
            seen.add(item_id)
            rows.append({"item_id": item_id, "timestamp": int(timestamp) if timestamp is not None else None})
    rows.reverse()
    return rows


def _validate_recent_window_sample_times(history_items: list[str], history_times: list[int | None], target_time: int | None) -> None:
    if target_time is None:
        raise ValueError("recent-window sample target_time is required")
    if len(history_items) != len(history_times):
        raise ValueError("recent-window sample history_times length must match history_items")
    if any(timestamp is None or int(timestamp) >= int(target_time) for timestamp in history_times):
        raise ValueError("recent-window sample history_times must be before target_time")


def _recent_window_policy(clean_manifest: dict[str, Any]) -> dict[str, Any]:
    policy = clean_manifest.get("window_policy")
    if isinstance(policy, dict):
        return policy
    return {"source": "train_user_sequences", "split_scope": "train_only", "boundary_policy": "history_time_lt_target_time"}


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
        hard_negative_policy=args.hard_negative_policy,
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
