from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
import shutil
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

import yaml

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.recsys.candidate_merge import semantic_title_category_expansion_candidates_for_user
from rs_lab.experiments.recall.pool500.common.source_layout import FORBIDDEN_EVIDENCE_SCOPES, method_output_dir

ROOT = Path(__file__).resolve().parents[6]
SOURCE = "semantic_title_category_expansion"
SCHEMA_VERSION = "pool500_semantic_title_category_expansion_source_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"
DEFAULT_ELIGIBLE_USER_MANIFEST = ROOT / "outputs" / "recall" / "pool500_main_route_direct_recall_full_promoted" / "eligible_user_manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources"
DEFAULT_CONFIG_PATH = ROOT / "configs" / "recall" / "full_data_pool500" / SOURCE / "source_config.yaml"
DEFAULT_SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
CONFIG_STRUCTURAL_KEYS = {"defaults", "tiers", "tier_aliases"}
FORBIDDEN_SPLIT_PARTS = {"valid", "test", "lopo"}
FORBIDDEN_PATH_SUBSTRINGS = tuple(token.lower() for token in FORBIDDEN_EVIDENCE_SCOPES if token.lower() not in FORBIDDEN_SPLIT_PARTS)
TEXT_FIELDS = ("title_clean", "main_category", "categories_flat")
FULL_METADATA_OVERLAP_TEXT_FIELDS = ("title_clean", "main_category", "category", "categories_flat", "description_text", "features_text", "item_text", "store", "brand")
FULL_METADATA_OVERLAP_STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "your", "you", "are", "black", "white", "edition", "products", "product", "amazon", "into", "full", "size", "made", "great", "compatible", "replacement", "case"
}
SELECTION_MODE_TITLE_CATEGORY_SCORER = "title_category_scorer"
SELECTION_MODE_TITLE_CATEGORY_CHANNEL = "semantic_title_category_channel"
SELECTION_MODE_FULL_METADATA_OVERLAP = "full_metadata_overlap"


