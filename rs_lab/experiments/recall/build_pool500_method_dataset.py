from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_lab.experiments.recall.build_train_only_data_governance import load_governance_manifest, method_dataset_policies

SCHEMA_VERSION = "pool500_method_dataset_v1"
ITEMCF_ACTIVE_USER_PENALTY_POLICY = "round(1 / log1p(filtered_sequence_len), 6)"
ITEMCF_SCORE_POLICY = "weighted_cooc_cosine_normalized_v1"
ITEMCF_SCORE_FORMULA = "round(weighted_cooc / sqrt(src_user_count * dst_user_count), 6)"
DEFAULT_GOVERNANCE_MANIFEST = ROOT / "outputs" / "recall" / "data_governance" / "train_only_v1" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_datasets" / "collab_v1"
SOURCE_METHODS = ("itemcf_weak", "itemcf_strong", "usercf_method_dataset", "swing_method_dataset")
POLICY_SOURCE_BY_METHOD = {
    "itemcf_weak": "itemcf_weak",
    "itemcf_strong": "itemcf_strong",
    "usercf_method_dataset": "usercf_recall",
    "swing_method_dataset": "swing_recall",
}
RESOURCE_SCALE_POLICIES: dict[str, dict[str, Any]] = {
    "itemcf_weak": {
        "input_scope": "governance_train_only",
        "scale_tier": "local_formal_default",
        "default_tier": "local_formal",
        "scale_tiers": {
            "smoke": {"max_output_users": 1_000, "max_items_per_user": 50, "max_item_user_freq": 5_000, "min_pair_support": 1, "top_k_per_seed": 100},
            "diagnostic": {"max_output_users": 50_000, "max_items_per_user": 50, "max_item_user_freq": 5_000, "min_pair_support": 1, "top_k_per_seed": 100},
            "local_formal": {"max_output_users": 300_000, "max_items_per_user": 50, "max_item_user_freq": 5_000, "min_pair_support": 1, "top_k_per_seed": 100},
        },
        "selection_policy_version": "p2_method_dataset_policy_v1",
        "selection_strategy": {
            "policy_name": "itemcf_weak_edges_v1",
            "sampling_unit": "user_positive_sequence_to_item_pairs",
            "eligible_user_buckets": ["medium_behavior", "collaborative_rich"],
            "eligible_item_bucket": "cf_ready",
            "over_hot_control": "cap_or_downweight",
            "coverage_mode": "broad",
        },
        "max_output_users": 300_000,
        "max_items_per_user": 50,
        "max_item_user_freq": 5_000,
        "min_pair_support": 1,
        "score_policy": ITEMCF_SCORE_POLICY,
        "active_user_penalty_policy": ITEMCF_ACTIVE_USER_PENALTY_POLICY,
        "weighted_cooc_feature": "weighted_cooc",
        "p2_contract_scope": "method_dataset_only",
    },
    "itemcf_strong": {
        "input_scope": "governance_train_only",
        "scale_tier": "local_formal_default",
        "default_tier": "local_formal",
        "scale_tiers": {
            "smoke": {"max_output_users": 1_000, "max_items_per_user": 50, "max_item_user_freq": 3_000, "min_pair_support": 2, "top_k_per_seed": 100},
            "diagnostic": {"max_output_users": 80_000, "max_items_per_user": 50, "max_item_user_freq": 3_000, "min_pair_support": 2, "top_k_per_seed": 100},
            "local_formal": {"max_output_users": 200_000, "max_items_per_user": 50, "max_item_user_freq": 3_000, "min_pair_support": 2, "top_k_per_seed": 100},
        },
        "selection_policy_version": "p2_method_dataset_policy_v1",
        "selection_strategy": {
            "policy_name": "itemcf_strong_edges_v1",
            "sampling_unit": "user_positive_sequence_to_item_pairs",
            "eligible_user_buckets": ["collaborative_rich"],
            "eligible_item_bucket": "cf_ready",
            "over_hot_control": "strict_cap",
            "pair_window_control": "strong_support_window",
        },
        "max_output_users": 200_000,
        "max_items_per_user": 50,
        "max_item_user_freq": 3_000,
        "min_pair_support": 2,
        "score_policy": ITEMCF_SCORE_POLICY,
        "active_user_penalty_policy": ITEMCF_ACTIVE_USER_PENALTY_POLICY,
        "weighted_cooc_feature": "weighted_cooc",
        "p2_contract_scope": "method_dataset_only",
    },
    "usercf_method_dataset": {
        "input_scope": "governance_train_only",
        "scale_tier": "local_formal_default",
        "default_tier": "local_formal",
        "scale_tiers": {
            "smoke": {"max_output_users": 1_000, "max_items_per_user": 80, "max_item_user_freq": 5_000, "similar_users_top_k": 50},
            "diagnostic": {"max_output_users": 60_000, "max_items_per_user": 80, "max_item_user_freq": 5_000, "similar_users_top_k": 100},
            "local_formal": {"max_output_users": 120_000, "max_items_per_user": 80, "max_item_user_freq": 5_000, "similar_users_top_k": 200},
        },
        "selection_policy_version": "p2_method_dataset_policy_v1",
        "selection_strategy": {
            "policy_name": "usercf_neighbors_v1",
            "sampling_unit": "connected_user_item_subgraph",
            "eligible_user_buckets": ["collaborative_rich", "sequence_sufficient"],
            "min_shared_items_policy": "required",
            "hot_item_influence_control": "cap",
            "shard_unit": "ego_network",
            "record_orphan_counts": True,
        },
        "max_output_users": 120_000,
        "max_items_per_user": 80,
        "max_item_user_freq": 5_000,
        "similar_users_top_k": 200,
        "p2_contract_scope": "method_dataset_only",
    },
    "swing_method_dataset": {
        "input_scope": "governance_train_only",
        "scale_tier": "local_formal_default",
        "default_tier": "local_formal",
        "scale_tiers": {
            "smoke": {"max_graph_users": 2_000, "max_items_per_user": 50, "max_item_user_freq": 1_000, "min_pair_support": 1},
            "diagnostic": {"max_graph_users": 50_000, "max_items_per_user": 80, "max_item_user_freq": 1_000, "min_pair_support": 1},
            "local_formal": {"max_graph_users": 120_000, "max_items_per_user": 80, "max_item_user_freq": 600, "min_pair_support": 2},
        },
        "selection_policy_version": "p2_method_dataset_policy_v1",
        "selection_strategy": {
            "policy_name": "swing_graph_v1",
            "sampling_unit": "bipartite_user_item_graph_to_pair_support",
            "eligible_user_buckets": ["medium_behavior", "collaborative_rich"],
            "min_user_items": 2,
            "eligible_item_bucket": "cf_ready",
            "hot_item_control": "strict_cap",
        },
        "max_graph_users": 120_000,
        "max_items_per_user": 80,
        "max_item_user_freq": 600,
        "min_pair_support": 2,
        "p2_contract_scope": "method_dataset_only",
    },
}
DATASET_FILE_NAME = "method_dataset_rows.jsonl"
OUTPUT_WHITELIST = {"method_dataset_manifest.json", DATASET_FILE_NAME, "README.md", "TODO.md", "migration_punchlist.md"}
FORBIDDEN_SCOPES = ["valid", "test", "holdout", "lopo", "oracle", "eval_label", "clean_10000", "pool1000"]
FORBIDDEN_SCOPE_TOKENS = ("valid", "validation", "test", "holdout", "lopo", "oracle", "eval_label", "clean_10000", "pool1000")
FORBIDDEN_PATH_TOKENS = (*FORBIDDEN_SCOPE_TOKENS, "source_index", "embedding", "faiss", "ann")
FORBIDDEN_INPUT_NAMES = {
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
}
FORBIDDEN_ARTIFACT_TOKENS = {
    "source_index_manifest",
    "source_index_manifest_path",
    "artifact_manifest_path",
    "embedding_path",
    "index_path",
    "candidates",
    "candidates_path",
    "readiness_contract",
    "promotion_manifest",
}
ALLOWED_GUARDRAIL_KEYS = {
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "promotion_allowed",
    "final_pool500_ready_claimed",
}
BLOCKED_OUTPUTS: dict[str, str] = {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build train-only pool500 collaborative method datasets.")
    parser.add_argument("--governance-manifest", default=str(DEFAULT_GOVERNANCE_MANIFEST))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--source-method", choices=SOURCE_METHODS + ("all",), default="all")
    parser.add_argument("--scale-tier", choices=("smoke", "diagnostic", "local_formal"), default="local_formal")
    parser.add_argument("--itemcf-coverage-profile", choices=("strict", "weak_coverage", "relaxed_strong"), default="strict")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_method_datasets(
    *,
    governance_manifest_path: Path = DEFAULT_GOVERNANCE_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    source_methods: Iterable[str] = SOURCE_METHODS,
    scale_tier: str = "local_formal",
    itemcf_coverage_profile: str = "strict",
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, dict[str, Any]]:
    return {
        source_method: build_pool500_method_dataset(
            governance_manifest_path=governance_manifest_path,
            output_dir=Path(output_root) / source_method,
            source_method=source_method,
            scale_tier=scale_tier,
            itemcf_coverage_profile=itemcf_coverage_profile,
            overwrite=overwrite,
            enforce_venv=enforce_venv,
        )
        for source_method in source_methods
    }


def build_pool500_method_dataset(
    *,
    governance_manifest_path: Path = DEFAULT_GOVERNANCE_MANIFEST,
    output_dir: Path,
    source_method: str,
    scale_tier: str = "local_formal",
    itemcf_coverage_profile: str = "strict",
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    if source_method not in SOURCE_METHODS:
        raise ValueError(f"Unsupported source_method: {source_method}")
    resource_policy = _effective_resource_policy(source_method, scale_tier)
    if itemcf_coverage_profile == "weak_coverage":
        resource_policy = _apply_itemcf_weak_coverage_profile(source_method, resource_policy)
    elif itemcf_coverage_profile == "relaxed_strong":
        resource_policy = _apply_itemcf_relaxed_strong_profile(source_method, resource_policy)
    elif itemcf_coverage_profile != "strict":
        raise ValueError(f"Unsupported itemcf_coverage_profile: {itemcf_coverage_profile}")

    governance_manifest_path = Path(governance_manifest_path).resolve()
    output_dir = Path(output_dir).resolve()
    _prepare_output_dir(output_dir, overwrite)

    governance_manifest = load_governance_manifest(governance_manifest_path)
    policies = method_dataset_policies(governance_manifest)
    policy = dict(policies[POLICY_SOURCE_BY_METHOD[source_method]])
    if itemcf_coverage_profile == "weak_coverage" and source_method == "itemcf_weak":
        policy = _apply_itemcf_weak_coverage_selection_policy(policy)
    elif itemcf_coverage_profile == "relaxed_strong" and source_method == "itemcf_strong":
        policy = _apply_itemcf_relaxed_strong_selection_policy(policy)
    paths = _governance_paths(governance_manifest)
    read_files = [governance_manifest_path, paths["user_quality_profile"], paths["item_quality_profile"], paths["item_frequency_train"], paths["train_user_sequences"]]

    blocker = _first_read_file_blocker(read_files)
    if blocker:
        manifest = _manifest(
            source_method=source_method,
            status="BLOCKED",
            governance_manifest_path=governance_manifest_path,
            read_files=read_files,
            policy=policy,
            resource_policy=resource_policy,
            user_bucket_policy=policy["eligible_user_policy"],
            item_bucket_policy=_item_bucket_policy(source_method, resource_policy),
            row_count=0,
            user_count=0,
            item_count=0,
            dropped_reason_counts={blocker: 1},
            outputs=BLOCKED_OUTPUTS,
        )
        write_json(output_dir / "method_dataset_manifest.json", manifest)
        return manifest

    users, user_blocker = _eligible_users(paths["user_quality_profile"], policy["eligible_user_buckets"])
    if user_blocker:
        manifest = _manifest(
            source_method=source_method,
            status="BLOCKED",
            governance_manifest_path=governance_manifest_path,
            read_files=read_files,
            policy=policy,
            resource_policy=resource_policy,
            user_bucket_policy=policy["eligible_user_policy"],
            item_bucket_policy=_item_bucket_policy(source_method, resource_policy),
            row_count=0,
            user_count=0,
            item_count=0,
            dropped_reason_counts={user_blocker: 1},
            outputs=BLOCKED_OUTPUTS,
        )
        write_json(output_dir / "method_dataset_manifest.json", manifest)
        return manifest

    item_user_counts, item_frequency_counts = _item_user_counts(paths["item_frequency_train"])
    item_effective_counts = {item_id: item_user_counts.get(item_id) or item_frequency_counts.get(item_id, 0) for item_id in set(item_user_counts) | set(item_frequency_counts)}
    eligible_items, item_drop_counts = _eligible_items(
        paths["item_quality_profile"],
        item_effective_counts,
        max_item_user_freq=int(resource_policy["max_item_user_freq"]),
        item_quality_buckets=resource_policy.get("item_quality_buckets"),
        allow_over_hot=bool(resource_policy.get("allow_over_hot", False)),
    )
    if source_method in {"itemcf_weak", "itemcf_strong"}:
        eligible_src_items = eligible_items
        if resource_policy.get("src_item_quality_buckets"):
            eligible_src_items, src_item_drop_counts = _eligible_items(
                paths["item_quality_profile"],
                item_effective_counts,
                max_item_user_freq=int(resource_policy["max_item_user_freq"]),
                item_quality_buckets=resource_policy.get("src_item_quality_buckets"),
                allow_over_hot=bool(resource_policy.get("src_allow_over_hot", resource_policy.get("allow_over_hot", False))),
            )
            item_drop_counts.update({f"src_{reason}": count for reason, count in src_item_drop_counts.items()})
        rows, dropped_reason_counts, manifest_counts = _itemcf_edge_rows(
            paths["train_user_sequences"],
            users,
            eligible_src_items,
            item_user_counts,
            item_frequency_counts,
            source_method,
            eligible_dst_items=eligible_items,
            max_output_users=int(resource_policy["max_output_users"]),
            max_items_per_user=int(resource_policy["max_items_per_user"]),
            min_pair_support=int(resource_policy["min_pair_support"]),
            top_k_per_seed=int(resource_policy["top_k_per_seed"]),
            src_sequence_key=resource_policy.get("src_sequence_key"),
            dst_sequence_key=resource_policy.get("dst_sequence_key"),
            directed_seed_to_candidate_only=bool(resource_policy.get("directed_seed_to_candidate_only", False)),
        )
    elif source_method == "swing_method_dataset":
        rows, dropped_reason_counts, manifest_counts = _swing_pair_rows(
            paths["train_user_sequences"],
            users,
            eligible_items,
            item_user_counts,
            max_graph_users=int(resource_policy["max_graph_users"]),
            max_items_per_user=int(resource_policy["max_items_per_user"]),
            min_pair_support=int(resource_policy["min_pair_support"]),
        )
    else:
        rows, dropped_reason_counts, manifest_counts = _dataset_rows(
            paths["train_user_sequences"],
            users,
            eligible_items,
            source_method,
            max_output_users=int(resource_policy["max_output_users"]),
            max_items_per_user=int(resource_policy["max_items_per_user"]),
        )
    dropped_reason_counts.update(item_drop_counts)
    row_path = output_dir / DATASET_FILE_NAME
    write_jsonl(row_path, rows)
    outputs = {"dataset_rows_path": str(row_path), "dataset_schema": _dataset_schema(source_method)}
    if source_method in {"itemcf_weak", "itemcf_strong"}:
        outputs["feature_schema"] = "itemcf_edge_features_v1"
    manifest = _manifest(
        source_method=source_method,
        status="PASS",
        governance_manifest_path=governance_manifest_path,
        read_files=read_files,
        policy=policy,
        resource_policy=resource_policy,
        user_bucket_policy=policy["eligible_user_policy"],
        item_bucket_policy=_item_bucket_policy(source_method, resource_policy),
        row_count=len(rows),
        user_count=manifest_counts["user_count"],
        item_count=manifest_counts["item_count"],
        dropped_reason_counts=dict(dropped_reason_counts),
        outputs=outputs,
    )
    for count_key in (
        "schema_name",
        "unique_pair_count",
        "edge_count",
        "directed_edge_count_after_topk",
        "top_k_per_seed",
        "score_policy",
        "active_user_penalty_policy",
        "itemcf_score_formula",
        "weighted_cooc_sum_before_topk",
        "weighted_cooc_sum_after_topk",
        "feature_summary",
    ):
        if count_key in manifest_counts:
            manifest[count_key] = manifest_counts[count_key]
    audit = _forbidden_scope_audit(output_dir, manifest, rows)
    manifest["forbidden_scope_audit"] = audit
    if audit["status"] != "PASS":
        manifest["status"] = "BLOCKED"
    write_json(output_dir / "method_dataset_manifest.json", manifest)
    _enforce_output_whitelist(output_dir)
    return manifest


def _effective_resource_policy(source_method: str, scale_tier: str) -> dict[str, Any]:
    policy = dict(RESOURCE_SCALE_POLICIES[source_method])
    scale_tiers = policy["scale_tiers"]
    if scale_tier not in scale_tiers:
        raise ValueError(f"Unsupported scale_tier: {scale_tier}")
    policy.update(scale_tiers[scale_tier])
    policy["scale_tier"] = scale_tier
    return policy


def _apply_itemcf_weak_coverage_profile(source_method: str, resource_policy: dict[str, Any]) -> dict[str, Any]:
    if source_method != "itemcf_weak":
        raise ValueError("weak_coverage profile is only supported for itemcf_weak")
    policy = dict(resource_policy)
    policy.update(
        {
            "dataset_variant": "itemcf_weak_coverage_formal_v1",
            "coverage_profile": "weak_coverage",
            "max_output_users": 120_000,
            "max_items_per_user": 80,
            "max_item_user_freq": 20_000,
            "min_pair_support": 1,
            "top_k_per_seed": 200,
            "item_quality_buckets": ["cf_ready", "embedding_ready"],
            "allow_over_hot": True,
            "over_hot_control": "allow_with_user_freq_cap_and_score_denominator",
        }
    )
    selection_strategy = dict(policy.get("selection_strategy") or {})
    selection_strategy.update(
        {
            "eligible_user_buckets": ["medium_behavior", "sequence_sufficient", "collaborative_rich"],
            "eligible_item_buckets": ["cf_ready", "embedding_ready"],
            "over_hot_control": "allow_with_user_freq_cap_and_score_denominator",
            "coverage_mode": "broad_coverage_formal",
        }
    )
    policy["selection_strategy"] = selection_strategy
    return policy


def _apply_itemcf_relaxed_strong_profile(source_method: str, resource_policy: dict[str, Any]) -> dict[str, Any]:
    if source_method != "itemcf_strong":
        raise ValueError("relaxed_strong profile is only supported for itemcf_strong")
    policy = dict(resource_policy)
    scale_tier = str(policy.get("scale_tier") or policy.get("default_tier") or "local_formal")
    relaxed_scale_tiers = {
        "smoke": {"max_output_users": 5_000, "max_items_per_user": 60, "max_item_user_freq": 8_000, "min_pair_support": 1, "top_k_per_seed": 150},
        "diagnostic": {"max_output_users": 80_000, "max_items_per_user": 60, "max_item_user_freq": 8_000, "min_pair_support": 1, "top_k_per_seed": 150},
        "local_formal": {"max_output_users": 160_000, "max_items_per_user": 60, "max_item_user_freq": 8_000, "min_pair_support": 1, "top_k_per_seed": 150},
    }
    policy.update(
        {
            "dataset_variant": f"itemcf_strong_relaxed_seedsrc_{scale_tier}_v3",
            "coverage_profile": "relaxed_strong",
            "relaxed_scale_tiers": relaxed_scale_tiers,
            **relaxed_scale_tiers[scale_tier],
            "item_quality_buckets": ["cf_ready", "embedding_ready"],
            "src_item_quality_buckets": ["cf_ready", "embedding_ready"],
            "dst_item_quality_buckets": ["cf_ready", "embedding_ready"],
            "allow_over_hot": False,
            "src_allow_over_hot": True,
            "src_sequence_key": "recent_strong_positive_item_sequence",
            "dst_sequence_key": "recent_positive_item_sequence",
            "directed_seed_to_candidate_only": True,
            "over_hot_control": "allow_hot_src_seed_but_exclude_hot_dst_candidate",
        }
    )
    selection_strategy = dict(policy.get("selection_strategy") or {})
    selection_strategy.update(
        {
            "policy_name": "itemcf_strong_relaxed_edges_v1",
            "eligible_user_buckets": ["sequence_sufficient", "collaborative_rich"],
            "eligible_item_buckets": ["cf_ready", "embedding_ready"],
            "eligible_src_item_buckets": ["cf_ready", "embedding_ready"],
            "eligible_dst_item_buckets": ["cf_ready", "embedding_ready"],
            "over_hot_control": "allow_hot_src_seed_but_exclude_hot_dst_candidate",
            "coverage_mode": "relaxed_high_confidence",
            "pair_window_control": "strong_support_window",
        }
    )
    policy["selection_strategy"] = selection_strategy
    return policy


def _apply_itemcf_weak_coverage_selection_policy(policy: dict[str, Any]) -> dict[str, Any]:
    updated = dict(policy)
    updated["eligible_user_buckets"] = ["medium_behavior", "sequence_sufficient", "collaborative_rich"]
    updated["eligible_user_policy"] = "sequence_sufficient_or_above_for_coverage_itemcf"
    updated["eligible_item_policy"] = "cf_ready_or_embedding_ready_with_user_freq_cap"
    updated["acceptance_checks"] = [
        "train_only_inputs",
        "eligible_user_bucket_is_sequence_sufficient_or_above",
        "item_user_freq_cap_applied",
        "active_user_penalty_applied",
    ]
    return updated


def _apply_itemcf_relaxed_strong_selection_policy(policy: dict[str, Any]) -> dict[str, Any]:
    updated = dict(policy)
    updated["eligible_user_buckets"] = ["sequence_sufficient", "collaborative_rich"]
    updated["eligible_user_policy"] = "sequence_sufficient_or_collaborative_rich_for_relaxed_strong_itemcf"
    updated["eligible_item_policy"] = "src_cf_ready_or_embedding_ready_can_be_hot_to_dst_cf_ready_or_embedding_ready_non_hot_with_relaxed_user_freq_cap"
    updated["acceptance_checks"] = [
        "train_only_inputs",
        "eligible_user_bucket_is_sequence_sufficient_or_collaborative_rich",
        "relaxed_pair_support_gte_1",
        "src_seed_item_can_be_embedding_ready",
        "dst_candidate_item_must_be_cf_ready_or_embedding_ready",
        "item_user_freq_cap_applied",
        "hot_src_seed_allowed",
        "hot_dst_candidate_excluded",
        "active_user_penalty_applied",
    ]
    return updated


def _prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)


def _governance_paths(manifest: dict[str, Any]) -> dict[str, Path]:
    artifacts = manifest.get("artifacts")
    lineage = manifest.get("lineage")
    input_files = lineage.get("input_files") if isinstance(lineage, dict) else None
    if not isinstance(artifacts, dict) or not isinstance(input_files, dict):
        raise ValueError("Governance manifest must contain artifacts and lineage.input_files")
    return {
        "user_quality_profile": Path(str(artifacts["user_quality_profile"])).resolve(),
        "item_quality_profile": Path(str(artifacts["item_quality_profile"])).resolve(),
        "item_frequency_train": Path(str(artifacts["item_frequency_train"])).resolve(),
        "train_user_sequences": Path(str(input_files["user_sequences_train"])).resolve(),
    }


def _first_read_file_blocker(paths: list[Path]) -> str | None:
    for path in paths:
        if _path_has_forbidden_scope(path):
            return f"forbidden_non_train_path:{path.name}"
        if not path.is_file():
            return f"missing_input:{path.name}"
    return None


def _path_has_forbidden_scope(path: Path) -> bool:
    lowered = str(path).replace("\\", "/").lower()
    parts = {part.lower() for part in path.parts}
    return (
        path.name.lower() in FORBIDDEN_INPUT_NAMES
        or bool(parts & set(FORBIDDEN_SCOPE_TOKENS))
        or _has_forbidden_filename_token(path.name)
        or "eval_label" in lowered
        or "clean_10000" in lowered
        or "source_index" in lowered
        or "embedding" in lowered
        or "faiss" in lowered
        or "/ann/" in lowered
    )


def _has_forbidden_filename_token(name: str) -> bool:
    lowered = name.lower()
    return any(re.search(rf"(^|[^a-z0-9]){re.escape(token)}([^a-z0-9]|$)", lowered) for token in FORBIDDEN_PATH_TOKENS)


def _eligible_users(path: Path, allowed_buckets: list[str]) -> tuple[dict[str, str], str | None]:
    users: dict[str, str] = {}
    for row in iter_jsonl(path):
        if "quality_bucket_v2" not in row:
            return {}, "missing_user_quality_bucket_v2"
        bucket = str(row.get("quality_bucket_v2") or "")
        user_id = str(row.get("user_id") or "")
        if user_id and bucket in set(allowed_buckets):
            users[user_id] = bucket
    return users, None


def _item_user_counts(path: Path) -> tuple[dict[str, int], dict[str, int]]:
    user_counts: dict[str, int] = {}
    frequency_counts: dict[str, int] = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if item_id:
            user_counts[item_id] = int(row.get("user_count") or 0)
            frequency_counts[item_id] = int(row.get("frequency") or 0)
    return user_counts, frequency_counts


def _eligible_items(
    path: Path,
    item_user_counts: dict[str, int],
    *,
    max_item_user_freq: int,
    item_quality_buckets: list[str] | None = None,
    allow_over_hot: bool = False,
) -> tuple[set[str], Counter[str]]:
    eligible: set[str] = set()
    dropped: Counter[str] = Counter()
    allowed_quality_buckets = set(item_quality_buckets or [])
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or "")
        if not item_id:
            dropped["missing_item_id"] += 1
            continue
        if "quality_bucket_v2" not in row:
            dropped["missing_item_quality_bucket_v2"] += 1
            continue
        quality_bucket = str(row.get("quality_bucket_v2") or "")
        cf_ready = row.get("cf_ready") is True
        quality_allowed = quality_bucket in allowed_quality_buckets if allowed_quality_buckets else cf_ready
        over_hot = _is_over_hot(row)
        if not quality_allowed:
            if allowed_quality_buckets:
                dropped["item_quality_bucket_not_allowed"] += 1
            else:
                dropped["item_not_cf_ready"] += 1
            continue
        if over_hot and not allow_over_hot:
            dropped["item_over_hot"] += 1
            continue
        if item_user_counts.get(item_id, 0) > max_item_user_freq:
            dropped["item_user_freq_over_cap"] += 1
            continue
        eligible.add(item_id)
    return eligible, dropped


