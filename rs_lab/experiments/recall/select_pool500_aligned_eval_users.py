from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.workflow.full_data_pool500_route_gate import canonical_manifest_sha256, canonical_user_set_hash

SCHEMA_VERSION = "pool500_aligned_eval_user_selection_v1"
OFFLINE_SCHEMA_VERSION = "pool500_offline_eval_users_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_aligned_eval_users"
DEFAULT_OFFLINE_EVAL_OUTPUT_DIR = ROOT / "outputs" / "eval" / "pool500_offline_eval_users_10k"
DEFAULT_MAX_USERS = 500
DEFAULT_TOTAL_USERS = 10_000
DEFAULT_DRY_RUN_USERS = 100
DEFAULT_SEGMENT_RATIOS = {"hot": 0.4, "warm": 0.4, "cold-ish": 0.2}
DEFAULT_SEED = 20260521
DEFAULT_MIN_TRAIN_HISTORY = 1
DEFAULT_POSITIVE_SAMPLE_SIZE = 5
POSITIVE_FIELDS = ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased")
ALLOWED_LABEL_SPLITS = {"valid", "test"}
CATEGORY_FIELDS = ("category", "main_category")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select diagnostic-only valid/test users for aligned pool500 evaluation without using holdout labels as recall inputs.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--label", action="append", default=[], help="Explicit valid/test JSONL label input; repeat for valid and test. Defaults to clean_manifest.split_paths valid/test.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-users", type=int, default=DEFAULT_MAX_USERS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--min-train-history", type=int, default=DEFAULT_MIN_TRAIN_HISTORY)
    parser.add_argument("--positive-sample-size", type=int, default=DEFAULT_POSITIVE_SAMPLE_SIZE)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    parser.add_argument("--offline-eval-output", default=None, help="Write fixed pool500 offline eval users manifest.json/users.jsonl to this directory.")
    parser.add_argument("--total-users", type=int, default=DEFAULT_TOTAL_USERS)
    parser.add_argument("--dry-run", action="store_true", help="Build a proportional 100-user offline eval artifact unless --total-users is also provided.")
    parser.add_argument("--dry-run-users", type=int, default=DEFAULT_DRY_RUN_USERS)
    return parser.parse_args()


def select_pool500_aligned_eval_users(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    label_paths: Iterable[Path] | None = None,
    max_users: int = DEFAULT_MAX_USERS,
    seed: int = DEFAULT_SEED,
    min_train_history: int = DEFAULT_MIN_TRAIN_HISTORY,
    positive_sample_size: int = DEFAULT_POSITIVE_SAMPLE_SIZE,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    _validate_args(max_users, min_train_history, positive_sample_size)
    clean_manifest_path = clean_manifest_path.resolve()
    output_dir = output_dir.resolve()
    output_path = output_dir / "aligned_eval_users_manifest.json"
    _precheck_output(output_path, overwrite)

    clean_manifest = read_json(clean_manifest_path)
    train_sequences_path = _resolve_required_train_sequences_path(clean_manifest_path, clean_manifest)
    all_interactions_path = _resolve_optional_all_interactions_path(clean_manifest_path, clean_manifest)
    resolved_label_paths = _resolve_label_paths(clean_manifest_path, clean_manifest, label_paths)
    history_by_user = _load_train_history(train_sequences_path)
    all_interaction_counts = _load_all_interaction_counts(all_interactions_path) if all_interactions_path else {}
    label_summary, positive_by_split_user = _load_eval_positives(resolved_label_paths, positive_sample_size)

    selected_profiles, skipped_counts = _select_profiles(
        positive_by_split_user=positive_by_split_user,
        history_by_user=history_by_user,
        all_interaction_counts=all_interaction_counts,
        max_users=max_users,
        seed=seed,
        min_train_history=min_train_history,
    )
    target_user_ids = [profile["user_id"] for profile in selected_profiles]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if selected_profiles else "EMPTY_SELECTION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "diagnostic_only_valid_test_eval_user_selection",
        "policy_role": "eval_target_user_manifest_not_recall_source",
        "diagnostic_only": True,
        "eval_label_inputs_role": "evaluation_only_valid_test_labels_not_recall_generation_inputs",
        "train_history_role": "history_availability_filter_only",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "all_interactions_path": str(all_interactions_path) if all_interactions_path else None,
        "label_paths": [str(path) for path in resolved_label_paths],
        "selection_config": {
            "max_users": max_users,
            "seed": seed,
            "min_train_history": min_train_history,
            "positive_sample_size": positive_sample_size,
            "eligible_splits": sorted(ALLOWED_LABEL_SPLITS),
        },
        "summary": {
            "selected_user_count": len(selected_profiles),
            "selected_split_counts": dict(sorted(Counter(profile["split"] for profile in selected_profiles).items())),
            "candidate_eval_user_count": len({user_id for split_users in positive_by_split_user.values() for user_id in split_users}),
            "skipped_counts": dict(sorted(skipped_counts.items())),
            "label_summary": label_summary,
            "target_user_hash": canonical_user_set_hash(target_user_ids),
        },
        "target_user_ids": target_user_ids,
        "eligible_user_ids": target_user_ids,
        "profiles": selected_profiles,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_path, manifest)
    return manifest