def build_semantic_title_category_expansion_source(
    *,
    clean_manifest_path: Path | None = None,
    lightweight_views_manifest_path: Path | None = None,
    eligible_user_manifest_path: Path | None = None,
    output_root: Path | None = None,
    run_id: str | None = None,
    config_path: Path | None = None,
    tier: str | None = None,
    limit_users: int | None = None,
    seed_window: int | None = None,
    per_user: int | None = None,
    per_seed: int | None = None,
    per_token_item_limit: int | None = None,
    max_candidate_items: int | None = None,
    selection_mode: str | None = None,
    checkpoint_every_users: int | None = None,
    target_user_offset: int | None = None,
    target_user_limit: int | None = None,
    shard_id: int | None = None,
    shard_count: int | None = None,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    config = _effective_config(config_path, tier, {
        "run_id": run_id,
        "output_root": str(output_root) if output_root is not None else None,
        "input_contract": {
            "clean_manifest": str(clean_manifest_path) if clean_manifest_path is not None else None,
            "lightweight_views_manifest": str(lightweight_views_manifest_path) if lightweight_views_manifest_path is not None else None,
            "eligible_user_manifest": str(eligible_user_manifest_path) if eligible_user_manifest_path is not None else None,
        },
        "method_config": {
            "limit_users": limit_users,
            "seed_window": seed_window,
            "per_user": per_user,
            "per_seed": per_seed,
            "per_token_item_limit": per_token_item_limit,
            "max_candidate_items": max_candidate_items,
            "selection_mode": selection_mode,
            "checkpoint_every_users": checkpoint_every_users,
            "target_user_offset": target_user_offset,
            "target_user_limit": target_user_limit,
            "shard_id": shard_id,
            "shard_count": shard_count,
        },
    })
    input_contract = config.get("input_contract") if isinstance(config.get("input_contract"), dict) else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    clean_manifest_path = _config_path(input_contract, DEFAULT_CLEAN_MANIFEST, "clean_manifest", "clean_manifest_path")
    lightweight_views_manifest_path = _config_path(input_contract, DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST, "lightweight_views_manifest", "lightweight_views_manifest_path")
    eligible_user_manifest_path = _config_path(input_contract, DEFAULT_ELIGIBLE_USER_MANIFEST, "eligible_user_manifest", "eligible_user_manifest_path")
    output_root = _resolve_repo_path(config.get("output_root") or DEFAULT_OUTPUT_ROOT)
    run_id = str(config.get("run_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    limit_users = int(method_config.get("limit_users", 500))
    seed_window = int(method_config.get("seed_window", 20))
    per_user = int(method_config.get("per_user", 80))
    per_seed = int(method_config.get("per_seed", 40))
    per_token_item_limit = int(method_config.get("per_token_item_limit", 2000))
    max_candidate_items = int(method_config.get("max_candidate_items", 80000))
    selection_mode = str(method_config.get("selection_mode") or SELECTION_MODE_TITLE_CATEGORY_SCORER)
    checkpoint_every_users = int(method_config.get("checkpoint_every_users", 0) or 0)
    target_user_offset = int(method_config.get("target_user_offset", 0) or 0)
    target_user_limit_value = method_config.get("target_user_limit")
    target_user_limit = int(target_user_limit_value) if target_user_limit_value is not None else None
    shard_id_value = method_config.get("shard_id")
    shard_count_value = method_config.get("shard_count")
    shard_id = int(shard_id_value) if shard_id_value is not None else None
    shard_count = int(shard_count_value) if shard_count_value is not None else None
    _validate_shard_contract(target_user_offset, target_user_limit, shard_id, shard_count)
    if selection_mode == SELECTION_MODE_TITLE_CATEGORY_CHANNEL:
        selection_mode = SELECTION_MODE_TITLE_CATEGORY_SCORER
    if selection_mode not in {SELECTION_MODE_TITLE_CATEGORY_SCORER, SELECTION_MODE_FULL_METADATA_OVERLAP}:
        raise ValueError(f"unsupported semantic selection mode: {selection_mode}")
    output_dir = method_output_dir(output_root.resolve(), SOURCE, run_id)
    if output_dir.exists() and any(output_dir.iterdir()) and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    clean_manifest_path = clean_manifest_path.resolve()
    lightweight_views_manifest_path = lightweight_views_manifest_path.resolve()
    clean_manifest = read_json(clean_manifest_path)
    views_manifest = read_json(lightweight_views_manifest_path)
    train_sequences_path = _resolve_repo_path(clean_manifest["train_user_sequences_path"])
    canonical_items_path = _resolve_repo_path(clean_manifest["canonical_items_path"])
    view_outputs = views_manifest.get("outputs") if isinstance(views_manifest.get("outputs"), dict) else {}
    semantic_inputs_path = _resolve_repo_path(view_outputs["semantic_recall_inputs"])
    semantic_inverted_index_path = _resolve_repo_path(view_outputs["semantic_inverted_index"])

    all_target_user_ids = _eligible_user_ids(eligible_user_manifest_path)
    target_user_ids = _select_target_user_ids(
        all_target_user_ids,
        limit_users,
        target_user_offset=target_user_offset,
        target_user_limit=target_user_limit,
        shard_id=shard_id,
        shard_count=shard_count,
    )
    sequences = _load_target_sequences(train_sequences_path, target_user_ids, limit_users)
    checkpoint_path = output_dir / "checkpoint.json"
    shard_contract = _shard_contract(
        full_eligible_user_count=len(all_target_user_ids) if all_target_user_ids is not None else None,
        selected_target_user_count=len(target_user_ids) if target_user_ids is not None else len(sequences),
        limit_users=limit_users,
        target_user_offset=target_user_offset,
        target_user_limit=target_user_limit,
        shard_id=shard_id,
        shard_count=shard_count,
        checkpoint_every_users=checkpoint_every_users,
    )
    write_json(checkpoint_path, {"stage": "target_sequences_loaded", "user_count": len(sequences), "source": SOURCE, "shard_contract": shard_contract})

    seed_items_by_user = _seed_items_by_user(sequences, seed_window)
    seed_items = {item for items in seed_items_by_user.values() for item in items}
    seed_records = _load_records_by_ids(semantic_inputs_path, seed_items)
    seed_tokens = _record_tokens(seed_records.values())
    if selection_mode == SELECTION_MODE_FULL_METADATA_OVERLAP:
        rows, candidate_item_ids, token_bucket_stats = _full_metadata_overlap_candidate_rows(
            semantic_inputs_path,
            sequences,
            seed_items_by_user,
            seed_records,
            per_user=per_user,
        )
    else:
        candidate_item_ids, token_candidate_ids, token_bucket_stats = _candidate_ids_from_inverted_index(
            semantic_inverted_index_path,
            seed_tokens,
            per_token_item_limit=per_token_item_limit,
            max_candidate_items=max_candidate_items,
        )
        candidate_records = _load_records_by_ids(semantic_inputs_path, candidate_item_ids | seed_items)
        semantic_index = {item_id: _with_semantic_tokens(record) for item_id, record in candidate_records.items()}
        write_json(checkpoint_path, {
            "stage": "semantic_index_loaded",
            "user_count": len(sequences),
            "seed_item_count": len(seed_items),
            "seed_metadata_count": len(seed_records),
            "candidate_item_id_count": len(candidate_item_ids),
            "semantic_index_record_count": len(semantic_index),
            "selection_mode": selection_mode,
            "source": SOURCE,
        })
        generation_config = {
            "semantic_title_category_expansion": {
                "enabled": True,
                "per_user": per_user,
                "per_seed": per_seed,
                "seed_window": seed_window,
                "min_title_overlap": 1,
                "category_weight": 2.0,
                "weak_category_boost": 0.5,
                "weak_categories": ["All Electronics", "Office Products", "Computers"],
                "text_fields": list(TEXT_FIELDS),
                "require_category_overlap": True,
                "max_bucket_candidates": max_candidate_items,
                "token_candidate_ids": token_candidate_ids,
            }
        }
        rows = _title_category_scorer_candidate_rows(sequences, seed_items_by_user, seed_records, semantic_index, generation_config, per_user)
    if selection_mode == SELECTION_MODE_FULL_METADATA_OVERLAP:
        candidate_records = _load_records_by_ids(semantic_inputs_path, candidate_item_ids | seed_items)
        semantic_index = {item_id: _with_semantic_tokens(record) for item_id, record in candidate_records.items()}
    write_json(checkpoint_path, {
        "stage": "semantic_index_loaded",
        "user_count": len(sequences),
        "seed_item_count": len(seed_items),
        "seed_metadata_count": len(seed_records),
        "candidate_item_id_count": len(candidate_item_ids),
        "semantic_index_record_count": len(semantic_index),
        "selection_mode": selection_mode,
        "source": SOURCE,
        "shard_contract": shard_contract,
    })

    input_dataset_path = output_dir / "semantic_title_category_input_dataset.jsonl"
    write_jsonl(input_dataset_path, _input_dataset_rows(semantic_index))
    per_user_counts = Counter(str(row.get("user_id") or "") for row in rows)
    undercovered_reasons = _undercovered_reasons(sequences, seed_items_by_user, seed_records, per_user_counts, per_user, selection_mode)
    user_seed_metadata_hits = {
        str(sequence.get("user_id") or ""): sum(1 for item in seed_items_by_user.get(str(sequence.get("user_id") or ""), []) if item in seed_records)
        for sequence in sequences
    }
    candidates_path = output_dir / "candidates.jsonl"
    write_jsonl(candidates_path, rows)

    signatures = {
        "clean_manifest": _file_signature(clean_manifest_path),
        "lightweight_views_manifest": _file_signature(lightweight_views_manifest_path),
        "train_user_sequences": _file_signature(train_sequences_path),
        "canonical_items": _file_signature(canonical_items_path),
        "semantic_recall_inputs": _file_signature(semantic_inputs_path),
        "semantic_inverted_index": _file_signature(semantic_inverted_index_path),
        "semantic_title_category_input_dataset": _file_signature(input_dataset_path),
        "candidates": _file_signature(candidates_path),
    }
    declared_paths = [
        clean_manifest_path,
        lightweight_views_manifest_path,
        train_sequences_path,
        canonical_items_path,
        semantic_inputs_path,
        semantic_inverted_index_path,
    ]
    no_holdout_audit = _no_holdout_audit(declared_paths)
    counts = [per_user_counts.get(str(sequence.get("user_id", "")), 0) for sequence in sequences]
    coverage_audit = _coverage_audit(
        sequences=sequences,
        semantic_index=semantic_index,
        seed_items=seed_items,
        seed_records=seed_records,
        user_seed_metadata_hits=user_seed_metadata_hits,
        rows=rows,
        per_user_counts=counts,
        token_bucket_stats=token_bucket_stats,
    )
    undercoverage_audit = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "source_status": DEFAULT_SOURCE_STATUS,
        "undercovered_user_count": sum(1 for count in counts if count < per_user),
        "empty_user_count": sum(1 for count in counts if count == 0),
        "method_target_per_user": per_user,
        "reason_counts": dict(sorted(undercovered_reasons.items())),
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "source_status": DEFAULT_SOURCE_STATUS,
        "heavy_job": False,
        "checkpoint_enabled": True,
        "checkpoint_path": str(checkpoint_path),
        "batching": {
            "limit_users": limit_users,
            "seed_window": seed_window,
            "per_token_item_limit": per_token_item_limit,
            "max_candidate_items": max_candidate_items,
            "selection_mode": selection_mode,
            "checkpoint_every_users": checkpoint_every_users,
            "target_user_offset": target_user_offset,
            "target_user_limit": target_user_limit,
            "shard_id": shard_id,
            "shard_count": shard_count,
        },
        "shard_contract": shard_contract,
        "runtime_seconds": round(perf_counter() - started, 6),
        "source_signatures": signatures,
    }
    method_dataset_manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": DEFAULT_SOURCE_STATUS,
        "dataset_name": "semantic_title_category_input_dataset",
        "selection_mode": selection_mode,
        "train_only": True,
        "target_user_count": len(sequences),
        "full_eligible_user_count": shard_contract["full_eligible_user_count"],
        "target_user_offset": target_user_offset,
        "target_user_limit": target_user_limit,
        "shard_id": shard_id,
        "shard_count": shard_count,
        "formal_shard_mode": shard_contract["formal_shard_mode"],
        "shard_contract": shard_contract,
        "seed_item_count": len(seed_items),
        "seed_item_metadata_count": len(seed_records),
        "semantic_index_record_count": len(semantic_index),
        "input_dataset_path": str(input_dataset_path),
        "declared_input_paths": [str(path) for path in declared_paths],
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
    }
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": DEFAULT_SOURCE_STATUS,
        "status": DEFAULT_SOURCE_STATUS,
        "run_id": run_id,
        "selection_mode": selection_mode,
        "output_dir": str(output_dir),
        "method_dataset_manifest_path": str(output_dir / "method_dataset_manifest.json"),
        "semantic_title_category_input_dataset_path": str(input_dataset_path),
        "source_index_manifest_path": str(output_dir / "source_index_manifest.json"),
        "candidates_path": str(candidates_path),
        "candidate_row_count": len(rows),
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "candidate_count_min": coverage_audit["candidate_count_min"],
        "candidate_count_p50": coverage_audit["candidate_count_p50"],
        "candidate_count_p90": coverage_audit["candidate_count_p90"],
        "candidate_count_max": coverage_audit["candidate_count_max"],
        "full_eligible_user_count": shard_contract["full_eligible_user_count"],
        "target_user_offset": target_user_offset,
        "target_user_limit": target_user_limit,
        "shard_id": shard_id,
        "shard_count": shard_count,
        "formal_shard_mode": shard_contract["formal_shard_mode"],
        "shard_contract": shard_contract,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "full_pool500_ready_declared": False,
        "full_ready_declared": False,
        "source_signatures": signatures,
    }
    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    return source_index_manifest