def _is_over_hot(row: dict[str, Any]) -> bool:
    return row.get("hotness_bucket") == "hot"


def _dataset_rows(
    path: Path,
    users: dict[str, str],
    eligible_items: set[str],
    source_method: str,
    *,
    max_output_users: int,
    max_items_per_user: int,
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    for sequence in iter_jsonl(path):
        user_id = str(sequence.get("user_id") or "")
        if user_id not in users:
            dropped["user_bucket_not_allowed"] += 1
            continue
        if len(rows) >= max_output_users:
            dropped["max_output_users_exceeded"] += 1
            continue
        positives = [str(item_id) for item_id in sequence.get("recent_positive_item_sequence") or [] if item_id]
        filtered_all = [item_id for item_id in positives if item_id in eligible_items]
        filtered = filtered_all[:max_items_per_user]
        if not filtered:
            dropped["no_cf_ready_non_over_hot_items"] += 1
            continue
        if len(filtered_all) > len(filtered):
            dropped["items_over_user_cap"] += len(filtered_all) - len(filtered)
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "source_method": source_method,
                "train_only": True,
                "user_id": user_id,
                "user_bucket_v2": users[user_id],
                "positive_item_count": len(positives),
                "eligible_item_sequence": filtered,
                "dropped_item_count": len(positives) - len(filtered),
            }
        )
    counts = {
        "user_count": len({row["user_id"] for row in rows}),
        "item_count": len({item_id for row in rows for item_id in row["eligible_item_sequence"]}),
    }
    return rows, dropped, counts