def build_pool500_offline_eval_users(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_dir: Path = DEFAULT_OFFLINE_EVAL_OUTPUT_DIR,
    label_paths: Iterable[Path] | None = None,
    total_users: int = DEFAULT_TOTAL_USERS,
    seed: int = DEFAULT_SEED,
    min_train_history: int = DEFAULT_MIN_TRAIN_HISTORY,
    positive_sample_size: int = DEFAULT_POSITIVE_SAMPLE_SIZE,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    if enforce_venv:
        enforce_project_venv(ROOT)
    _validate_args(total_users, min_train_history, positive_sample_size)
    clean_manifest_path = clean_manifest_path.resolve()
    output_dir = output_dir.resolve()
    manifest_path = output_dir / "manifest.json"
    users_path = output_dir / "users.jsonl"
    _precheck_output(manifest_path, overwrite)
    _precheck_output(users_path, overwrite)

    clean_manifest = read_json(clean_manifest_path)
    train_sequences_path = _resolve_required_train_sequences_path(clean_manifest_path, clean_manifest)
    all_interactions_path = _resolve_optional_all_interactions_path(clean_manifest_path, clean_manifest)
    item_metadata_path = _resolve_optional_item_metadata_path(clean_manifest_path, clean_manifest)
    resolved_label_paths = _resolve_label_paths(clean_manifest_path, clean_manifest, label_paths)
    all_interaction_counts = _load_all_interaction_counts(all_interactions_path) if all_interactions_path else {}
    output_dir.mkdir(parents=True, exist_ok=True)
    label_db_path = output_dir / "_label_aggregate.tmp.sqlite"
    if label_db_path.exists():
        label_db_path.unlink()
    try:
        dry_run_label_user_limit = total_users * 100 if total_users <= DEFAULT_DRY_RUN_USERS else None
        label_summary = _build_eval_label_aggregate_db(resolved_label_paths, positive_sample_size, label_db_path, max_positive_users=dry_run_label_user_limit)
        eligible_candidates, skipped_counts = _build_offline_candidates_from_label_db(
            train_sequences_path=train_sequences_path,
            label_db_path=label_db_path,
            all_interaction_counts=all_interaction_counts,
            min_train_history=min_train_history,
        )
        segment_targets = _segment_targets(total_users)
        segmented_candidates, segment_thresholds = _segment_candidates(eligible_candidates)
        users, segment_warnings = _select_segmented_users(segmented_candidates, segment_targets, seed)
        users = _attach_user_diagnostics(users, item_metadata_path, train_sequences_path)
    finally:
        if label_db_path.exists():
            label_db_path.unlink()
    user_ids = [user["user_id"] for user in users]
    user_set_hash = canonical_user_set_hash(user_ids)
    source_manifest_hash = canonical_manifest_sha256(clean_manifest)
    status = "PASS" if len(users) == total_users and not segment_warnings else "PARTIAL_SEGMENT_SHORTFALL"
    if not users:
        status = "EMPTY_SELECTION"

    manifest = {
        "schema_version": OFFLINE_SCHEMA_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "random_seed": seed,
        "total_user_count": len(users),
        "requested_total_user_count": total_users,
        "segment_counts": _segment_counts(users),
        "segment_targets": segment_targets,
        "segment_thresholds": segment_thresholds,
        "source_data_paths": {
            "train_user_sequences_path": str(train_sequences_path),
            "all_interactions_path": str(all_interactions_path) if all_interactions_path else None,
            "label_paths": [str(path) for path in resolved_label_paths],
            "item_metadata_path": str(item_metadata_path) if item_metadata_path else None,
        },
        "source_manifest_paths": {"clean_manifest_path": str(clean_manifest_path)},
        "source_data_hash": source_manifest_hash,
        "source_manifest_hash": source_manifest_hash,
        "user_set_hash": user_set_hash,
        "split_contract": {
            "history_source": "train_user_sequences_only",
            "label_source": "valid_or_test_positive_rows_only",
            "history_window": "per-user train recent timestamp sequence min/max when available",
            "label_window": "per-user valid/test positive label timestamp min/max when available",
            "split_policy": "history comes only from train split; labels come only from valid/test splits and are evaluation-only",
            "required_user_conditions": ["history_count >= 1", "label_count >= 1"],
            "history_label_boundary": "train history is used for eligibility and stratification; valid/test labels are evaluation-only",
        },
        "leakage_policy": {
            "train_history_only": True,
            "no_label_in_candidate_generation": True,
            "no_oracle_candidate_injection": True,
            "candidate_generation_allowed": False,
            "eval_labels_allowed_for_candidate_generation": False,
            "ranking_input_replacement_allowed": False,
            "labels_role": "evaluation_only_not_recall_generation_inputs",
        },
        "metric_contract": {
            "recall": {
                "primary_metrics": ["Recall@500", "HitRate@500"],
                "auxiliary_metrics": ["Recall@50", "Recall@100"],
            },
            "ranking": {
                "primary_metrics": ["NDCG@10", "MRR@10", "HitRate@10"],
                "auxiliary_metrics": ["NDCG@20", "Recall@20", "Recall@50"],
                "pure_ranking_requires_fixed_candidate_pool": True,
            },
            "user_denominator": "fixed_users_jsonl",
            "positive_labels": "valid/test positives only",
        },
        "candidate_pool_contract": {
            "recall_eval": "candidate_pool_may_vary_by_method",
            "pure_ranking_eval": "candidate_pool_must_be_fixed",
            "end_to_end_eval": "candidate_pool_and_ranker_may_vary",
            "pool_name": "pool500",
            "candidate_pool_size": 500,
            "candidate_generation_inputs": "train_history_and_non_label_artifacts_only",
            "label_injection_allowed": False,
        },
        "warnings": segment_warnings,
        "selection_config": {
            "min_train_history": min_train_history,
            "positive_sample_size": positive_sample_size,
            "eligible_splits": sorted(ALLOWED_LABEL_SPLITS),
            "segment_basis": "history_count_from_train_user_sequences",
        },
        "summary": {
            "eligible_user_count": len(eligible_candidates),
            "candidate_eval_user_count": label_summary["positive_user_count"],
            "skipped_counts": dict(sorted(skipped_counts.items())),
            "label_summary": label_summary,
        },
        "users": users,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(manifest_path, manifest)
    write_jsonl(users_path, users)
    return manifest


def _validate_args(max_users: int, min_train_history: int, positive_sample_size: int) -> None:
    if max_users <= 0:
        raise ValueError("--max-users must be positive")
    if min_train_history <= 0:
        raise ValueError("--min-train-history must be positive")
    if positive_sample_size < 0:
        raise ValueError("--positive-sample-size must be non-negative")


def _precheck_output(output_path: Path, overwrite: bool) -> None:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}")


def _resolve_repo_path(manifest_path: Path, raw_path: Any) -> Path:
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (manifest_path.parent / path).resolve()


def _resolve_required_train_sequences_path(manifest_path: Path, manifest: dict[str, Any]) -> Path:
    value = manifest.get("train_user_sequences_path")
    if not value:
        raise ValueError("aligned eval selection requires clean_manifest.train_user_sequences_path")
    path = _resolve_repo_path(manifest_path, value)
    if not path.is_file():
        raise FileNotFoundError(f"train_user_sequences_path does not exist: {path}")
    _reject_eval_label_path(path, "train history input")
    return path


def _resolve_optional_all_interactions_path(manifest_path: Path, manifest: dict[str, Any]) -> Path | None:
    split_paths = manifest.get("split_paths") if isinstance(manifest.get("split_paths"), dict) else {}
    value = manifest.get("all_interactions_path") or split_paths.get("all")
    if not value:
        default_path = manifest_path.parent / "canonical_interactions.all.jsonl"
        return default_path.resolve() if default_path.is_file() else None
    path = _resolve_repo_path(manifest_path, value)
    if not path.is_file():
        raise FileNotFoundError(f"all interactions path does not exist: {path}")
    return path


def _resolve_optional_item_metadata_path(manifest_path: Path, manifest: dict[str, Any]) -> Path | None:
    value = manifest.get("canonical_items_path") or manifest.get("items_path")
    if not value:
        default_path = manifest_path.parent / "canonical_items.jsonl"
        return default_path.resolve() if default_path.is_file() else None
    path = _resolve_repo_path(manifest_path, value)
    if not path.is_file():
        raise FileNotFoundError(f"item metadata path does not exist: {path}")
    return path


def _resolve_label_paths(manifest_path: Path, manifest: dict[str, Any], label_paths: Iterable[Path] | None) -> list[Path]:
    if label_paths:
        paths = [Path(path).resolve() for path in label_paths]
    else:
        split_paths = manifest.get("split_paths") if isinstance(manifest.get("split_paths"), dict) else {}
        paths = [_resolve_repo_path(manifest_path, split_paths[split]) for split in ("valid", "test") if split_paths.get(split)]
    if not paths:
        raise ValueError("At least one valid/test label path is required")
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"label path does not exist: {path}")
        split = _split_from_label_path(path, {})
        if split not in ALLOWED_LABEL_SPLITS:
            raise ValueError(f"aligned eval selection only accepts valid/test label paths, got {path}")
    return paths