def _resolve_repo_path(raw_path: str | Path) -> Path:
    normalized = str(raw_path).replace("\\", "/")
    repo_marker = f"/{ROOT.name}/"
    if repo_marker in normalized:
        normalized = normalized.split(repo_marker, 1)[1]
    path = Path(normalized)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _config_path(config: dict[str, Any], default: Path, *keys: str) -> Path:
    for key in keys:
        value = config.get(key)
        if value:
            return _resolve_repo_path(str(value))
    return default.resolve()


def _effective_config(config_path: Path | None, tier: str | None, cli_overrides: dict[str, Any]) -> dict[str, Any]:
    raw_config = _load_source_config(config_path)
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


def _load_source_config(config_path: Path | None) -> dict[str, Any]:
    path = config_path or DEFAULT_CONFIG_PATH
    path = path if path.is_absolute() else ROOT / path
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


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


def _eligible_user_ids(path: Path | None) -> list[str] | None:
    if path is None or not path.is_file():
        return None
    payload = read_json(path)
    user_ids = payload.get("eligible_user_ids")
    if not isinstance(user_ids, list):
        return None
    return [str(user_id) for user_id in user_ids if user_id]


def _select_target_user_ids(
    user_ids: list[str] | None,
    limit_users: int,
    *,
    target_user_offset: int,
    target_user_limit: int | None,
    shard_id: int | None,
    shard_count: int | None,
) -> set[str] | None:
    if user_ids is None:
        return None
    selected = user_ids[target_user_offset:]
    if target_user_limit is not None:
        selected = selected[:target_user_limit]
    elif limit_users > 0:
        selected = selected[:limit_users]
    if shard_id is not None and shard_count is not None:
        selected = [user_id for index, user_id in enumerate(selected) if index % shard_count == shard_id]
    return set(selected)