def _itemcf_edge_rows(
    path: Path,
    users: dict[str, str],
    eligible_items: set[str],
    item_user_counts: dict[str, int],
    item_frequency_counts: dict[str, int],
    source_method: str,
    *,
    eligible_dst_items: set[str] | None = None,
    max_output_users: int,
    max_items_per_user: int,
    min_pair_support: int,
    top_k_per_seed: int,
    src_sequence_key: str | None = None,
    dst_sequence_key: str | None = None,
    directed_seed_to_candidate_only: bool = False,
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, Any]]:
    eligible_dst_items = eligible_dst_items or eligible_items
    pair_items = eligible_items | eligible_dst_items
    pair_support: Counter[tuple[str, str]] = Counter()
    pair_weighted_cooc: Counter[tuple[str, str]] = Counter()
    pair_user_buckets: dict[tuple[str, str], Counter[str]] = {}
    contributing_users: set[str] = set()
    dropped: Counter[str] = Counter()
    for sequence in iter_jsonl(path):
        user_id = str(sequence.get("user_id") or "")
        if user_id not in users:
            dropped["user_bucket_not_allowed"] += 1
            continue
        if len(contributing_users) >= max_output_users:
            dropped["max_output_users_exceeded"] += 1
            continue
        default_sequence_key = "recent_strong_positive_item_sequence" if source_method == "itemcf_strong" else "recent_positive_item_sequence"
        source_sequence_key = src_sequence_key or default_sequence_key
        target_sequence_key = dst_sequence_key or source_sequence_key
        src_positives = [str(item_id) for item_id in sequence.get(source_sequence_key) or [] if item_id]
        dst_positives = [str(item_id) for item_id in sequence.get(target_sequence_key) or [] if item_id]
        if directed_seed_to_candidate_only:
            filtered_src_all = _unique_in_order(item_id for item_id in src_positives if item_id in eligible_items)
            filtered_dst_all = _unique_in_order(item_id for item_id in dst_positives if item_id in eligible_dst_items)
            filtered_src = filtered_src_all[:max_items_per_user]
            filtered_dst = filtered_dst_all[:max_items_per_user]
            if len(filtered_src_all) > len(filtered_src):
                dropped["src_items_over_user_cap"] += len(filtered_src_all) - len(filtered_src)
            if len(filtered_dst_all) > len(filtered_dst):
                dropped["dst_items_over_user_cap"] += len(filtered_dst_all) - len(filtered_dst)
            directed_pairs = [(src_item, dst_item) for src_item in filtered_src for dst_item in filtered_dst if src_item != dst_item]
            if not directed_pairs:
                dropped["insufficient_pair_items"] += 1
                continue
            active_user_penalty = round(1 / math.log1p(len(set(filtered_src) | set(filtered_dst))), 6)
            contributing_users.add(user_id)
            for pair in directed_pairs:
                pair_support[pair] += 1
                pair_weighted_cooc[pair] += active_user_penalty
                pair_user_buckets.setdefault(pair, Counter())[users[user_id]] += 1
            continue
        positives = src_positives
        filtered_all = _unique_in_order(item_id for item_id in positives if item_id in pair_items)
        filtered = filtered_all[:max_items_per_user]
        if len(filtered_all) > len(filtered):
            dropped["items_over_user_cap"] += len(filtered_all) - len(filtered)
        if len(filtered) < 2:
            dropped["insufficient_pair_items"] += 1
            continue
        active_user_penalty = round(1 / math.log1p(len(filtered)), 6)
        contributing_users.add(user_id)
        for pair in combinations(sorted(filtered), 2):
            pair_support[pair] += 1
            pair_weighted_cooc[pair] += active_user_penalty
            pair_user_buckets.setdefault(pair, Counter())[users[user_id]] += 1

    supported_pairs = [(pair, support) for pair, support in sorted(pair_support.items()) if support >= min_pair_support]
    dropped["pair_below_min_support"] += sum(1 for support in pair_support.values() if support < min_pair_support)

    edges_by_src: dict[str, list[dict[str, Any]]] = {}
    emitted_pairs: set[tuple[str, str]] = set()
    directed_edge_count_before_topk = 0
    weighted_cooc_sum_before_topk = 0.0
    for (item_i, item_j), support in supported_pairs:
        weighted_cooc = round(pair_weighted_cooc[(item_i, item_j)], 6)
        directions = ((item_i, item_j),) if directed_seed_to_candidate_only else ((item_i, item_j), (item_j, item_i))
        for src_item_id, dst_item_id in directions:
            if src_item_id not in eligible_items:
                dropped["edge_src_item_not_allowed"] += 1
                continue
            if dst_item_id not in eligible_dst_items:
                dropped["edge_dst_item_not_allowed"] += 1
                continue
            src_user_count = item_user_counts.get(src_item_id) or item_frequency_counts.get(src_item_id, 0)
            dst_user_count = item_user_counts.get(dst_item_id) or item_frequency_counts.get(dst_item_id, 0)
            if src_user_count <= 0 or dst_user_count <= 0:
                dropped["missing_or_zero_item_user_count"] += 1
                continue
            itemcf_score = round(weighted_cooc / math.sqrt(src_user_count * dst_user_count), 6)
            emitted_pairs.add((item_i, item_j))
            directed_edge_count_before_topk += 1
            weighted_cooc_sum_before_topk += weighted_cooc
            edges_by_src.setdefault(src_item_id, []).append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "dataset_role": "method_dataset_itemcf_edge_feature",
                    "source_method": source_method,
                    "train_only": True,
                    "item_i": item_i,
                    "item_j": item_j,
                    "src_item_id": src_item_id,
                    "dst_item_id": dst_item_id,
                    "pair_support": support,
                    "cooc_cnt": support,
                    "supporting_user_count": support,
                    "weighted_cooc": weighted_cooc,
                    "src_user_count": src_user_count,
                    "dst_user_count": dst_user_count,
                    "itemcf_score": itemcf_score,
                    "score_policy": ITEMCF_SCORE_POLICY,
                    "itemcf_score_formula": ITEMCF_SCORE_FORMULA,
                    "active_user_penalty_policy": ITEMCF_ACTIVE_USER_PENALTY_POLICY,
                    "supporting_user_buckets": dict(sorted(pair_user_buckets[(item_i, item_j)].items())),
                    "min_pair_support": min_pair_support,
                    "top_k_per_seed": top_k_per_seed,
                }
            )

    rows: list[dict[str, Any]] = []
    for src_item_id in sorted(edges_by_src):
        ranked_edges = sorted(edges_by_src[src_item_id], key=lambda row: (-row["itemcf_score"], -row["cooc_cnt"], row["dst_item_id"]))
        if len(ranked_edges) > top_k_per_seed:
            dropped["edge_over_top_k_per_seed"] += len(ranked_edges) - top_k_per_seed
        for edge_rank, row in enumerate(ranked_edges[:top_k_per_seed], start=1):
            row["edge_rank"] = edge_rank
            rows.append(row)

    unique_pair_count = len(emitted_pairs)
    edge_count = directed_edge_count_before_topk
    item_ids = {item_id for row in rows for item_id in (row["item_i"], row["item_j"])}
    weighted_cooc_sum_before_topk = round(weighted_cooc_sum_before_topk, 6)
    weighted_cooc_sum_after_topk = round(sum(row["weighted_cooc"] for row in rows), 6)
    counts = {
        "user_count": len(contributing_users),
        "item_count": len(item_ids),
        "unique_pair_count": unique_pair_count,
        "edge_count": edge_count,
        "directed_edge_count_after_topk": len(rows),
        "top_k_per_seed": top_k_per_seed,
        "schema_name": "itemcf_edge_features_v1",
        "score_policy": ITEMCF_SCORE_POLICY,
        "active_user_penalty_policy": ITEMCF_ACTIVE_USER_PENALTY_POLICY,
        "itemcf_score_formula": ITEMCF_SCORE_FORMULA,
        "weighted_cooc_sum_before_topk": weighted_cooc_sum_before_topk,
        "weighted_cooc_sum_after_topk": weighted_cooc_sum_after_topk,
        "feature_summary": {
            "schema_name": "itemcf_edge_features_v1",
            "layer": "method_dataset",
            "score_policy": ITEMCF_SCORE_POLICY,
            "score_formula": ITEMCF_SCORE_FORMULA,
            "active_user_penalty_policy": ITEMCF_ACTIVE_USER_PENALTY_POLICY,
            "rank_policy": "source_method + src_item_id by itemcf_score desc, cooc_cnt desc, dst_item_id asc",
            "unique_pair_count_before_topk": unique_pair_count,
            "directed_edge_count_before_topk": directed_edge_count_before_topk,
            "directed_edge_count_after_topk": len(rows),
            "weighted_cooc_sum_before_topk": weighted_cooc_sum_before_topk,
            "weighted_cooc_sum_after_topk": weighted_cooc_sum_after_topk,
            "dropped_reason_counts": dict(dropped),
        },
    }
    return rows, dropped, counts