def _reject_eval_label_path(path: Path, role: str) -> None:
    name = path.name.lower()
    if name.endswith(".valid.jsonl") or name.endswith(".test.jsonl") or ".valid." in name or ".test." in name:
        raise ValueError(f"{role} must not use valid/test label input: {path}")


def _load_train_history(path: Path) -> dict[str, dict[str, Any]]:
    history: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        user_id = _string_value(row, "user_id", "user")
        if not user_id:
            continue
        positive_items = _list_items(row.get("recent_positive_item_sequence"))
        recent_items = _list_items(row.get("recent_item_sequence")) or positive_items
        history_count = max(len(positive_items), len(recent_items), int(row.get("positive_sequence_len") or 0), int(row.get("sequence_len") or 0))
        history_timestamps = _list_ints(row.get("recent_timestamp_sequence")) or _list_ints(row.get("recent_positive_timestamp_sequence"))
        history[user_id] = {
            "history_count": history_count,
            "train_positive_count": len(positive_items),
            "train_unique_item_count": len(set(positive_items or recent_items)),
            "train_recent_sequence_length": len(recent_items),
            "recent_item_ids": recent_items,
            "history_start_time": min(history_timestamps) if history_timestamps else None,
            "history_end_time": max(history_timestamps) if history_timestamps else None,
        }
    return history