def _target_user_ids(path: Path | None, limit_users: int) -> set[str] | None:
    return _select_target_user_ids(
        _eligible_user_ids(path),
        limit_users,
        target_user_offset=0,
        target_user_limit=None,
        shard_id=None,
        shard_count=None,
    )


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
    full_eligible_user_count: int | None,
    selected_target_user_count: int,
    limit_users: int,
    target_user_offset: int,
    target_user_limit: int | None,
    shard_id: int | None,
    shard_count: int | None,
    checkpoint_every_users: int,
) -> dict[str, Any]:
    return {
        "full_eligible_user_count": full_eligible_user_count,
        "selected_target_user_count": selected_target_user_count,
        "limit_users": limit_users,
        "target_user_offset": target_user_offset,
        "target_user_limit": target_user_limit,
        "shard_id": shard_id,
        "shard_count": shard_count,
        "formal_shard_mode": target_user_offset > 0 or target_user_limit is not None or shard_id is not None or shard_count is not None,
        "checkpoint_enabled": checkpoint_every_users > 0,
        "checkpoint_every_users": checkpoint_every_users,
    }


def _load_target_sequences(path: Path, target_user_ids: set[str] | None, limit_users: int) -> list[dict[str, Any]]:
    sequences: list[dict[str, Any]] = []
    if target_user_ids is not None:
        remaining = set(target_user_ids)
        for sequence in iter_jsonl(path):
            user_id = str(sequence.get("user_id", ""))
            if user_id in remaining:
                sequences.append(sequence)
                remaining.remove(user_id)
                if not remaining:
                    break
        return sequences
    for sequence in iter_jsonl(path):
        if not sequence.get("user_id"):
            continue
        sequences.append(sequence)
        if limit_users > 0 and len(sequences) >= limit_users:
            break
    return sequences


