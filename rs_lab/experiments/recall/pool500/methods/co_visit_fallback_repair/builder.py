from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.online.recall.candidate_merge import metadata_neighbor_candidates_for_user, stable_itemcf_shard_id
from rs_lab.experiments.recall.pool500.common.source_layout import FORBIDDEN_EVIDENCE_SCOPES, REQUIRED_SOURCE_OUTPUTS, method_output_dir

SOURCE = "co_visit_fallback_repair"
SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
TRANSITION_GRAPH_SOURCE_STATUS = "UNDERFILL_REPAIR_INDEX_READY"
TRANSITION_GRAPH_SCHEMA_VERSION = "pool500_co_visit_transition_graph_v1"
SCHEMA_VERSION = "pool500_co_visit_fallback_repair_v1"
ALGORITHM_SCOPE = "train_transition_metadata_repair_v2"
DEFAULT_CONFIG_PATH = ROOT / "configs" / "recall" / "full_data_pool500" / SOURCE / "source_config.yaml"
CONFIG_STRUCTURAL_KEYS = {"defaults", "tiers", "tier_aliases"}
FORBIDDEN_TOKENS = tuple(token.lower() for token in FORBIDDEN_EVIDENCE_SCOPES)


def build_co_visit_fallback_repair_source(
    *,
    clean_manifest_path: Path | None = None,
    lightweight_views_manifest_path: Path | None = None,
    eligible_user_manifest_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
    tier: str | None = None,
    max_metadata_rows: int | None = None,
    candidate_per_user: int | None = None,
    candidate_per_seed: int | None = None,
    seed_window: int | None = None,
    transition_window: int | None = None,
    transition_per_seed: int | None = None,
    checkpoint_every_users: int | None = None,
    target_user_offset: int | None = None,
    target_user_limit: int | None = None,
    shard_id: int | None = None,
    shard_count: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    config = _effective_config(config_path, tier, {
        "run_id": run_id,
        "output_root": str(output_root) if output_root is not None else None,
        "input_contract": {
            "clean_manifest": str(clean_manifest_path) if clean_manifest_path is not None else None,
            "lightweight_views_manifest": str(lightweight_views_manifest_path) if lightweight_views_manifest_path is not None else None,
            "eligible_user_manifest": str(eligible_user_manifest_path) if eligible_user_manifest_path is not None else None,
        },
        "method_config": {
            "max_metadata_rows": max_metadata_rows,
            "candidate_per_user": candidate_per_user,
            "candidate_per_seed": candidate_per_seed,
            "seed_window": seed_window,
            "transition_window": transition_window,
            "transition_per_seed": transition_per_seed,
            "checkpoint_every_users": checkpoint_every_users,
            "target_user_offset": target_user_offset,
            "target_user_limit": target_user_limit,
            "shard_id": shard_id,
            "shard_count": shard_count,
        },
    })
    input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    clean_manifest_path = _config_path(input_contract, "data/processed/amazon_2023_recall_clean_full/manifest.json", "clean_manifest", "clean_manifest_path")
    lightweight_views_manifest_path = _config_path(input_contract, "data/processed/amazon_2023_recall_views_full_lightweight/manifest.json", "lightweight_views_manifest", "lightweight_views_manifest_path")
    eligible_user_manifest_path = _config_path(input_contract, "outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json", "eligible_user_manifest", "eligible_user_manifest_path")
    output_root = _config_path(config, "outputs/recall/pool500_method_sources", "output_root")
    run_id = str(config.get("run_id") or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    max_metadata_rows = int(method_config.get("max_metadata_rows", 250_000))
    candidate_per_user = int(method_config.get("candidate_per_user", 120))
    candidate_per_seed = int(method_config.get("candidate_per_seed", 40))
    seed_window = int(method_config.get("seed_window", 30))
    transition_window = int(method_config.get("transition_window", 5))
    transition_per_seed = int(method_config.get("transition_per_seed", 200))
    transition_decay = str(method_config.get("transition_decay", "reciprocal"))
    transition_popularity_norm_alpha = float(method_config.get("transition_popularity_norm_alpha", 0.0))
    min_pair_support = int(method_config.get("min_pair_support", 1))
    min_distinct_user_support = int(method_config.get("min_distinct_user_support", 1))
    underfill_repair_enabled = bool(method_config.get("underfill_repair_enabled", True))
    underfill_repair_per_seed_multiplier = int(method_config.get("underfill_repair_per_seed_multiplier", 3))
    checkpoint_every_users = int(method_config.get("checkpoint_every_users", 50))

    output_root = output_root if output_root.is_absolute() else _resolve_repo_path(output_root)
    output_dir = output_root / run_id if output_root.name == SOURCE else method_output_dir(output_root, SOURCE, run_id)
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(lightweight_views_manifest_path)
    eligible_manifest = read_json(eligible_user_manifest_path)
    train_sequences_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    train_interactions_path = _resolve_train_interactions_path(clean_manifest)
    semantic_inputs_path = _resolve_repo_path(views_manifest["outputs"]["semantic_recall_inputs"])
    all_target_users = [str(user_id) for user_id in eligible_manifest.get("eligible_user_ids", [])]
    target_user_offset = int(method_config.get("target_user_offset", 0) or 0)
    target_user_limit_value = method_config.get("target_user_limit")
    target_user_limit = int(target_user_limit_value) if target_user_limit_value is not None else None
    shard_id_value = method_config.get("shard_id")
    shard_count_value = method_config.get("shard_count")
    shard_id = int(shard_id_value) if shard_id_value is not None else None
    shard_count = int(shard_count_value) if shard_count_value is not None else None
    _validate_shard_contract(target_user_offset, target_user_limit, shard_id, shard_count)
    target_users = all_target_users[target_user_offset:]
    if target_user_limit is not None:
        target_users = target_users[:target_user_limit]
    if shard_id is not None and shard_count is not None:
        target_users = [user_id for index, user_id in enumerate(target_users) if index % shard_count == shard_id]
    shard_contract = _shard_contract(
        full_eligible_user_count=len(all_target_users),
        selected_target_user_count=len(target_users),
        target_user_offset=target_user_offset,
        target_user_limit=target_user_limit,
        shard_id=shard_id,
        shard_count=shard_count,
        checkpoint_every_users=checkpoint_every_users,
    )
    sequences = _load_target_sequences(train_sequences_path, target_users)
    target_seed_items = {
        item_id
        for sequence in sequences.values()
        for item_id in _recent_unique(sequence.get("recent_positive_item_sequence", []), seed_window)
    }
    metadata_index = _load_metadata_index(semantic_inputs_path, sequences, max_metadata_rows, seed_window)
    transition_index, transition_scan_audit = _load_train_transition_index(
        train_interactions_path,
        target_seed_items,
        transition_window,
        transition_per_seed,
        transition_decay=transition_decay,
        popularity_norm_alpha=transition_popularity_norm_alpha,
        min_pair_support=min_pair_support,
        min_distinct_user_support=min_distinct_user_support,
    )

    generation_config = {
        "metadata_neighbor_enabled": True,
        "metadata_neighbor_seed_window": seed_window,
        "metadata_neighbor_per_seed": candidate_per_seed,
        "metadata_neighbor_per_user": candidate_per_user,
        "metadata_neighbor_min_token_overlap": int(method_config.get("min_token_overlap", 1)),
        "metadata_neighbor_max_bucket_candidates": int(method_config.get("max_bucket_candidates", 1000)),
        "metadata_neighbor_category_weight": float(method_config.get("category_weight", 2.0)),
        "transition_window": transition_window,
        "transition_per_seed": transition_per_seed,
        "transition_decay": transition_decay,
        "transition_popularity_norm_alpha": transition_popularity_norm_alpha,
        "min_pair_support": min_pair_support,
        "min_distinct_user_support": min_distinct_user_support,
        "underfill_repair_enabled": underfill_repair_enabled,
        "underfill_repair_per_seed_multiplier": underfill_repair_per_seed_multiplier,
    }

    source_candidates_path = output_dir / "candidates.jsonl"
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir()
    target_user_set = set(target_users)
    missing_users = sorted(target_user_set - set(sequences))
    include_full_per_user_audit = len(target_users) <= int(method_config.get("full_per_user_audit_limit", 20_000))
    per_user: dict[str, dict[str, Any]] = {}
    per_user_sample: dict[str, dict[str, Any]] = {}
    per_user_sample_limit = int(method_config.get("per_user_audit_sample_limit", 1_000))
    candidate_counts: list[int] = []
    candidate_row_count = 0
    seed_covered_users = 0
    metadata_covered_users = 0
    transition_covered_users = 0
    user_coverage_count = 0
    unique_item_ids: set[str] = set()
    undercovered_user_count = 0
    undercovered_user_sample: list[str] = []
    undercoverage_reasons = {
        "missing_train_sequence": len(missing_users),
        "no_co_visit_seed_metadata": 0,
        "no_metadata_neighbor_candidate": 0,
        "below_target_candidate_count": 0,
    }
    with source_candidates_path.open("w", encoding="utf-8") as candidate_handle:
        for processed_count, user_id in enumerate(target_users, start=1):
            sequence = sequences.get(user_id)
            metadata_candidates = metadata_neighbor_candidates_for_user(sequence or {"user_id": user_id}, metadata_index, generation_config) if sequence else []
            transition_limit = candidate_per_user * max(1, underfill_repair_per_seed_multiplier) if underfill_repair_enabled else candidate_per_user
            transition_candidates = _transition_candidates_for_user(sequence or {"user_id": user_id}, transition_index, metadata_index, seed_window, transition_limit) if sequence else []
            candidates = _merge_repair_candidates(metadata_candidates, transition_candidates, candidate_per_user)
            if underfill_repair_enabled and len(candidates) < candidate_per_user and sequence:
                candidates = _underfill_repair_candidates(
                    candidates,
                    metadata_candidates,
                    transition_candidates,
                    {str(item_id) for item_id in sequence.get("recent_item_sequence", []) if item_id},
                    candidate_per_user,
                )
            seed_items = _recent_unique(sequence.get("recent_positive_item_sequence", []) if sequence else [], seed_window)
            co_visit_seed_count = sum(1 for item_id in seed_items if item_id in metadata_index)
            transition_seed_count = sum(1 for item_id in seed_items if item_id in transition_index)
            user_row_count = 0
            for rank, candidate in enumerate(candidates, start=1):
                metadata = dict(candidate.metadata)
                metadata["canonical_source"] = SOURCE
                metadata["source_status"] = SOURCE_STATUS
                row = {
                    "user_id": user_id,
                    "item_id": candidate.item_id,
                    "source": SOURCE,
                    "sources": [SOURCE],
                    "score": candidate.score,
                    "rank": rank,
                    "metadata": metadata,
                }
                candidate_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                candidate_row_count += 1
                user_row_count += 1
                unique_item_ids.add(candidate.item_id)
            user_audit = {
                "seed_item_count": len(seed_items),
                "co_visit_seed_count": co_visit_seed_count,
                "co_visit_seed_covered": co_visit_seed_count > 0,
                "metadata_neighbor_candidate_count": len(metadata_candidates),
                "metadata_neighbor_covered": len(metadata_candidates) > 0,
                "sequence_transition_seed_count": transition_seed_count,
                "sequence_transition_candidate_count": len(transition_candidates),
                "sequence_transition_covered": len(transition_candidates) > 0,
                "repair_candidate_count": user_row_count,
            }
            if include_full_per_user_audit:
                per_user[user_id] = user_audit
            elif len(per_user_sample) < per_user_sample_limit:
                per_user_sample[user_id] = user_audit
            candidate_counts.append(user_row_count)
            if co_visit_seed_count > 0:
                seed_covered_users += 1
            else:
                undercoverage_reasons["no_co_visit_seed_metadata"] += 1
            if metadata_candidates:
                metadata_covered_users += 1
            else:
                undercoverage_reasons["no_metadata_neighbor_candidate"] += 1
            if transition_candidates:
                transition_covered_users += 1
            if user_row_count > 0:
                user_coverage_count += 1
            if user_row_count < candidate_per_user:
                undercovered_user_count += 1
                if len(undercovered_user_sample) < 20:
                    undercovered_user_sample.append(user_id)
                if user_row_count > 0:
                    undercoverage_reasons["below_target_candidate_count"] += 1
            if checkpoint_every_users > 0 and processed_count % checkpoint_every_users == 0:
                write_json(checkpoint_dir / f"processed_{processed_count:04d}.json", {"processed_user_count": processed_count, "candidate_row_count": candidate_row_count, "shard_contract": shard_contract})

    stats = _count_stats(candidate_counts)
    unique_items = len(unique_item_ids)
    input_paths = [clean_manifest_path, lightweight_views_manifest_path, eligible_user_manifest_path, train_sequences_path, train_interactions_path, semantic_inputs_path]
    forbidden_inputs = [str(path) for path in input_paths if _is_forbidden_path(path)]

    required_paths = {name: str(output_dir / name) for name in REQUIRED_SOURCE_OUTPUTS}
    source_index_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.source_index_manifest",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "status": SOURCE_STATUS,
        "source_status": SOURCE_STATUS,
        "index_status": "TARGET_SLICE_INDEX_READY",
        "index_scope": "TARGET_SLICE_DERIVED_INDEX",
        "formal_shard_mode": shard_contract["formal_shard_mode"],
        "target_user_offset": target_user_offset,
        "target_user_limit": target_user_limit,
        "shard_id": shard_id,
        "shard_count": shard_count,
        "full_eligible_user_count": len(all_target_users),
        "shard_contract": shard_contract,
        "train_only": True,
        "metadata_index_path": str(semantic_inputs_path),
        "train_interactions_path": str(train_interactions_path),
        "sequence_transition_index_mode": "train_only_seed_triggered_time_window",
        "candidates_path": str(source_candidates_path),
        "candidate_row_count": candidate_row_count,
        "user_coverage_count": user_coverage_count,
        "unique_item_count": unique_items,
        "generation_config_overrides": {},
        "required_artifacts": required_paths,
        "batch_scoped_evidence_only": True,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "algorithm_scope": ALGORITHM_SCOPE,
        "complete_co_visit_graph_claimed": False,
        "transition_gates": {
            "pair_support_gate": min_pair_support,
            "distinct_user_support_gate": min_distinct_user_support,
            "popularity_normalization_alpha": transition_popularity_norm_alpha,
        },
    }
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "source": SOURCE,
        "source_status": SOURCE_STATUS,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "created_at": datetime.now(UTC).isoformat(),
        "target_user_count": len(target_users),
        "full_eligible_user_count": len(all_target_users),
        "target_user_offset": target_user_offset,
        "target_user_limit": target_user_limit,
        "shard_id": shard_id,
        "shard_count": shard_count,
        "formal_shard_mode": shard_contract["formal_shard_mode"],
        "shard_contract": shard_contract,
        "loaded_target_user_count": len(sequences),
        "missing_target_user_count": len(missing_users),
        "metadata_index_row_count": len(metadata_index),
        "sequence_transition_scan": transition_scan_audit,
        "co_visit_seed_coverage": _coverage(seed_covered_users, len(target_users)),
        "metadata_neighbor_coverage": _coverage(metadata_covered_users, len(target_users)),
        "sequence_transition_coverage": _coverage(transition_covered_users, len(target_users)),
        "candidate_row_count": candidate_row_count,
        "user_coverage_count": user_coverage_count,
        "candidate_count_stats": stats,
        "declared_inputs": [str(path) for path in input_paths],
        "train_only": True,
        "batch_scoped_evidence_only": True,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "algorithm_scope": ALGORITHM_SCOPE,
        "complete_co_visit_graph_claimed": False,
        "transition_gates": {
            "pair_support_gate": min_pair_support,
            "distinct_user_support_gate": min_distinct_user_support,
            "popularity_normalization_alpha": transition_popularity_norm_alpha,
        },
    }
    coverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS" if user_coverage_count else "EMPTY",
        "source": SOURCE,
        "co_visit_seed_coverage": _coverage(seed_covered_users, len(target_users)),
        "metadata_neighbor_coverage": _coverage(metadata_covered_users, len(target_users)),
        "sequence_transition_coverage": _coverage(transition_covered_users, len(target_users)),
        "repair_candidate_count": candidate_row_count,
        "user_coverage_count": user_coverage_count,
        "candidate_row_count": candidate_row_count,
        "unique_item_count": unique_items,
        "candidate_count_stats": stats,
        "per_user": per_user if include_full_per_user_audit else {},
        "per_user_sample": per_user_sample,
        "per_user_audit_truncated": not include_full_per_user_audit,
        "per_user_audit_sample_limit": per_user_sample_limit,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    undercoverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "DIAGNOSTIC_UNDERCOVERAGE_REMAINS" if undercovered_user_count else "PASS",
        "source": SOURCE,
        "target_per_user": candidate_per_user,
        "undercovered_user_count": undercovered_user_count,
        "undercovered_user_sample": undercovered_user_sample,
        "primary_reasons": undercoverage_reasons,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    seed_metadata_row_count = sum(1 for item_id in target_seed_items if item_id in metadata_index)
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "mode": "target_slice_diagnostic",
        "heavy_job": False,
        "batch_size": checkpoint_every_users,
        "checkpoint_enabled": True,
        "checkpoint_dir": str(checkpoint_dir),
        "checkpoint_count": len(list(checkpoint_dir.glob("*.json"))),
        "streaming_candidates_enabled": True,
        "full_per_user_audit_included": include_full_per_user_audit,
        "per_user_audit_sample_limit": per_user_sample_limit,
        "max_candidate_metadata_rows": max_metadata_rows,
        "seed_metadata_row_count": seed_metadata_row_count,
        "metadata_index_row_count": len(metadata_index),
        "sequence_transition_scan": transition_scan_audit,
        "target_user_count": len(target_users),
        "full_eligible_user_count": len(all_target_users),
        "target_user_offset": target_user_offset,
        "target_user_limit": target_user_limit,
        "shard_id": shard_id,
        "shard_count": shard_count,
        "formal_shard_mode": shard_contract["formal_shard_mode"],
        "shard_contract": shard_contract,
        "disk_free_bytes_end": shutil.disk_usage(output_dir).free,
        "batch_scoped_evidence_only": True,
        "full_run_claimed": False,
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    no_holdout_audit = {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS" if not forbidden_inputs else "BLOCKED",
        "source": SOURCE,
        "declared_inputs": [str(path) for path in input_paths],
        "forbidden_inputs": forbidden_inputs,
        "forbidden_tokens": list(FORBIDDEN_TOKENS),
        "train_only": not forbidden_inputs,
        "candidate_generation_uses_holdout": bool(forbidden_inputs),
        "candidate_generation_read_files": [str(path) for path in input_paths],
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    if no_holdout_audit["status"] != "PASS":
        write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
        raise ValueError(f"forbidden input path detected for co_visit_fallback_repair source: {forbidden_inputs}")

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    source_index_manifest["manifest_sha256"] = _sha256_json(source_index_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def build_co_visit_transition_graph_index(
    *,
    clean_manifest_path: Path | None = None,
    lightweight_views_manifest_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
    tier: str | None = None,
    seed_window: int | None = None,
    transition_window: int | None = None,
    transition_per_seed: int | None = None,
    shard_count: int | None = None,
    max_src_items: int | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    config = _effective_config(config_path, tier, {
        "run_id": run_id,
        "output_root": str(output_root) if output_root is not None else None,
        "input_contract": {
            "clean_manifest": str(clean_manifest_path) if clean_manifest_path is not None else None,
            "lightweight_views_manifest": str(lightweight_views_manifest_path) if lightweight_views_manifest_path is not None else None,
        },
        "method_config": {
            "seed_window": seed_window,
            "transition_window": transition_window,
            "transition_per_seed": transition_per_seed,
            "shard_count": shard_count,
            "max_src_items": max_src_items,
        },
    })
    input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    clean_manifest_path = _config_path(input_contract, "data/processed/amazon_2023_recall_clean_full/manifest.json", "clean_manifest", "clean_manifest_path")
    lightweight_views_manifest_path = _config_path(input_contract, "data/processed/amazon_2023_recall_views_full_lightweight/manifest.json", "lightweight_views_manifest", "lightweight_views_manifest_path")
    output_root = _config_path(config, "outputs/recall/pool500_method_sources", "output_root")
    run_id = str(config.get("run_id") or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    transition_window = int(method_config.get("transition_window", 5))
    transition_per_seed = int(method_config.get("transition_per_seed", 200))
    transition_decay = str(method_config.get("transition_decay", "reciprocal"))
    transition_popularity_norm_alpha = float(method_config.get("transition_popularity_norm_alpha", 0.0))
    min_pair_support = int(method_config.get("min_pair_support", 1))
    min_distinct_user_support = int(method_config.get("min_distinct_user_support", 1))
    shard_count = int(method_config.get("shard_count", 64))
    max_src_items_value = method_config.get("max_src_items")
    max_src_items = int(max_src_items_value) if max_src_items_value is not None else None
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if max_src_items is not None and max_src_items <= 0:
        raise ValueError("max_src_items must be positive when provided")

    output_root = output_root if output_root.is_absolute() else _resolve_repo_path(output_root)
    output_dir = output_root / run_id if output_root.name == SOURCE else method_output_dir(output_root, SOURCE, run_id)
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(lightweight_views_manifest_path)
    train_interactions_path = _resolve_train_interactions_path(clean_manifest)
    train_sequences_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    semantic_inputs_path = _resolve_repo_path(views_manifest["outputs"]["semantic_recall_inputs"])
    input_paths = [clean_manifest_path, lightweight_views_manifest_path, train_sequences_path, train_interactions_path, semantic_inputs_path]
    forbidden_inputs = [str(path) for path in input_paths if _is_forbidden_path(path)]
    no_holdout_audit = {
        "schema_version": f"{TRANSITION_GRAPH_SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS" if not forbidden_inputs else "BLOCKED",
        "source": SOURCE,
        "declared_inputs": [str(path) for path in input_paths],
        "forbidden_inputs": forbidden_inputs,
        "forbidden_tokens": list(FORBIDDEN_TOKENS),
        "train_only": not forbidden_inputs,
        "candidate_generation_uses_holdout": bool(forbidden_inputs),
        "candidate_generation_allowed": False,
        "serving_candidate_source_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    if no_holdout_audit["status"] != "PASS":
        write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
        raise ValueError(f"forbidden input path detected for co_visit_fallback_repair transition graph: {forbidden_inputs}")

    transition_index, transition_scan_audit = _load_train_transition_index(
        train_interactions_path,
        None,
        transition_window,
        transition_per_seed,
        transition_decay=transition_decay,
        popularity_norm_alpha=transition_popularity_norm_alpha,
        min_pair_support=min_pair_support,
        min_distinct_user_support=min_distinct_user_support,
        max_src_items=max_src_items,
    )
    edge_shards, edge_shard_stats = _write_transition_graph_edge_shards(output_dir, transition_index, shard_count)
    edge_count = sum(int(stat["edge_count"]) for stat in edge_shard_stats)
    transition_graph_stats = {
        "schema_version": f"{TRANSITION_GRAPH_SCHEMA_VERSION}.transition_graph_stats",
        "status": "PASS" if edge_count else "EMPTY",
        "source": SOURCE,
        "src_item_count": len(transition_index),
        "edge_count": edge_count,
        "shard_count": shard_count,
        "max_src_items": max_src_items,
        "transition_scan": transition_scan_audit,
        "edge_shard_stats": edge_shard_stats,
        "candidate_materialization": "none",
        "underfill_repair_allowed": True,
        "candidate_generation_allowed": False,
        "serving_candidate_source_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    resource_audit = {
        "schema_version": f"{TRANSITION_GRAPH_SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "mode": "transition_graph",
        "heavy_job": max_src_items is None,
        "candidate_materialization": "none",
        "streaming_candidates_enabled": False,
        "per_user_candidates_written": False,
        "shard_count": shard_count,
        "max_src_items": max_src_items,
        "transition_scan": transition_scan_audit,
        "edge_count": edge_count,
        "src_item_count": len(transition_index),
        "disk_free_bytes_end": shutil.disk_usage(output_dir).free,
        "candidate_generation_allowed": False,
        "serving_candidate_source_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    source_index_manifest = {
        "schema_version": f"{TRANSITION_GRAPH_SCHEMA_VERSION}.source_index_manifest",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "status": "PASS" if edge_count else "EMPTY",
        "source_status": TRANSITION_GRAPH_SOURCE_STATUS,
        "index_status": "INDEX_READY" if edge_count else "EMPTY_INDEX",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_materialization": "none",
        "complete_co_visit_graph_claimed": max_src_items is None,
        "sequence_transition_index_mode": "train_only_full_item_transition_graph",
        "algorithm_scope": ALGORITHM_SCOPE,
        "shard_key": "src_item_sha256_mod",
        "shard_count": shard_count,
        "max_src_items": max_src_items,
        "outputs": {
            "edges_shards": edge_shards,
            "edge_shard_stats": edge_shard_stats,
            "transition_graph_stats": "transition_graph_stats.json",
            "resource_audit": "resource_audit.json",
            "no_holdout_audit": "no_holdout_audit.json",
        },
        "parameters": {
            "transition_window": transition_window,
            "transition_per_seed": transition_per_seed,
            "transition_decay": transition_decay,
            "transition_popularity_norm_alpha": transition_popularity_norm_alpha,
            "min_pair_support": min_pair_support,
            "min_distinct_user_support": min_distinct_user_support,
        },
        "input_contract": {
            "allowed_inputs": [
                "clean_manifest.split_paths.train",
                "clean_manifest.train_user_sequences_path",
                "lightweight_views_manifest.outputs.semantic_recall_inputs",
            ],
            "declared_inputs": [str(path) for path in input_paths],
        },
        "underfill_repair_allowed": True,
        "candidate_generation_allowed": False,
        "serving_candidate_source_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "public_payload_allowed": False,
        "diagnostic_only": False,
    }
    write_json(output_dir / "transition_graph_stats.json", transition_graph_stats)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    source_index_manifest["manifest_sha256"] = _sha256_json(source_index_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _write_transition_graph_edge_shards(output_dir: Path, transition_index: dict[str, list[dict[str, Any]]], shard_count: int) -> tuple[list[str], list[dict[str, Any]]]:
    shard_names = [f"co_visit_transition_edges_shard_{index:03d}.jsonl" for index in range(shard_count)]
    handles = [(output_dir / name).open("w", encoding="utf-8") for name in shard_names]
    shard_stats = [
        {"shard_id": index, "path": shard_names[index], "src_item_count": 0, "edge_count": 0}
        for index in range(shard_count)
    ]
    try:
        for src_item in sorted(transition_index):
            shard_id = stable_itemcf_shard_id(src_item, shard_count)
            shard_stats[shard_id]["src_item_count"] += 1
            for rank, edge in enumerate(transition_index[src_item], start=1):
                dst_item = str(edge.get("item_id") or edge.get("dst_item") or "")
                if not dst_item:
                    continue
                row = {
                    "source": SOURCE,
                    "algorithm": ALGORITHM_SCOPE,
                    "src_item": src_item,
                    "dst_item": dst_item,
                    "rank": rank,
                    "score": float(edge.get("score", 0.0) or 0.0),
                    "raw_score": float(edge.get("raw_score", edge.get("score", 0.0)) or 0.0),
                    "pair_support": int(edge.get("pair_support", 0) or 0),
                    "distinct_user_support": int(edge.get("distinct_user_support", 0) or 0),
                    "candidate_popularity": int(edge.get("candidate_popularity", 0) or 0),
                    "normalized_score": float(edge.get("normalized_score", edge.get("score", 0.0)) or 0.0),
                }
                handles[shard_id].write(json.dumps(row, ensure_ascii=False) + "\n")
                shard_stats[shard_id]["edge_count"] += 1
    finally:
        for handle in handles:
            handle.close()
    return shard_names, shard_stats



def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build pool500 co_visit_fallback_repair method source artifacts.")
    parser.add_argument("--mode", choices=("target_slice_diagnostic", "transition_graph"), default="target_slice_diagnostic")
    parser.add_argument("--clean-manifest", type=Path, default=None)
    parser.add_argument("--lightweight-views-manifest", type=Path, default=None)
    parser.add_argument("--eligible-user-manifest", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--tier", default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-metadata-rows", type=int, default=None)
    parser.add_argument("--candidate-per-user", type=int, default=None)
    parser.add_argument("--candidate-per-seed", type=int, default=None)
    parser.add_argument("--seed-window", type=int, default=None)
    parser.add_argument("--transition-window", type=int, default=None)
    parser.add_argument("--transition-per-seed", type=int, default=None)
    parser.add_argument("--checkpoint-every-users", type=int, default=None)
    parser.add_argument("--target-user-offset", type=int, default=None)
    parser.add_argument("--target-user-limit", type=int, default=None)
    parser.add_argument("--shard-id", type=int, default=None)
    parser.add_argument("--shard-count", type=int, default=None)
    parser.add_argument("--max-src-items", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.mode == "transition_graph":
        manifest = build_co_visit_transition_graph_index(
            clean_manifest_path=args.clean_manifest,
            lightweight_views_manifest_path=args.lightweight_views_manifest,
            output_root=args.output_root,
            run_id=args.run_id,
            config_path=args.config,
            tier=args.tier,
            seed_window=args.seed_window,
            transition_window=args.transition_window,
            transition_per_seed=args.transition_per_seed,
            shard_count=args.shard_count,
            max_src_items=args.max_src_items,
            overwrite=args.overwrite,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    manifest = build_co_visit_fallback_repair_source(
        clean_manifest_path=args.clean_manifest,
        lightweight_views_manifest_path=args.lightweight_views_manifest,
        eligible_user_manifest_path=args.eligible_user_manifest,
        output_root=args.output_root,
        run_id=args.run_id,
        config_path=args.config,
        tier=args.tier,
        max_metadata_rows=args.max_metadata_rows,
        candidate_per_user=args.candidate_per_user,
        candidate_per_seed=args.candidate_per_seed,
        seed_window=args.seed_window,
        transition_window=args.transition_window,
        transition_per_seed=args.transition_per_seed,
        checkpoint_every_users=args.checkpoint_every_users,
        target_user_offset=args.target_user_offset,
        target_user_limit=args.target_user_limit,
        shard_id=args.shard_id,
        shard_count=args.shard_count,
        overwrite=args.overwrite,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _effective_config(config_path: Path | None, tier: str | None, cli_overrides: dict[str, Any]) -> dict[str, Any]:
    raw_config = _load_yaml((config_path or DEFAULT_CONFIG_PATH).resolve() if (config_path or DEFAULT_CONFIG_PATH).is_absolute() else ROOT / (config_path or DEFAULT_CONFIG_PATH))
    selected_tier = _resolve_tier(raw_config, tier)
    config = {key: deepcopy(value) for key, value in raw_config.items() if key not in CONFIG_STRUCTURAL_KEYS}
    defaults = raw_config.get("defaults") if isinstance(raw_config.get("defaults"), dict) else {}
    tiers = raw_config.get("tiers") if isinstance(raw_config.get("tiers"), dict) else {}
    tier_config: dict[str, Any] = {}
    if selected_tier is not None:
        if selected_tier not in tiers:
            raise ValueError(f"unknown tier: {selected_tier}; available tiers: {', '.join(sorted(str(key) for key in tiers))}")
        selected = tiers[selected_tier]
        if not isinstance(selected, dict):
            raise ValueError(f"tier config must be a mapping: {selected_tier}")
        tier_config = selected
    return _deep_merge(config, defaults, tier_config, _drop_none(cli_overrides))


def _resolve_tier(config: dict[str, Any], tier: str | None) -> str | None:
    if tier is None:
        return None
    aliases = config.get("tier_aliases") if isinstance(config.get("tier_aliases"), dict) else {}
    return str(aliases.get(tier, tier))


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: cleaned for key, child in value.items() if (cleaned := _drop_none(child)) is not None}
    return value


def _deep_merge(*configs: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for config in configs:
        for key, value in config.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
    return merged


def _config_path(config: dict[str, Any], default: str | Path, *keys: str) -> Path:
    for key in keys:
        value = config.get(key)
        if value:
            return _resolve_repo_path(value)
    return _resolve_repo_path(default)


def _validate_shard_contract(target_user_offset: int, target_user_limit: int | None, shard_id: int | None, shard_count: int | None) -> None:
    if target_user_offset < 0:
        raise ValueError("target_user_offset must be >= 0")
    if target_user_limit is not None and target_user_limit <= 0:
        raise ValueError("target_user_limit must be positive when provided")
    if shard_id is None and shard_count is None:
        return
    if shard_id is None or shard_count is None:
        raise ValueError("shard_id and shard_count must be provided together")
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if shard_id < 0 or shard_id >= shard_count:
        raise ValueError("shard_id must be >= 0 and < shard_count")


def _shard_contract(
    *,
    full_eligible_user_count: int,
    selected_target_user_count: int,
    target_user_offset: int,
    target_user_limit: int | None,
    shard_id: int | None,
    shard_count: int | None,
    checkpoint_every_users: int,
) -> dict[str, Any]:
    return {
        "full_eligible_user_count": full_eligible_user_count,
        "selected_target_user_count": selected_target_user_count,
        "target_user_offset": target_user_offset,
        "target_user_limit": target_user_limit,
        "shard_id": shard_id,
        "shard_count": shard_count,
        "formal_shard_mode": target_user_offset > 0 or target_user_limit is not None or shard_id is not None or shard_count is not None,
        "checkpoint_enabled": checkpoint_every_users > 0,
        "checkpoint_every_users": checkpoint_every_users,
    }


def _resolve_repo_path(path: str | Path) -> Path:
    raw_path = str(path).replace("\\", "/")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate



def _resolve_train_interactions_path(clean_manifest: dict[str, Any]) -> Path:
    split_paths = clean_manifest.get("split_paths") if isinstance(clean_manifest.get("split_paths"), dict) else {}
    value = split_paths.get("train") or clean_manifest.get("train_interactions_path")
    if not value:
        return _resolve_repo_path(Path(clean_manifest["train_user_sequences_path"]).parent / "canonical_interactions.train.jsonl")
    return _resolve_repo_path(value)


def _load_target_sequences(path: Path, target_users: list[str]) -> dict[str, dict[str, Any]]:
    remaining = set(target_users)
    sequences: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        if user_id in remaining:
            sequences[user_id] = row
            remaining.remove(user_id)
            if not remaining:
                break
    return sequences


def _load_metadata_index(path: Path, sequences: dict[str, dict[str, Any]], max_rows: int, seed_window: int) -> dict[str, dict[str, Any]]:
    seed_items = {item_id for sequence in sequences.values() for item_id in _recent_unique(sequence.get("recent_positive_item_sequence", []), seed_window)}
    seed_records: dict[str, dict[str, Any]] = {}
    seed_tokens: set[str] = set()
    seed_categories: set[str] = set()
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if item_id not in seed_items:
            continue
        record = dict(row)
        seed_records[item_id] = record
        seed_tokens.update(_tokens(record))
        seed_categories.update(_categories(record))
    candidate_records: dict[str, dict[str, Any]] = {}
    if seed_tokens or seed_categories:
        for row in iter_jsonl(path):
            if len(candidate_records) >= max_rows:
                break
            item_id = str(row.get("parent_asin") or row.get("item_id") or "")
            if not item_id or item_id in seed_records:
                continue
            record = dict(row)
            if _tokens(record) & seed_tokens or _categories(record) & seed_categories:
                candidate_records[item_id] = record
    return {**candidate_records, **seed_records}


def _load_train_transition_index(
    path: Path,
    seed_items: set[str] | None,
    transition_window: int,
    transition_per_seed: int,
    *,
    transition_decay: str = "reciprocal",
    popularity_norm_alpha: float = 0.0,
    min_pair_support: int = 1,
    min_distinct_user_support: int = 1,
    max_src_items: int | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if transition_decay not in {"linear", "reciprocal", "exponential"}:
        raise ValueError(f"unsupported transition_decay: {transition_decay}")
    seed_filter_enabled = seed_items is not None
    if (seed_filter_enabled and not seed_items) or transition_window <= 0 or transition_per_seed <= 0:
        return {}, {
            "status": "SKIPPED",
            "train_interactions_path": str(path),
            "seed_item_count": len(seed_items or set()),
            "seed_filter_enabled": seed_filter_enabled,
            "max_src_items": max_src_items,
            "transition_window": transition_window,
            "transition_per_seed": transition_per_seed,
            "transition_decay": transition_decay,
            "transition_popularity_norm_alpha": popularity_norm_alpha,
            "min_pair_support": min_pair_support,
            "min_distinct_user_support": min_distinct_user_support,
        }
    weighted_scores: dict[str, Counter[str]] = defaultdict(Counter)
    pair_support: dict[str, Counter[str]] = defaultdict(Counter)
    pair_users: dict[tuple[str, str], set[str]] = defaultdict(set)
    candidate_popularity: Counter[str] = Counter()
    active: dict[str, list[tuple[str, int]]] = defaultdict(list)
    discovered_src_items: set[str] = set()
    scanned_row_count = 0
    seed_event_count = 0
    transition_event_count = 0
    filtered_pair_support_count = 0
    filtered_distinct_user_support_count = 0
    for row in iter_jsonl(path):
        scanned_row_count += 1
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not user_id or not item_id:
            continue
        if _positive_interaction(row):
            candidate_popularity[item_id] += 1
        active_events = active.get(user_id)
        if active_events:
            retained_events = []
            for seed_item, distance in active_events:
                if item_id != seed_item and _positive_interaction(row):
                    weighted_scores[seed_item][item_id] += _transition_distance_weight(distance, transition_window, transition_decay)
                    pair_support[seed_item][item_id] += 1
                    pair_users[(seed_item, item_id)].add(user_id)
                    transition_event_count += 1
                if distance < transition_window:
                    retained_events.append((seed_item, distance + 1))
            if retained_events:
                active[user_id] = retained_events
            else:
                active.pop(user_id, None)
        is_positive = _positive_interaction(row)
        is_seed_item = item_id in seed_items if seed_filter_enabled else True
        if is_seed_item and is_positive:
            if max_src_items is not None and item_id not in discovered_src_items and len(discovered_src_items) >= max_src_items:
                continue
            discovered_src_items.add(item_id)
            active[user_id].append((item_id, 1))
            seed_event_count += 1
    transition_index: dict[str, list[dict[str, Any]]] = {}
    for seed_item, counter in weighted_scores.items():
        rows: list[dict[str, Any]] = []
        for item_id, raw_score in counter.items():
            support = int(pair_support[seed_item][item_id])
            distinct_users = len(pair_users[(seed_item, item_id)])
            if support < min_pair_support:
                filtered_pair_support_count += 1
                continue
            if distinct_users < min_distinct_user_support:
                filtered_distinct_user_support_count += 1
                continue
            popularity = int(candidate_popularity[item_id])
            normalized_score = float(raw_score) / ((1.0 + popularity) ** popularity_norm_alpha)
            rows.append({
                "item_id": item_id,
                "score": normalized_score,
                "raw_score": float(raw_score),
                "pair_support": support,
                "distinct_user_support": distinct_users,
                "candidate_popularity": popularity,
                "normalized_score": normalized_score,
            })
        rows.sort(key=lambda item: (-float(item["score"]), str(item["item_id"])))
        if rows:
            transition_index[seed_item] = rows[:transition_per_seed]
    return transition_index, {
        "status": "PASS",
        "train_interactions_path": str(path),
        "seed_item_count": len(seed_items or discovered_src_items),
        "seed_filter_enabled": seed_filter_enabled,
        "max_src_items": max_src_items,
        "seed_with_transition_count": len(transition_index),
        "scanned_row_count": scanned_row_count,
        "seed_event_count": seed_event_count,
        "transition_event_count": transition_event_count,
        "raw_pair_count": sum(len(counter) for counter in weighted_scores.values()),
        "filtered_pair_support_count": filtered_pair_support_count,
        "filtered_distinct_user_support_count": filtered_distinct_user_support_count,
        "transition_window": transition_window,
        "transition_per_seed": transition_per_seed,
        "transition_decay": transition_decay,
        "transition_popularity_norm_alpha": popularity_norm_alpha,
        "min_pair_support": min_pair_support,
        "min_distinct_user_support": min_distinct_user_support,
    }



def _transition_distance_weight(distance: int, transition_window: int, decay: str) -> float:
    if decay == "linear":
        return float(max(0, transition_window + 1 - distance))
    if decay == "exponential":
        return 0.5 ** max(0, distance - 1)
    return 1.0 / max(1, distance)



def _positive_interaction(row: dict[str, Any]) -> bool:
    if "label_binary" in row:
        return int(row.get("label_binary") or 0) == 1
    return float(row.get("rating") or 0.0) >= 3.0



def _transition_candidates_for_user(
    sequence: dict[str, Any],
    transition_index: dict[str, list[dict[str, Any]]],
    metadata_index: dict[str, dict[str, Any]],
    seed_window: int,
    limit: int,
) -> list[Any]:
    seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", []) if item_id}
    seed_items = _recent_unique(sequence.get("recent_positive_item_sequence", []), seed_window)
    by_item: dict[str, Any] = {}
    for seed_rank, seed_item in enumerate(seed_items, start=1):
        recency_weight = 1.0 / math.sqrt(seed_rank)
        for source_rank, transition in enumerate(transition_index.get(seed_item, []), start=1):
            item_id = str(transition.get("item_id") or "")
            if not item_id or item_id in seen_items:
                continue
            record = metadata_index.get(item_id, {})
            source_score = float(transition.get("score", 0.0))
            score = source_score * recency_weight
            metadata = {
                "reason": "train_interaction_sequence_transition",
                "seed_item_id": seed_item,
                "source_rank": source_rank,
                "sequence_transition_seed_rank": seed_rank,
                "sequence_transition_score": float(transition.get("raw_score", source_score)),
                "sequence_transition_support": int(transition.get("pair_support", 0)),
                "sequence_transition_distinct_user_support": int(transition.get("distinct_user_support", 0)),
                "sequence_transition_candidate_popularity": int(transition.get("candidate_popularity", 0)),
                "sequence_transition_normalized_score": source_score,
                "sequence_transition_recency_weighted_score": score,
                "sequence_transition_index_mode": "train_only_seed_triggered_time_window",
            }
            if record:
                metadata.update({k: v for k, v in record.items() if k not in {"semantic_tokens", "two_tower_tokens"}})
            candidate = _candidate(item_id, score, str(record.get("main_category") or record.get("category") or ""), metadata)
            current = by_item.get(item_id)
            if current is None or candidate.score > current.score:
                by_item[item_id] = candidate
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]



def _candidate(item_id: str, score: float, category: str, metadata: dict[str, Any]) -> Any:
    from rs_core.common.recsys_types import RecallCandidate

    return RecallCandidate(item_id=item_id, source=SOURCE, score=score, category=category, metadata=metadata)



def _merge_repair_candidates(metadata_candidates: list[Any], transition_candidates: list[Any], limit: int) -> list[Any]:
    by_item = {candidate.item_id: candidate for candidate in metadata_candidates}
    for candidate in transition_candidates:
        current = by_item.get(candidate.item_id)
        if current is None or candidate.score > current.score:
            by_item[candidate.item_id] = candidate
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:limit]



def _underfill_repair_candidates(
    merged_candidates: list[Any],
    metadata_candidates: list[Any],
    transition_candidates: list[Any],
    seen_items: set[str],
    limit: int,
) -> list[Any]:
    selected = {candidate.item_id for candidate in merged_candidates}
    repaired = list(merged_candidates)
    refill_pool = [
        candidate
        for candidate in [*metadata_candidates, *transition_candidates]
        if candidate.item_id not in selected and candidate.item_id not in seen_items
    ]
    refill_pool.sort(key=lambda item: (-item.score, item.item_id))
    for candidate in refill_pool:
        repaired.append(candidate)
        selected.add(candidate.item_id)
        if len(repaired) >= limit:
            break
    repaired.sort(key=lambda item: (-item.score, item.item_id))
    return repaired[:limit]



def _recent_unique(values: Any, window: int) -> list[str]:
    if not isinstance(values, list):
        return []
    unique: list[str] = []
    for value in reversed(values[-window:]):
        item_id = str(value)
        if item_id and item_id not in unique:
            unique.append(item_id)
    return unique


def _tokens(row: dict[str, Any]) -> set[str]:
    text_parts: list[str] = []
    for field in ("title_clean", "main_category", "category", "description_text", "features_text", "item_text", "categories_flat"):
        value = row.get(field)
        if isinstance(value, list):
            text_parts.extend(str(item) for item in value)
        elif value is not None:
            text_parts.append(str(value))
    return {token for token in re.findall(r"[a-z0-9]+", " ".join(text_parts).lower()) if len(token) >= 3}


def _categories(row: dict[str, Any]) -> set[str]:
    values = [row.get("main_category"), row.get("category")]
    raw = row.get("categories_flat")
    if isinstance(raw, list):
        values.extend(raw)
    return {str(value).lower() for value in values if value}


def _coverage(count: int, total: int) -> dict[str, Any]:
    return {"count": count, "total": total, "ratio": round(count / total, 6) if total else 0.0}


def _count_stats(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p50": _percentile(ordered, 0.5),
        "p90": _percentile(ordered, 0.9),
        "max": ordered[-1],
        "avg": round(sum(ordered) / len(ordered), 6),
    }


def _percentile(ordered: list[int], percentile: float) -> int:
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _is_forbidden_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    filename = path.name.lower()
    for token in FORBIDDEN_TOKENS:
        if token in {"holdout", "valid", "test"}:
            if token in parts or filename.endswith(f".{token}.jsonl"):
                return True
            continue
        if any(token in part for part in parts):
            return True
    return False


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()