def _load_all_interaction_counts(path: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in iter_jsonl(path):
        user_id = _string_value(row, "user_id", "user")
        if user_id:
            counts[user_id] += 1
    return dict(counts)


def _build_eval_label_aggregate_db(paths: list[Path], sample_size: int, db_path: Path, max_positive_users: int | None = None) -> dict[str, Any]:
    row_counts: Counter[str] = Counter()
    positive_counts: Counter[str] = Counter()
    skipped_non_positive_counts: Counter[str] = Counter()
    skipped_missing_key_counts: Counter[str] = Counter()
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("CREATE TABLE labels (user_id TEXT PRIMARY KEY, splits_json TEXT NOT NULL, positive_count INTEGER NOT NULL, sample_json TEXT NOT NULL, item_counts_json TEXT NOT NULL, label_start_time INTEGER, label_end_time INTEGER)")
        connection.execute("CREATE TABLE label_user_splits (split TEXT NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY (split, user_id))")
        positive_user_count = 0
        reached_limit = False
        for path in paths:
            for row in iter_jsonl(path):
                split = _split_from_label_path(path, row)
                if split not in ALLOWED_LABEL_SPLITS:
                    raise ValueError(f"Only valid/test rows are allowed for eval selection, got split={split!r} from {path}")
                row_counts[split] += 1
                user_id = _string_value(row, "user_id", "user")
                item_id = _string_value(row, "parent_asin", "item_id", "item")
                if not user_id or not item_id:
                    skipped_missing_key_counts[split] += 1
                    continue
                if not _is_positive(row):
                    skipped_non_positive_counts[split] += 1
                    continue
                positive_counts[split] += 1
                connection.execute("INSERT OR IGNORE INTO label_user_splits (split, user_id) VALUES (?, ?)", (split, user_id))
                existing = connection.execute("SELECT splits_json, positive_count, sample_json, item_counts_json, label_start_time, label_end_time FROM labels WHERE user_id = ?", (user_id,)).fetchone()
                label_timestamp = _optional_int(row.get("timestamp"))
                item_interaction_count = _optional_int(row.get("item_interaction_count"))
                if existing is None:
                    samples = [item_id] if sample_size > 0 else []
                    item_counts = [item_interaction_count] if item_interaction_count is not None and sample_size > 0 else []
                    connection.execute(
                        "INSERT INTO labels (user_id, splits_json, positive_count, sample_json, item_counts_json, label_start_time, label_end_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user_id, json.dumps([split]), 1, json.dumps(samples), json.dumps(item_counts), label_timestamp, label_timestamp),
                    )
                    positive_user_count += 1
                    if max_positive_users is not None and positive_user_count >= max_positive_users:
                        reached_limit = True
                        break
                    continue
                splits = json.loads(existing[0])
                if split not in splits:
                    splits.append(split)
                positive_count = int(existing[1]) + 1
                samples = json.loads(existing[2])
                if len(samples) < sample_size and item_id not in samples:
                    samples.append(item_id)
                item_counts = json.loads(existing[3])
                if item_interaction_count is not None and len(item_counts) < sample_size:
                    item_counts.append(item_interaction_count)
                label_start_time = existing[4]
                label_end_time = existing[5]
                if label_timestamp is not None:
                    label_start_time = label_timestamp if label_start_time is None else min(label_start_time, label_timestamp)
                    label_end_time = label_timestamp if label_end_time is None else max(label_end_time, label_timestamp)
                connection.execute(
                    "UPDATE labels SET splits_json = ?, positive_count = ?, sample_json = ?, item_counts_json = ?, label_start_time = ?, label_end_time = ? WHERE user_id = ?",
                    (json.dumps(sorted(splits)), positive_count, json.dumps(samples), json.dumps(item_counts), label_start_time, label_end_time, user_id),
                )
            if reached_limit:
                break
        connection.commit()
        positive_user_counts = {
            split: connection.execute("SELECT COUNT(*) FROM label_user_splits WHERE split = ?", (split,)).fetchone()[0]
            for split in sorted(ALLOWED_LABEL_SPLITS)
        }
        positive_user_count = connection.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
        return {
            "row_counts": {split: row_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
            "positive_counts": {split: positive_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
            "positive_user_counts": positive_user_counts,
            "positive_user_count": positive_user_count,
            "skipped_non_positive_counts": {split: skipped_non_positive_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
            "skipped_missing_key_counts": {split: skipped_missing_key_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
            "positive_dedup_key": "user_id,parent_asin per split not materialized in offline builder",
            "aggregation_store": "temporary_sqlite_disk_table",
            "max_positive_users_scanned": max_positive_users,
        }
    finally:
        connection.close()


def _aggregate_positive_eval_users(positive_by_split_user: dict[str, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    by_user: dict[str, dict[str, Any]] = {}
    for split in sorted(ALLOWED_LABEL_SPLITS):
        for user_id, label_info in sorted(positive_by_split_user[split].items()):
            entry = by_user.setdefault(
                user_id,
                {
                    "eval_label_splits": [],
                    "future_positive_count": 0,
                    "label_count": 0,
                    "positive_items_sample": [],
                    "label_item_interaction_counts_sample": [],
                    "label_start_time": None,
                    "label_end_time": None,
                },
            )
            entry["eval_label_splits"].append(split)
            entry["future_positive_count"] += int(label_info["positive_count"])
            entry["label_count"] += int(label_info["positive_count"])
            if label_info.get("label_start_time") is not None:
                entry["label_start_time"] = label_info["label_start_time"] if entry["label_start_time"] is None else min(entry["label_start_time"], label_info["label_start_time"])
            if label_info.get("label_end_time") is not None:
                entry["label_end_time"] = label_info["label_end_time"] if entry["label_end_time"] is None else max(entry["label_end_time"], label_info["label_end_time"])
            entry["positive_items_sample"].extend(item for item in label_info["positive_items_sample"] if item not in entry["positive_items_sample"])
            entry["label_item_interaction_counts_sample"].extend(label_info.get("label_item_interaction_counts_sample", []))
    return by_user


def _load_eval_positives(paths: list[Path], sample_size: int) -> tuple[dict[str, Any], dict[str, dict[str, dict[str, Any]]]]:
    positive_by_split_user: dict[str, dict[str, dict[str, Any]]] = {"valid": {}, "test": {}}
    row_counts: Counter[str] = Counter()
    positive_counts: Counter[str] = Counter()
    skipped_non_positive_counts: Counter[str] = Counter()
    skipped_missing_key_counts: Counter[str] = Counter()
    seen_pairs: set[tuple[str, str, str]] = set()
    for path in paths:
        for row in iter_jsonl(path):
            split = _split_from_label_path(path, row)
            if split not in ALLOWED_LABEL_SPLITS:
                raise ValueError(f"Only valid/test rows are allowed for eval selection, got split={split!r} from {path}")
            row_counts[split] += 1
            user_id = _string_value(row, "user_id", "user")
            item_id = _string_value(row, "parent_asin", "item_id", "item")
            if not user_id or not item_id:
                skipped_missing_key_counts[split] += 1
                continue
            if not _is_positive(row):
                skipped_non_positive_counts[split] += 1
                continue
            key = (split, user_id, item_id)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            positive_counts[split] += 1
            user_entry = positive_by_split_user[split].setdefault(
                user_id,
                {"positive_count": 0, "positive_items_sample": [], "label_item_interaction_counts_sample": [], "label_start_time": None, "label_end_time": None},
            )
            user_entry["positive_count"] += 1
            label_timestamp = _optional_int(row.get("timestamp"))
            if label_timestamp is not None:
                user_entry["label_start_time"] = label_timestamp if user_entry["label_start_time"] is None else min(user_entry["label_start_time"], label_timestamp)
                user_entry["label_end_time"] = label_timestamp if user_entry["label_end_time"] is None else max(user_entry["label_end_time"], label_timestamp)
            if len(user_entry["positive_items_sample"]) < sample_size:
                user_entry["positive_items_sample"].append(item_id)
            item_interaction_count = _optional_int(row.get("item_interaction_count"))
            if item_interaction_count is not None and len(user_entry["label_item_interaction_counts_sample"]) < sample_size:
                user_entry["label_item_interaction_counts_sample"].append(item_interaction_count)
    summary = {
        "row_counts": {split: row_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
        "positive_counts": {split: positive_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
        "positive_user_counts": {split: len(positive_by_split_user[split]) for split in sorted(ALLOWED_LABEL_SPLITS)},
        "skipped_non_positive_counts": {split: skipped_non_positive_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
        "skipped_missing_key_counts": {split: skipped_missing_key_counts.get(split, 0) for split in sorted(ALLOWED_LABEL_SPLITS)},
        "positive_dedup_key": "split,user_id,parent_asin",
    }
    return summary, positive_by_split_user


def _select_profiles(
    *,
    positive_by_split_user: dict[str, dict[str, dict[str, Any]]],
    history_by_user: dict[str, dict[str, Any]],
    all_interaction_counts: dict[str, int],
    max_users: int,
    seed: int,
    min_train_history: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates = []
    skipped_counts: Counter[str] = Counter()
    for split in sorted(ALLOWED_LABEL_SPLITS):
        for user_id, label_info in sorted(positive_by_split_user[split].items()):
            history = history_by_user.get(user_id)
            if history is None:
                skipped_counts["missing_train_history"] += 1
                continue
            train_history_count = int(history["history_count"])
            if train_history_count < min_train_history:
                skipped_counts["insufficient_train_history"] += 1
                continue
            candidates.append(
                {
                    "user_id": user_id,
                    "split": split,
                    "positive_count": label_info["positive_count"],
                    "positive_items_sample": label_info["positive_items_sample"],
                    "positive_items_sample_count": len(label_info["positive_items_sample"]),
                    "train_positive_count": history["train_positive_count"],
                    "train_unique_item_count": history["train_unique_item_count"],
                    "train_recent_sequence_length": history["train_recent_sequence_length"],
                    "all_interaction_count": all_interaction_counts.get(user_id),
                    "eligible_for_aligned_eval": True,
                    "selection_reason": "valid_or_test_positive_with_train_history",
                }
            )
    random.Random(seed).shuffle(candidates)
    return candidates[:max_users], skipped_counts


def _build_offline_candidates(
    *,
    positive_by_split_user: dict[str, dict[str, dict[str, Any]]],
    history_by_user: dict[str, dict[str, Any]],
    all_interaction_counts: dict[str, int],
    min_train_history: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    by_user: dict[str, dict[str, Any]] = {}
    skipped_counts: Counter[str] = Counter()
    for split in sorted(ALLOWED_LABEL_SPLITS):
        for user_id, label_info in sorted(positive_by_split_user[split].items()):
            history = history_by_user.get(user_id)
            if history is None:
                skipped_counts["missing_train_history"] += 1
                continue
            history_count = int(history["history_count"])
            if history_count < min_train_history:
                skipped_counts["insufficient_train_history"] += 1
                continue
            entry = by_user.setdefault(
                user_id,
                {
                    "user_id": user_id,
                    "eval_label_splits": [],
                    "future_positive_count": 0,
                    "label_count": 0,
                    "positive_items_sample": [],
                    "label_item_interaction_counts_sample": [],
                    "history_count": history_count,
                    "train_positive_count": history["train_positive_count"],
                    "train_unique_item_count": history["train_unique_item_count"],
                    "train_recent_sequence_length": history["train_recent_sequence_length"],
                    "history_start_time": history["history_start_time"],
                    "history_end_time": history["history_end_time"],
                    "label_start_time": None,
                    "label_end_time": None,
                    "all_interaction_count": all_interaction_counts.get(user_id),
                    "recent_item_ids": history["recent_item_ids"],
                },
            )
            entry["eval_label_splits"].append(split)
            entry["future_positive_count"] += int(label_info["positive_count"])
            entry["label_count"] += int(label_info["positive_count"])
            if label_info.get("label_start_time") is not None:
                entry["label_start_time"] = label_info["label_start_time"] if entry["label_start_time"] is None else min(entry["label_start_time"], label_info["label_start_time"])
            if label_info.get("label_end_time") is not None:
                entry["label_end_time"] = label_info["label_end_time"] if entry["label_end_time"] is None else max(entry["label_end_time"], label_info["label_end_time"])
            entry["positive_items_sample"].extend(item for item in label_info["positive_items_sample"] if item not in entry["positive_items_sample"])
            entry["label_item_interaction_counts_sample"].extend(label_info.get("label_item_interaction_counts_sample", []))
    return list(by_user.values()), skipped_counts


def _build_offline_candidates_from_label_db(
    *,
    train_sequences_path: Path,
    label_db_path: Path,
    all_interaction_counts: dict[str, int],
    min_train_history: int,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    candidates: list[dict[str, Any]] = []
    skipped_counts: Counter[str] = Counter()
    seen_history_count = 0
    connection = sqlite3.connect(label_db_path)
    try:
        positive_user_count = connection.execute("SELECT COUNT(*) FROM labels").fetchone()[0]
        for row in iter_jsonl(train_sequences_path):
            user_id = _string_value(row, "user_id", "user")
            if not user_id:
                continue
            label_row = connection.execute(
                "SELECT splits_json, positive_count, sample_json, item_counts_json, label_start_time, label_end_time FROM labels WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if label_row is None:
                continue
            seen_history_count += 1
            positive_items = _list_items(row.get("recent_positive_item_sequence"))
            recent_items = _list_items(row.get("recent_item_sequence")) or positive_items
            history_count = max(len(positive_items), len(recent_items), int(row.get("positive_sequence_len") or 0), int(row.get("sequence_len") or 0))
            if history_count < min_train_history:
                skipped_counts["insufficient_train_history"] += 1
                continue
            history_timestamps = _list_ints(row.get("recent_timestamp_sequence")) or _list_ints(row.get("recent_positive_timestamp_sequence"))
            label_count = int(label_row[1])
            candidates.append(
                {
                    "user_id": user_id,
                    "eval_label_splits": json.loads(label_row[0]),
                    "future_positive_count": label_count,
                    "label_count": label_count,
                    "positive_items_sample": json.loads(label_row[2]),
                    "label_item_interaction_counts_sample": json.loads(label_row[3]),
                    "history_count": history_count,
                    "train_positive_count": len(positive_items),
                    "train_unique_item_count": len(set(positive_items or recent_items)),
                    "train_recent_sequence_length": len(recent_items),
                    "history_start_time": min(history_timestamps) if history_timestamps else None,
                    "history_end_time": max(history_timestamps) if history_timestamps else None,
                    "label_start_time": label_row[4],
                    "label_end_time": label_row[5],
                    "all_interaction_count": all_interaction_counts.get(user_id),
                }
            )
        skipped_counts["missing_train_history"] = positive_user_count - seen_history_count
        return candidates, skipped_counts
    finally:
        connection.close()


def _segment_targets(total_users: int) -> dict[str, int]:
    raw = {segment: total_users * ratio for segment, ratio in DEFAULT_SEGMENT_RATIOS.items()}
    targets = {segment: int(value) for segment, value in raw.items()}
    remaining = total_users - sum(targets.values())
    remainders = sorted(((value - int(value), segment) for segment, value in raw.items()), reverse=True)
    for _, segment in remainders[:remaining]:
        targets[segment] += 1
    return targets


def _segment_counts(users: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(user["segment"] for user in users)
    return {segment: counts.get(segment, 0) for segment in ("hot", "warm", "cold-ish")}


def _segment_candidates(candidates: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, int | None]]]:
    ordered = sorted(candidates, key=lambda row: (-int(row["history_count"]), row["user_id"]))
    total = len(ordered)
    hot_end = int(total * DEFAULT_SEGMENT_RATIOS["hot"])
    warm_end = hot_end + int(total * DEFAULT_SEGMENT_RATIOS["warm"])
    segmented = {"hot": ordered[:hot_end], "warm": ordered[hot_end:warm_end], "cold-ish": ordered[warm_end:]}
    thresholds: dict[str, dict[str, int | None]] = {}
    for segment, rows in segmented.items():
        counts = [int(row["history_count"]) for row in rows]
        thresholds[segment] = {"min_history_count": min(counts) if counts else None, "max_history_count": max(counts) if counts else None}
    return segmented, thresholds


def _select_segmented_users(segmented_candidates: dict[str, list[dict[str, Any]]], targets: dict[str, int], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    warnings = []
    for segment in ("hot", "warm", "cold-ish"):
        candidates = list(segmented_candidates[segment])
        random.Random(seed + len(segment)).shuffle(candidates)
        target = targets[segment]
        if len(candidates) < target:
            warnings.append({"segment": segment, "status": "INSUFFICIENT_ELIGIBLE_USERS", "target": target, "available": len(candidates), "selected": len(candidates)})
        for row in candidates[:target]:
            user = dict(row)
            user["segment"] = segment
            user["diagnostics"] = {
                "category_diversity": None,
                "head_tail_preference": _head_tail_preference(user.get("label_item_interaction_counts_sample", [])),
            }
            user.pop("label_item_interaction_counts_sample", None)
            selected.append(user)
    selected.sort(key=lambda row: (row["segment"], row["user_id"]))
    return selected, warnings


def _attach_user_diagnostics(users: list[dict[str, Any]], item_metadata_path: Path | None, train_sequences_path: Path | None = None) -> list[dict[str, Any]]:
    if not users:
        return users
    if item_metadata_path is None:
        for user in users:
            user.pop("recent_item_ids", None)
        return users
    selected_user_ids = {str(user["user_id"]) for user in users}
    recent_by_user = _load_recent_items_for_users(train_sequences_path, selected_user_ids) if train_sequences_path else {}
    needed_items: set[str] = set()
    for user in users:
        items = recent_by_user.get(str(user["user_id"]), _list_items(user.get("recent_item_ids")))
        recent_by_user[str(user["user_id"])] = items
        needed_items.update(items)
    item_categories = _load_item_categories(item_metadata_path, needed_items)
    for user in users:
        categories = {item_categories[item] for item in recent_by_user[str(user["user_id"])] if item in item_categories and item_categories[item]}
        user["diagnostics"]["category_diversity"] = len(categories) if categories else None
        user.pop("recent_item_ids", None)
    return users


def _load_recent_items_for_users(path: Path | None, user_ids: set[str]) -> dict[str, list[str]]:
    if path is None or not user_ids:
        return {}
    recent_by_user: dict[str, list[str]] = {}
    for row in iter_jsonl(path):
        user_id = _string_value(row, "user_id", "user")
        if user_id not in user_ids:
            continue
        positive_items = _list_items(row.get("recent_positive_item_sequence"))
        recent_by_user[user_id] = _list_items(row.get("recent_item_sequence")) or positive_items
        if len(recent_by_user) == len(user_ids):
            break
    return recent_by_user


def _load_item_categories(path: Path, needed_items: set[str]) -> dict[str, str]:
    if not needed_items:
        return {}
    categories: dict[str, str] = {}
    for row in iter_jsonl(path):
        item_id = _string_value(row, "parent_asin", "item_id", "item")
        if item_id not in needed_items:
            continue
        category = _string_value(row, *CATEGORY_FIELDS)
        if not category and isinstance(row.get("categories_flat"), list) and row["categories_flat"]:
            category = str(row["categories_flat"][0])
        categories[item_id] = category
        if len(categories) == len(needed_items):
            break
    return categories


def _head_tail_preference(counts: list[int]) -> str | None:
    counts = [count for count in counts if count >= 0]
    if not counts:
        return None
    average = sum(counts) / len(counts)
    if average >= 100:
        return "head"
    if average <= 10:
        return "tail"
    return "mid"


def _string_value(row: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = row.get(field)
        if value is not None and str(value) != "":
            return str(value)
    return ""


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _list_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _list_ints(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    values = []
    for item in value:
        parsed = _optional_int(item)
        if parsed is not None:
            values.append(parsed)
    return values


def _split_from_label_path(path: Path, row: dict[str, Any]) -> str:
    split = _string_value(row, "split")
    if split:
        return split
    name = path.name.lower()
    if ".valid." in name or name.startswith("valid"):
        return "valid"
    if ".test." in name or name.startswith("test"):
        return "test"
    return ""


def _is_positive(row: dict[str, Any]) -> bool:
    for field in POSITIVE_FIELDS:
        if field in row:
            return int(row.get(field) or 0) == 1
    if "rating" in row:
        return float(row.get("rating") or 0.0) > 0.0
    return True


def main() -> None:
    args = parse_args()
    if args.offline_eval_output or args.dry_run:
        total_users = args.dry_run_users if args.dry_run and args.total_users == DEFAULT_TOTAL_USERS else args.total_users
        output_dir = Path(args.offline_eval_output) if args.offline_eval_output else DEFAULT_OFFLINE_EVAL_OUTPUT_DIR
        manifest = build_pool500_offline_eval_users(
            clean_manifest_path=Path(args.clean_manifest),
            output_dir=output_dir,
            label_paths=[Path(path) for path in args.label] if args.label else None,
            total_users=total_users,
            seed=args.seed,
            min_train_history=args.min_train_history,
            positive_sample_size=args.positive_sample_size,
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
        print(
            json.dumps(
                {
                    "status": manifest["status"],
                    "selected_user_count": manifest["total_user_count"],
                    "segment_counts": manifest["segment_counts"],
                    "manifest_path": str(output_dir / "manifest.json"),
                    "users_path": str(output_dir / "users.jsonl"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    manifest = select_pool500_aligned_eval_users(
        clean_manifest_path=Path(args.clean_manifest),
        output_dir=Path(args.output_dir),
        label_paths=[Path(path) for path in args.label] if args.label else None,
        max_users=args.max_users,
        seed=args.seed,
        min_train_history=args.min_train_history,
        positive_sample_size=args.positive_sample_size,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "selected_user_count": manifest["summary"]["selected_user_count"],
                "manifest_path": str(Path(args.output_dir) / "aligned_eval_users_manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