def _swing_pair_rows(
    path: Path,
    users: dict[str, str],
    eligible_items: set[str],
    item_user_counts: dict[str, int],
    *,
    max_graph_users: int,
    max_items_per_user: int,
    min_pair_support: int,
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, int]]:
    pair_support: Counter[tuple[str, str]] = Counter()
    contributing_users: set[str] = set()
    dropped: Counter[str] = Counter()
    for sequence in iter_jsonl(path):
        user_id = str(sequence.get("user_id") or "")
        if user_id not in users:
            dropped["user_bucket_not_allowed"] += 1
            continue
        if len(contributing_users) >= max_graph_users:
            dropped["max_graph_users_exceeded"] += 1
            continue
        positives = [str(item_id) for item_id in sequence.get("recent_positive_item_sequence") or [] if item_id]
        filtered = _unique_in_order(item_id for item_id in positives if item_id in eligible_items)[:max_items_per_user]
        if len(filtered) < 2:
            dropped["insufficient_graph_items"] += 1
            continue
        contributing_users.add(user_id)
        for pair in combinations(sorted(filtered), 2):
            pair_support[pair] += 1
    rows = [
        {
            "schema_version": SCHEMA_VERSION,
            "dataset_role": "method_dataset_swing_pair_support",
            "source_method": "swing_method_dataset",
            "train_only": True,
            "item_i": item_i,
            "item_j": item_j,
            "pair_support": support,
            "graph_user_support": support,
            "item_i_user_count": item_user_counts.get(item_i, 0),
            "item_j_user_count": item_user_counts.get(item_j, 0),
            "min_pair_support": min_pair_support,
        }
        for (item_i, item_j), support in sorted(pair_support.items())
        if support >= min_pair_support
    ]
    dropped["pair_below_min_support"] += sum(1 for support in pair_support.values() if support < min_pair_support)
    counts = {
        "user_count": len(contributing_users),
        "item_count": len({item_id for row in rows for item_id in (row["item_i"], row["item_j"])}),
    }
    return rows, dropped, counts