def _seed_items_by_user(sequences: Iterable[dict[str, Any]], seed_window: int) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        positives = sequence.get("recent_positive_item_sequence", [])
        if not isinstance(positives, list):
            result[user_id] = []
            continue
        result[user_id] = list(dict.fromkeys(str(item) for item in reversed(positives[-seed_window:]) if item))
    return result


def _load_records_by_ids(path: Path, item_ids: set[str]) -> dict[str, dict[str, Any]]:
    if not item_ids:
        return {}
    remaining = set(item_ids)
    records: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if item_id in remaining:
            records[item_id] = dict(row)
            remaining.remove(item_id)
            if not remaining:
                break
    return records


def _title_category_scorer_candidate_rows(
    sequences: list[dict[str, Any]],
    seed_items_by_user: dict[str, list[str]],
    seed_records: dict[str, dict[str, Any]],
    semantic_index: dict[str, dict[str, Any]],
    generation_config: dict[str, Any],
    per_user: int,
) -> list[dict[str, Any]]:
    source_config = generation_config.get("semantic_title_category_expansion", {})
    if not isinstance(source_config, dict):
        return []
    per_seed = int(source_config.get("per_seed", 40))
    min_title_overlap = int(source_config.get("min_title_overlap", 1))
    category_weight = float(source_config.get("category_weight", 2.0))
    weak_category_boost = float(source_config.get("weak_category_boost", 0.5))
    weak_categories = {str(item).lower() for item in source_config.get("weak_categories", [])}
    require_category_overlap = bool(source_config.get("require_category_overlap", True))
    raw_token_candidate_ids = source_config.get("token_candidate_ids", {})
    token_candidate_ids = raw_token_candidate_ids if isinstance(raw_token_candidate_ids, dict) else {}

    item_tokens = {item_id: set(record.get("semantic_tokens", set())) for item_id, record in semantic_index.items()}
    item_categories = {item_id: _category_values(record) for item_id, record in semantic_index.items()}
    inverted_index: dict[str, set[str]] = {}
    for item_id, tokens in item_tokens.items():
        for token in tokens:
            inverted_index.setdefault(token, set()).add(item_id)

    rows: list[dict[str, Any]] = []
    progress_step = max(1, len(sequences) // 10)
    for sequence_index, sequence in enumerate(sequences, start=1):
        user_id = str(sequence.get("user_id", ""))
        seed_items = seed_items_by_user.get(user_id, [])
        seed_item_set = set(seed_items)
        user_tokens: set[str] = set()
        user_categories: set[str] = set()
        for seed_item in seed_items:
            user_tokens.update(item_tokens.get(seed_item, set()))
            user_categories.update(item_categories.get(seed_item, set()))
        if not user_tokens and not user_categories:
            continue
        seen_items = {str(item) for item in sequence.get("recent_item_sequence", []) or [] if item}
        by_item: dict[str, tuple[float, int, int, int, str, str, int]] = {}
        for seed_rank, seed_item in enumerate(seed_items, start=1):
            seed_tokens = item_tokens.get(seed_item, set())
            seed_categories = item_categories.get(seed_item, set())
            if not seed_tokens and not seed_categories:
                continue
            overlap_counts: Counter[str] = Counter()
            for token in seed_tokens:
                token_items = token_candidate_ids.get(token) or inverted_index.get(token, set())
                if not isinstance(token_items, set):
                    token_items = set(token_items)
                overlap_counts.update(token_items)
            seed_candidates: list[tuple[float, str, int, int, str, int]] = []
            for item_id, overlap in overlap_counts.items():
                if item_id in seed_item_set or item_id in seen_items or overlap < min_title_overlap:
                    continue
                candidate_categories = item_categories.get(item_id, set())
                category_overlap = len(seed_categories & candidate_categories)
                if not category_overlap and require_category_overlap:
                    continue
                boost = weak_category_boost if candidate_categories & weak_categories else 0.0
                reason = "weak_category_boost" if boost else "category_path" if category_overlap else "title_sim"
                score = round(float(overlap) + float(category_overlap) * category_weight + boost, 6)
                seed_candidates.append((score, item_id, overlap, category_overlap, reason, seed_rank))
            ranked_seed_candidates = heapq.nsmallest(per_seed, seed_candidates, key=lambda item: (-item[0], item[1]))
            for source_rank, (score, item_id, overlap, category_overlap, reason, seed_rank_value) in enumerate(ranked_seed_candidates, start=1):
                current = by_item.get(item_id)
                candidate = (score, overlap, category_overlap, seed_rank_value, reason, seed_item, source_rank)
                if current is None or candidate[0] > current[0] or (candidate[0] == current[0] and candidate[3] < current[3]):
                    by_item[item_id] = candidate
        ranked_user_items = heapq.nsmallest(per_user, by_item.items(), key=lambda item: (-item[1][0], item[0]))
        for rank, (item_id, (score, overlap, category_overlap, _seed_rank, reason, seed_item, source_rank)) in enumerate(ranked_user_items, start=1):
            record = semantic_index[item_id]
            metadata = {k: v for k, v in record.items() if k != "semantic_tokens"}
            metadata.update({
                "reason": reason,
                "seed_item_id": seed_item,
                "source_score": score,
                "source_rank": source_rank,
                "title_token_overlap": overlap,
                "category_overlap": category_overlap,
                "source_scores": {SOURCE: score},
            })
            rows.append({
                "user_id": user_id,
                "item_id": item_id,
                "source": SOURCE,
                "canonical_source": SOURCE,
                "sources": [SOURCE],
                "score": score,
                "rank": rank,
                "metadata": metadata,
            })
    return rows


def _full_metadata_overlap_candidate_rows(
    semantic_inputs_path: Path,
    sequences: list[dict[str, Any]],
    seed_items_by_user: dict[str, list[str]],
    seed_records: dict[str, dict[str, Any]],
    *,
    per_user: int,
    min_overlap: int = 2,
) -> tuple[list[dict[str, Any]], set[str], dict[str, Any]]:
    user_profiles = _full_metadata_user_profiles(sequences, seed_items_by_user, seed_records)
    heaps: dict[str, list[tuple[float, str, dict[str, Any]]]] = {user_id: [] for user_id in user_profiles}
    scanned_rows = 0
    candidate_rows_considered = 0
    for record in iter_jsonl(semantic_inputs_path):
        scanned_rows += 1
        item_id = str(record.get("parent_asin") or record.get("item_id") or "")
        if not item_id:
            continue
        candidate_tokens = _overlap_tokens(record)
        if not candidate_tokens:
            continue
        candidate_categories = _category_values(record)
        for user_id, profile in user_profiles.items():
            if item_id in profile["seen_items"]:
                continue
            overlap = len(candidate_tokens & profile["seed_tokens"])
            if overlap < min_overlap:
                continue
            category_overlap = len(candidate_categories & profile["seed_categories"])
            score = float(overlap) + float(category_overlap) * 8.0
            _push_bounded_candidate(
                heaps[user_id],
                per_user,
                score,
                item_id,
                {
                    "source_score": round(score, 6),
                    "selection_mode": SELECTION_MODE_FULL_METADATA_OVERLAP,
                    "title_token_overlap": overlap,
                    "category_overlap": category_overlap,
                    "semantic_overlap_min_overlap": min_overlap,
                    "category": record.get("main_category") or record.get("category") or "",
                },
            )
            candidate_rows_considered += 1
    rows: list[dict[str, Any]] = []
    candidate_item_ids: set[str] = set()
    for user_id, heap in heaps.items():
        ranked = sorted(heap, key=lambda item: (-item[0], item[1]))
        for rank, (score, item_id, metadata) in enumerate(ranked, start=1):
            candidate_item_ids.add(item_id)
            rows.append({
                "user_id": user_id,
                "item_id": item_id,
                "source": SOURCE,
                "canonical_source": SOURCE,
                "sources": [SOURCE],
                "score": round(score, 6),
                "rank": rank,
                "metadata": {**metadata, "source_scores": {SOURCE: round(score, 6)}},
            })
    return rows, candidate_item_ids, {
        "selection_mode": SELECTION_MODE_FULL_METADATA_OVERLAP,
        "scanned_semantic_input_rows": scanned_rows,
        "candidate_rows_considered": candidate_rows_considered,
        "target_user_count": len(user_profiles),
        "candidate_item_id_count": len(candidate_item_ids),
        "min_overlap": min_overlap,
    }


def _full_metadata_user_profiles(
    sequences: list[dict[str, Any]],
    seed_items_by_user: dict[str, list[str]],
    seed_records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for sequence in sequences:
        user_id = str(sequence.get("user_id") or "")
        if not user_id:
            continue
        seed_tokens: set[str] = set()
        seed_categories: set[str] = set()
        for seed_item in seed_items_by_user.get(user_id, []):
            record = seed_records.get(seed_item)
            if not record:
                continue
            seed_tokens.update(_overlap_tokens(record))
            seed_categories.update(_category_values(record))
        profiles[user_id] = {
            "seed_tokens": seed_tokens,
            "seed_categories": seed_categories,
            "seen_items": {str(item) for item in sequence.get("recent_item_sequence", []) or [] if item},
        }
    return profiles


def _push_bounded_candidate(heap: list[tuple[float, str, dict[str, Any]]], limit: int, score: float, item_id: str, metadata: dict[str, Any]) -> None:
    item = (score, item_id, metadata)
    if len(heap) < limit:
        heapq.heappush(heap, item)
        return
    if score > heap[0][0] or score == heap[0][0] and item_id < heap[0][1]:
        heapq.heapreplace(heap, item)


def _undercovered_reasons(
    sequences: list[dict[str, Any]],
    seed_items_by_user: dict[str, list[str]],
    seed_records: dict[str, dict[str, Any]],
    per_user_counts: Counter[str],
    per_user: int,
    selection_mode: str,
) -> Counter[str]:
    reasons: Counter[str] = Counter()
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        seed_items = seed_items_by_user.get(user_id, [])
        seed_hits = sum(1 for item in seed_items if item in seed_records)
        candidate_count = per_user_counts.get(user_id, 0)
        if not seed_items:
            reasons["no_positive_seed_items"] += 1
        elif seed_hits == 0:
            reasons["missing_seed_item_metadata"] += 1
        elif not candidate_count:
            reasons[f"no_{selection_mode}_candidates"] += 1
        elif candidate_count < per_user:
            reasons["below_method_target_per_user"] += 1
    return reasons


def _candidate_ids_from_inverted_index(
    path: Path,
    seed_tokens: set[str],
    *,
    per_token_item_limit: int,
    max_candidate_items: int,
) -> tuple[set[str], dict[str, set[str]], dict[str, Any]]:
    candidate_ids: set[str] = set()
    ordered_candidate_ids: list[str] = []
    token_candidate_ids: dict[str, set[str]] = {}
    matched_tokens = 0
    truncated_token_buckets = 0
    for row in iter_jsonl(path):
        token = str(row.get("token") or "").lower()
        if token not in seed_tokens:
            continue
        matched_tokens += 1
        raw_items = row.get("parent_asins") or row.get("item_ids") or []
        if not isinstance(raw_items, list):
            continue
        if len(raw_items) > per_token_item_limit:
            truncated_token_buckets += 1
        bucket_ids: set[str] = set()
        for raw_item_id in raw_items[:per_token_item_limit]:
            item_id = str(raw_item_id)
            bucket_ids.add(item_id)
            if item_id not in candidate_ids:
                candidate_ids.add(item_id)
                ordered_candidate_ids.append(item_id)
        token_candidate_ids[token] = bucket_ids
        if len(candidate_ids) >= max_candidate_items:
            retained_ids = set(ordered_candidate_ids[:max_candidate_items])
            token_candidate_ids = {key: values & retained_ids for key, values in token_candidate_ids.items()}
            return retained_ids, token_candidate_ids, {
                "seed_token_count": len(seed_tokens),
                "matched_token_count": matched_tokens,
                "truncated_token_bucket_count": truncated_token_buckets,
                "candidate_item_id_count": len(retained_ids),
                "max_candidate_items_reached": True,
            }
    return candidate_ids, token_candidate_ids, {
        "seed_token_count": len(seed_tokens),
        "matched_token_count": matched_tokens,
        "truncated_token_bucket_count": truncated_token_buckets,
        "candidate_item_id_count": len(candidate_ids),
        "max_candidate_items_reached": False,
    }


def _with_semantic_tokens(record: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(record)
    enriched["semantic_tokens"] = _title_tokens(record)
    return enriched


def _record_tokens(records: Iterable[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for record in records:
        tokens.update(_title_tokens(record))
    return tokens


def _tokens_from_fields(record: dict[str, Any], fields: Iterable[str]) -> set[str]:
    parts: list[str] = []
    for field in fields:
        value = record.get(field, "")
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        else:
            parts.append(str(value))
    return {token for token in re.findall(r"[a-z0-9]+", " ".join(parts).lower()) if len(token) >= 3}


def _overlap_tokens(record: dict[str, Any]) -> set[str]:
    return _tokens_from_fields(record, FULL_METADATA_OVERLAP_TEXT_FIELDS) - FULL_METADATA_OVERLAP_STOP_WORDS


def _category_values(record: dict[str, Any]) -> set[str]:
    values = {str(record.get("main_category") or ""), str(record.get("category") or "")}
    values.update(str(item) for item in record.get("categories_flat", []) or [])
    return {value.lower() for value in values if value}


def _title_tokens(record: dict[str, Any]) -> set[str]:
    return _tokens_from_fields(record, TEXT_FIELDS)


def _has_category(record: dict[str, Any]) -> bool:
    if record.get("main_category") or record.get("category"):
        return True
    categories = record.get("categories_flat")
    return isinstance(categories, list) and bool(categories)


def _input_dataset_rows(semantic_index: dict[str, dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for item_id, record in sorted(semantic_index.items()):
        yield {
            "item_id": item_id,
            "parent_asin": record.get("parent_asin", item_id),
            "title_clean": record.get("title_clean", ""),
            "main_category": record.get("main_category", ""),
            "category": record.get("category", ""),
            "categories_flat": record.get("categories_flat", []),
            "semantic_token_count": len(record.get("semantic_tokens", [])),
        }


def _coverage_audit(
    *,
    sequences: list[dict[str, Any]],
    semantic_index: dict[str, dict[str, Any]],
    seed_items: set[str],
    seed_records: dict[str, dict[str, Any]],
    user_seed_metadata_hits: dict[str, int],
    rows: list[dict[str, Any]],
    per_user_counts: list[int],
    token_bucket_stats: dict[str, Any],
) -> dict[str, Any]:
    record_count = len(semantic_index)
    title_hits = sum(1 for record in semantic_index.values() if str(record.get("title_clean") or "").strip())
    category_hits = sum(1 for record in semantic_index.values() if _has_category(record))
    clean_title_token_hits = sum(1 for record in semantic_index.values() if _title_tokens(record))
    seed_metadata_hits = len(seed_records)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "source_status": DEFAULT_SOURCE_STATUS,
        "target_user_count": len(sequences),
        "semantic_index_record_count": record_count,
        "title_coverage": _ratio(title_hits, record_count),
        "category_coverage": _ratio(category_hits, record_count),
        "clean_title_token_coverage": _ratio(clean_title_token_hits, record_count),
        "seed_item_count": len(seed_items),
        "seed_item_metadata_count": seed_metadata_hits,
        "seed_item_metadata_coverage": _ratio(seed_metadata_hits, len(seed_items)),
        "users_with_seed_metadata_count": sum(1 for count in user_seed_metadata_hits.values() if count > 0),
        "candidate_row_count": len(rows),
        "user_coverage_count": sum(1 for count in per_user_counts if count > 0),
        "candidate_count_min": min(per_user_counts) if per_user_counts else 0,
        "candidate_count_p50": _percentile(per_user_counts, 0.5),
        "candidate_count_p90": _percentile(per_user_counts, 0.9),
        "candidate_count_max": max(per_user_counts) if per_user_counts else 0,
        "token_bucket_stats": token_bucket_stats,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return ordered[index]


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            rows += chunk.count(b"\n")
    return {"path": str(path), "size_bytes": path.stat().st_size, "row_count": rows if path.suffix == ".jsonl" else None, "sha256": digest.hexdigest()}


def _no_holdout_audit(paths: list[Path]) -> dict[str, Any]:
    forbidden = [str(path) for path in paths if _is_forbidden_input_path(path)]
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "status": "PASS" if not forbidden else "BLOCKED",
        "train_only": not forbidden,
        "candidate_generation_uses_holdout": bool(forbidden),
        "forbidden_inputs": forbidden,
        "declared_inputs": [str(path) for path in paths],
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _is_forbidden_input_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    name = path.name.lower()
    if name in {"canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl", "user_sequences.valid.jsonl", "user_sequences.test.jsonl"}:
        return True
    if any(part in FORBIDDEN_SPLIT_PARTS for part in parts):
        return True
    return any(token in part for part in parts for token in FORBIDDEN_PATH_SUBSTRINGS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pool500 semantic title/category diagnostic method source.")
    parser.add_argument("--clean-manifest", type=Path, default=None)
    parser.add_argument("--lightweight-views-manifest", type=Path, default=None)
    parser.add_argument("--eligible-user-manifest", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--tier", default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit-users", type=int, default=None)
    parser.add_argument("--seed-window", type=int, default=None)
    parser.add_argument("--per-user", type=int, default=None)
    parser.add_argument("--per-seed", type=int, default=None)
    parser.add_argument("--per-token-item-limit", type=int, default=None)
    parser.add_argument("--max-candidate-items", type=int, default=None)
    parser.add_argument("--selection-mode", choices=[SELECTION_MODE_TITLE_CATEGORY_SCORER, SELECTION_MODE_TITLE_CATEGORY_CHANNEL, SELECTION_MODE_FULL_METADATA_OVERLAP], default=None)
    parser.add_argument("--checkpoint-every-users", type=int, default=None)
    parser.add_argument("--target-user-offset", type=int, default=None)
    parser.add_argument("--target-user-limit", type=int, default=None)
    parser.add_argument("--shard-id", type=int, default=None)
    parser.add_argument("--shard-count", type=int, default=None)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_semantic_title_category_expansion_source(
        clean_manifest_path=args.clean_manifest,
        lightweight_views_manifest_path=args.lightweight_views_manifest,
        eligible_user_manifest_path=args.eligible_user_manifest,
        output_root=args.output_root,
        run_id=args.run_id,
        config_path=args.config,
        tier=args.tier,
        limit_users=args.limit_users,
        seed_window=args.seed_window,
        per_user=args.per_user,
        per_seed=args.per_seed,
        per_token_item_limit=args.per_token_item_limit,
        max_candidate_items=args.max_candidate_items,
        selection_mode=args.selection_mode,
        checkpoint_every_users=args.checkpoint_every_users,
        target_user_offset=args.target_user_offset,
        target_user_limit=args.target_user_limit,
        shard_id=args.shard_id,
        shard_count=args.shard_count,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({
        "source": manifest["source"],
        "run_id": manifest["run_id"],
        "output_dir": manifest["output_dir"],
        "source_index_manifest_path": manifest["source_index_manifest_path"],
        "candidate_row_count": manifest["candidate_row_count"],
        "user_coverage_count": manifest["user_coverage_count"],
        "candidate_count_min": manifest["candidate_count_min"],
        "candidate_count_p50": manifest["candidate_count_p50"],
        "candidate_count_p90": manifest["candidate_count_p90"],
        "candidate_count_max": manifest["candidate_count_max"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
