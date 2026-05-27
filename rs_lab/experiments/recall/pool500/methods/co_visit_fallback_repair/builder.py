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

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.recsys.candidate_merge import metadata_neighbor_candidates_for_user
from rs_lab.experiments.recall.pool500.common.source_layout import FORBIDDEN_EVIDENCE_SCOPES, REQUIRED_SOURCE_OUTPUTS, method_output_dir

SOURCE = "co_visit_fallback_repair"
SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
SCHEMA_VERSION = "pool500_co_visit_fallback_repair_v1"
ALGORITHM_SCOPE = "train_transition_metadata_repair_v0"
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
    target_users = [str(user_id) for user_id in eligible_manifest.get("eligible_user_ids", [])]
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
    }

    rows: list[dict[str, Any]] = []
    per_user: dict[str, dict[str, Any]] = {}
    source_candidates_path = output_dir / "candidates.jsonl"
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir()
    target_user_set = set(target_users)
    missing_users = sorted(target_user_set - set(sequences))
    for processed_count, user_id in enumerate(target_users, start=1):
        sequence = sequences.get(user_id)
        metadata_candidates = metadata_neighbor_candidates_for_user(sequence or {"user_id": user_id}, metadata_index, generation_config) if sequence else []
        transition_candidates = _transition_candidates_for_user(sequence or {"user_id": user_id}, transition_index, metadata_index, seed_window, candidate_per_user) if sequence else []
        candidates = _merge_repair_candidates(metadata_candidates, transition_candidates, candidate_per_user)
        seed_items = _recent_unique(sequence.get("recent_positive_item_sequence", []) if sequence else [], seed_window)
        co_visit_seed_count = sum(1 for item_id in seed_items if item_id in metadata_index)
        transition_seed_count = sum(1 for item_id in seed_items if item_id in transition_index)
        user_rows = []
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
            rows.append(row)
            user_rows.append(row)
        per_user[user_id] = {
            "seed_item_count": len(seed_items),
            "co_visit_seed_count": co_visit_seed_count,
            "co_visit_seed_covered": co_visit_seed_count > 0,
            "metadata_neighbor_candidate_count": len(metadata_candidates),
            "metadata_neighbor_covered": len(metadata_candidates) > 0,
            "sequence_transition_seed_count": transition_seed_count,
            "sequence_transition_candidate_count": len(transition_candidates),
            "sequence_transition_covered": len(transition_candidates) > 0,
            "repair_candidate_count": len(user_rows),
        }
        if checkpoint_every_users > 0 and processed_count % checkpoint_every_users == 0:
            write_json(checkpoint_dir / f"processed_{processed_count:04d}.json", {"processed_user_count": processed_count, "candidate_row_count": len(rows)})

    write_jsonl(source_candidates_path, rows)
    candidate_counts = [per_user[user_id]["repair_candidate_count"] for user_id in target_users]
    stats = _count_stats(candidate_counts)
    seed_covered_users = sum(1 for item in per_user.values() if item["co_visit_seed_covered"])
    metadata_covered_users = sum(1 for item in per_user.values() if item["metadata_neighbor_covered"])
    transition_covered_users = sum(1 for item in per_user.values() if item["sequence_transition_covered"])
    user_coverage_count = sum(1 for count in candidate_counts if count > 0)
    unique_items = len({row["item_id"] for row in rows})
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
        "train_only": True,
        "metadata_index_path": str(semantic_inputs_path),
        "train_interactions_path": str(train_interactions_path),
        "sequence_transition_index_mode": "train_only_seed_triggered_time_window",
        "candidates_path": str(source_candidates_path),
        "candidate_row_count": len(rows),
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
        "follow_up_metrics": {
            "pair_support": "follow_up_only_not_gate",
            "distinct_user_support": "follow_up_only_not_gate",
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
        "loaded_target_user_count": len(sequences),
        "missing_target_user_count": len(missing_users),
        "metadata_index_row_count": len(metadata_index),
        "sequence_transition_scan": transition_scan_audit,
        "co_visit_seed_coverage": _coverage(seed_covered_users, len(target_users)),
        "metadata_neighbor_coverage": _coverage(metadata_covered_users, len(target_users)),
        "sequence_transition_coverage": _coverage(transition_covered_users, len(target_users)),
        "candidate_row_count": len(rows),
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
        "follow_up_metrics": {
            "pair_support": "follow_up_only_not_gate",
            "distinct_user_support": "follow_up_only_not_gate",
        },
    }
    coverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS" if user_coverage_count else "EMPTY",
        "source": SOURCE,
        "co_visit_seed_coverage": _coverage(seed_covered_users, len(target_users)),
        "metadata_neighbor_coverage": _coverage(metadata_covered_users, len(target_users)),
        "sequence_transition_coverage": _coverage(transition_covered_users, len(target_users)),
        "repair_candidate_count": len(rows),
        "user_coverage_count": user_coverage_count,
        "candidate_row_count": len(rows),
        "unique_item_count": unique_items,
        "candidate_count_stats": stats,
        "per_user": per_user,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    undercovered_users = [user_id for user_id in target_users if per_user[user_id]["repair_candidate_count"] < candidate_per_user]
    undercoverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "DIAGNOSTIC_UNDERCOVERAGE_REMAINS" if undercovered_users else "PASS",
        "source": SOURCE,
        "target_per_user": candidate_per_user,
        "undercovered_user_count": len(undercovered_users),
        "undercovered_user_sample": undercovered_users[:20],
        "primary_reasons": _undercoverage_reasons(per_user, target_users, missing_users, candidate_per_user),
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
        "max_candidate_metadata_rows": max_metadata_rows,
        "seed_metadata_row_count": seed_metadata_row_count,
        "metadata_index_row_count": len(metadata_index),
        "sequence_transition_scan": transition_scan_audit,
        "target_user_count": len(target_users),
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
        "train_only": True,
        "candidate_generation_uses_holdout": False,
        "candidate_generation_read_files": [str(path) for path in input_paths],
        "candidate_generation_allowed": False,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    source_index_manifest["manifest_sha256"] = _sha256_json(source_index_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build pool500 co_visit_fallback_repair method source artifacts.")
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
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
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


def _resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
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


def _load_train_transition_index(path: Path, seed_items: set[str], transition_window: int, transition_per_seed: int) -> tuple[dict[str, list[tuple[str, float]]], dict[str, Any]]:
    if not seed_items or transition_window <= 0 or transition_per_seed <= 0:
        return {}, {
            "status": "SKIPPED",
            "train_interactions_path": str(path),
            "seed_item_count": len(seed_items),
            "transition_window": transition_window,
            "transition_per_seed": transition_per_seed,
        }
    counters: dict[str, Counter[str]] = {item_id: Counter() for item_id in seed_items}
    active: dict[str, list[tuple[str, int]]] = defaultdict(list)
    scanned_row_count = 0
    seed_event_count = 0
    transition_event_count = 0
    for row in iter_jsonl(path):
        scanned_row_count += 1
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not user_id or not item_id:
            continue
        active_events = active.get(user_id)
        if active_events:
            retained_events = []
            for seed_item, distance in active_events:
                if item_id != seed_item:
                    counters[seed_item][item_id] += transition_window + 1 - distance
                    transition_event_count += 1
                if distance < transition_window:
                    retained_events.append((seed_item, distance + 1))
            if retained_events:
                active[user_id] = retained_events
            else:
                active.pop(user_id, None)
        if item_id in seed_items and _positive_interaction(row):
            active[user_id].append((item_id, 1))
            seed_event_count += 1
    transition_index = {
        seed_item: [(item_id, float(score)) for item_id, score in counter.most_common(transition_per_seed)]
        for seed_item, counter in counters.items()
        if counter
    }
    return transition_index, {
        "status": "PASS",
        "train_interactions_path": str(path),
        "seed_item_count": len(seed_items),
        "seed_with_transition_count": len(transition_index),
        "scanned_row_count": scanned_row_count,
        "seed_event_count": seed_event_count,
        "transition_event_count": transition_event_count,
        "transition_window": transition_window,
        "transition_per_seed": transition_per_seed,
    }



def _positive_interaction(row: dict[str, Any]) -> bool:
    if "label_binary" in row:
        return int(row.get("label_binary") or 0) == 1
    return float(row.get("rating") or 0.0) >= 3.0



def _transition_candidates_for_user(
    sequence: dict[str, Any],
    transition_index: dict[str, list[tuple[str, float]]],
    metadata_index: dict[str, dict[str, Any]],
    seed_window: int,
    limit: int,
) -> list[Any]:
    seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", []) if item_id}
    seed_items = _recent_unique(sequence.get("recent_positive_item_sequence", []), seed_window)
    by_item: dict[str, Any] = {}
    for seed_rank, seed_item in enumerate(seed_items, start=1):
        recency_weight = 1.0 / math.sqrt(seed_rank)
        for source_rank, (item_id, source_score) in enumerate(transition_index.get(seed_item, []), start=1):
            if item_id in seen_items:
                continue
            record = metadata_index.get(item_id, {})
            score = float(source_score) * recency_weight
            metadata = {
                "reason": "train_interaction_sequence_transition",
                "seed_item_id": seed_item,
                "source_rank": source_rank,
                "sequence_transition_seed_rank": seed_rank,
                "sequence_transition_score": float(source_score),
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
    from rs_core.recsys.types import RecallCandidate

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


def _undercoverage_reasons(per_user: dict[str, dict[str, Any]], target_users: list[str], missing_users: list[str], target_count: int) -> dict[str, int]:
    return {
        "missing_train_sequence": len(missing_users),
        "no_co_visit_seed_metadata": sum(1 for user_id in target_users if per_user[user_id]["co_visit_seed_count"] == 0),
        "no_metadata_neighbor_candidate": sum(1 for user_id in target_users if per_user[user_id]["metadata_neighbor_candidate_count"] == 0),
        "below_target_candidate_count": sum(1 for user_id in target_users if 0 < per_user[user_id]["repair_candidate_count"] < target_count),
    }


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