def _unique_in_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            unique.append(value)
            seen.add(value)
    return unique


def _dataset_schema(source_method: str) -> str:
    if source_method in {"itemcf_weak", "itemcf_strong"}:
        return "itemcf_edge_features_v1"
    if source_method == "swing_method_dataset":
        return "swing_item_pair_support_v1"
    return "eligible_user_sequence_v1"


def _manifest(
    *,
    source_method: str,
    status: str,
    governance_manifest_path: Path,
    read_files: list[Path],
    policy: dict[str, Any],
    resource_policy: dict[str, Any],
    user_bucket_policy: str,
    item_bucket_policy: str,
    row_count: int,
    user_count: int,
    item_count: int,
    dropped_reason_counts: dict[str, int],
    outputs: dict[str, str],
) -> dict[str, Any]:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "layer": "method_dataset",
        "source_method": source_method,
        "status": status,
        "train_only": True,
        "upstream_governance_manifest_path": str(governance_manifest_path),
        "upstream_governance_manifest_hash": _file_sha256(governance_manifest_path),
        "read_files": [str(path) for path in read_files],
        "input_hashes": {path.name: _file_sha256(path) for path in read_files if path.is_file()},
        "forbidden_scopes": FORBIDDEN_SCOPES,
        "forbidden_scope_audit": {"status": "PASS", "hits": []},
        "selection_policy": policy,
        "resource_scale_policy": dict(resource_policy),
        "effective_user_bucket_policy": user_bucket_policy,
        "effective_item_bucket_policy": item_bucket_policy,
        "row_count": row_count,
        "user_count": user_count,
        "item_count": item_count,
        "dropped_reason_counts": dropped_reason_counts,
        "outputs": outputs,
        "is_source_artifact": False,
        "is_candidate": False,
        "is_ranking": False,
        "is_promotion": False,
        "config_hash": _config_hash(
            {
                "source_method": source_method,
                "selection_policy": policy,
                "resource_scale_policy": resource_policy,
                "item_bucket_policy": item_bucket_policy,
            }
        ),
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return manifest


def _item_bucket_policy(source_method: str, resource_policy: dict[str, Any] | None = None) -> str:
    if source_method == "swing_method_dataset":
        return "item_quality_profile.cf_ready=true and over_hot=false for swing collaborative pairs"
    if resource_policy and resource_policy.get("coverage_profile") == "weak_coverage":
        return "item_quality_profile.quality_bucket_v2 in {cf_ready, embedding_ready}; over_hot allowed only under item_user_freq cap"
    if resource_policy and resource_policy.get("coverage_profile") == "relaxed_strong":
        return "src strong-seed items in {cf_ready, embedding_ready} with hot allowed; dst candidate items in {cf_ready, embedding_ready} and non-hot"
    return "item_quality_profile.cf_ready=true and over_hot=false for collaborative filtering"


def _forbidden_scope_audit(output_dir: Path, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    hits = list(_forbidden_hits({"manifest": manifest, "rows": rows}))
    forbidden_output_files = sorted(path.name for path in output_dir.iterdir() if path.name not in OUTPUT_WHITELIST)
    hits.extend(f"output_file:{name}" for name in forbidden_output_files)
    return {"status": "PASS" if not hits else "BLOCKED", "hits": hits, "output_whitelist": sorted(OUTPUT_WHITELIST)}


def _forbidden_hits(value: Any, context: str = "payload") -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            key_context = f"{context}.{key_text}"
            if key_text in FORBIDDEN_ARTIFACT_TOKENS:
                yield key_context
            if key_text not in ALLOWED_GUARDRAIL_KEYS:
                yield from _forbidden_hits(nested, key_context)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _forbidden_hits(nested, f"{context}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if "full_pool500_ready" in lowered or lowered == "ready" or "promotion_manifest" in lowered:
            yield context


def _enforce_output_whitelist(output_dir: Path) -> None:
    unexpected = sorted(path.name for path in output_dir.iterdir() if path.name not in OUTPUT_WHITELIST)
    if unexpected:
        raise ValueError(f"Unexpected method dataset outputs: {unexpected}")


def _config_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    source_methods = SOURCE_METHODS if args.source_method == "all" else (args.source_method,)
    manifests = build_pool500_method_datasets(
        governance_manifest_path=Path(args.governance_manifest),
        output_root=Path(args.output_root),
        source_methods=source_methods,
        scale_tier=args.scale_tier,
        itemcf_coverage_profile=args.itemcf_coverage_profile,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({method: manifest["status"] for method, manifest in manifests.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
