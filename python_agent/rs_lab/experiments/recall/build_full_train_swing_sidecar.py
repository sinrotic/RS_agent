from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _enforce_project_venv, _existing_ancestor, _file_signature

SCHEMA_VERSION = "full_train_swing_sidecar_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_full_sources" / "swing_recall"
DEFAULT_MIN_FREE_BYTES = 10 * 1024**3
SCORE_MODE_LEGACY_APPROX = "legacy_approx"
SCORE_MODE_DATAWHALE_STANDARD = "datawhale_standard"
SCORE_MODES = (SCORE_MODE_LEGACY_APPROX, SCORE_MODE_DATAWHALE_STANDARD)
USER_WEIGHT_MODE = "inverse_sqrt_retained_user_item_count"
COMMON_USER_PAIR_MODE = "distinct_unordered"
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
    "valid",
    "test",
    "holdout",
    "label",
    "labels",
    "all_window",
)
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "canonical_interactions.jsonl",
    "all_interactions.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "user_sequences.jsonl",
    "labels.jsonl",
    "holdout.jsonl",
)
FORBIDDEN_MANIFEST_INPUT_KEYS = (
    "all_interactions_path",
    "all_user_sequences_path",
    "all_window_path",
    "all_window_user_sequences_path",
    "canonical_interactions_path",
    "holdout_path",
    "holdout_user_sequences_path",
    "label_path",
    "labels_path",
    "split_paths",
    "test_path",
    "test_user_sequences_path",
    "user_sequences_path",
    "valid_path",
    "valid_user_sequences_path",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a train-only full-clean Swing item-pair sidecar for pool500 recall sources.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--max-item-user-freq", type=int, default=500)
    parser.add_argument("--max-user-items", type=int, default=100)
    parser.add_argument("--min-pair-support", type=int, default=2)
    parser.add_argument("--per-seed-top-k", type=int, default=200)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--score-mode", choices=SCORE_MODES, default=SCORE_MODE_LEGACY_APPROX)
    parser.add_argument("--alpha", type=float, default=1.0)
    parser.add_argument("--min-user-items", type=int, default=2)
    parser.add_argument("--min-src-item-positive-user-count", type=int, default=1)
    parser.add_argument("--min-dst-item-positive-user-count", type=int, default=1)
    parser.add_argument("--pre-filter-users-before-item-count", action="store_true")
    parser.add_argument("--disable-post-item-user-filter", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_full_train_swing_sidecar(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_item_user_freq: int = 500,
    max_user_items: int = 100,
    min_pair_support: int = 2,
    per_seed_top_k: int = 200,
    min_score: float = 0.0,
    score_mode: str = SCORE_MODE_LEGACY_APPROX,
    alpha: float = 1.0,
    min_user_items: int = 2,
    min_src_item_positive_user_count: int = 1,
    min_dst_item_positive_user_count: int = 1,
    pre_filter_users_before_item_count: bool = False,
    disable_post_item_user_filter: bool = False,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    _validate_limits(
        max_item_user_freq,
        max_user_items,
        min_pair_support,
        per_seed_top_k,
        min_score,
        score_mode,
        alpha,
        min_user_items,
        min_src_item_positive_user_count,
        min_dst_item_positive_user_count,
    )
    if enforce_venv:
        _enforce_project_venv()

    clean_manifest_path = clean_manifest_path.resolve()
    output_dir = output_dir.resolve()
    clean_manifest = _read_json(clean_manifest_path)
    train_sequences_path = _resolve_train_sequences_path(clean_manifest_path, clean_manifest)
    input_contract = _input_contract(clean_manifest_path, train_sequences_path, clean_manifest)
    _precheck(clean_manifest_path, train_sequences_path, output_dir, min_free_bytes, overwrite)

    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free

    sequences_by_user, load_audit = _load_train_positive_sequences(train_sequences_path, max_user_items, min_user_items)
    item_count_sequences_by_user = sequences_by_user
    if pre_filter_users_before_item_count:
        item_count_sequences_by_user = _filter_sequences_by_user_item_count(sequences_by_user, min_user_items)
    item_users = _build_item_users(item_count_sequences_by_user)
    dropped_hot_items = _dropped_hot_items(item_users, max_item_user_freq)
    filtered_sequences_by_user, item_filter_audit = _filter_sequences_by_item_count(
        sequences_by_user=item_count_sequences_by_user,
        item_users=item_users,
        dropped_hot_items=set(dropped_hot_items),
        min_src_item_positive_user_count=min_src_item_positive_user_count,
        min_dst_item_positive_user_count=min_dst_item_positive_user_count,
        min_user_items=min_user_items,
        apply_post_item_user_filter=not disable_post_item_user_filter,
    )
    load_audit.update(
        {
            "pre_user_filter_applied_before_item_count": pre_filter_users_before_item_count,
            "post_item_user_filter_enabled": not disable_post_item_user_filter,
            "retained_user_count_before_item_filter": len(item_count_sequences_by_user),
            "retained_positive_item_count_before_item_filter": sum(len(items) for items in item_count_sequences_by_user.values()),
            "skipped_user_count_by_pre_item_count_filter": len(sequences_by_user) - len(item_count_sequences_by_user),
            "retained_user_count": len(filtered_sequences_by_user),
            "retained_positive_item_count": sum(len(items) for items in filtered_sequences_by_user.values()),
            "skipped_user_count_below_min_after_item_filter": item_filter_audit[
                "skipped_user_count_below_min_after_item_filter"
            ],
            "retained_item_count_bucket_distribution_after_item_filter": item_filter_audit[
                "retained_item_count_bucket_distribution_after_item_filter"
            ],
        }
    )
    filtered_item_users = _build_item_users(filtered_sequences_by_user)
    src_eligible_items = set(item_filter_audit["src_eligible_items"])
    dst_eligible_items = set(item_filter_audit["dst_eligible_items"])
    edges, build_audit = _build_swing_edges(
        sequences_by_user=filtered_sequences_by_user,
        item_users=filtered_item_users,
        src_eligible_items=src_eligible_items,
        dst_eligible_items=dst_eligible_items,
        min_pair_support=min_pair_support,
        per_seed_top_k=per_seed_top_k,
        min_score=min_score,
        score_mode=score_mode,
        alpha=alpha,
    )

    edges_path = output_dir / "swing_recall_edges.jsonl"
    write_jsonl(edges_path, edges)

    guard_contract = {
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    parameters = {
        "max_item_user_freq": max_item_user_freq,
        "max_user_items": max_user_items,
        "min_pair_support": min_pair_support,
        "per_seed_top_k": per_seed_top_k,
        "min_score": min_score,
        "score_mode": score_mode,
        "alpha": alpha,
        "min_user_items": min_user_items,
        "min_src_item_positive_user_count": min_src_item_positive_user_count,
        "min_dst_item_positive_user_count": min_dst_item_positive_user_count,
        "pre_filter_users_before_item_count": pre_filter_users_before_item_count,
        "disable_post_item_user_filter": disable_post_item_user_filter,
    }
    no_holdout_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **guard_contract,
        **input_contract,
        "read_files": [str(train_sequences_path)],
        "valid_test_holdout_usage": "not_read",
        "uses_all_window": False,
        "uses_valid": False,
        "uses_test": False,
        "uses_holdout": False,
        "uses_label": False,
        "uses_canonical_interactions": False,
        "uses_all_interactions": False,
        "source_signatures": {
            "clean_manifest": _file_signature(clean_manifest_path),
            "train_user_sequences": _file_signature(train_sequences_path),
        },
    }
    custom_index_selection_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **guard_contract,
        **input_contract,
        "method": "swing_recall",
        "input_strategy": "clean_manifest.train_user_sequences_path_only",
        "ranking_input_replacement": False,
        "pool500_recall_source_sidecar": True,
        "pool1000_ready": False,
        "parameters": parameters,
    }
    dropped_hot_payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "max_item_user_freq": max_item_user_freq,
        "dropped_item_count": len(dropped_hot_items),
        "items": [
            {"item_id": item_id, "train_user_freq": len(item_users[item_id])}
            for item_id in dropped_hot_items
        ],
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        **guard_contract,
        "lifecycle_stage": "builder_complete",
        "provenance": input_contract,
        "source_signatures": {
            "clean_manifest": _file_signature(clean_manifest_path),
            "train_user_sequences": _file_signature(train_sequences_path),
        },
        "disk_free_bytes_start": "excluded_from_canonical_sha",
        "disk_free_bytes_end": "excluded_from_canonical_sha",
        "canonical_sha_excluded_fields": ["disk_free_bytes_start", "disk_free_bytes_end"],
        "min_free_bytes": min_free_bytes,
        "user_count": len(filtered_sequences_by_user),
        "user_count_raw_loaded": len(sequences_by_user),
        "user_count_before_item_filter": len(item_count_sequences_by_user),
        "item_count_before_hot_drop": len(item_users),
        "item_count_after_hot_drop": len(item_users) - len(dropped_hot_items),
        "dropped_hot_item_count": len(dropped_hot_items),
        "edge_count": len(edges),
        "shard_audit": _shard_audit(edges),
        "load_audit": load_audit,
        "item_filter_audit": _public_item_filter_audit(item_filter_audit),
        "build_audit": build_audit,
        "no_unbounded_global_pair_counter": True,
        "partial_invalidation_keys": [
            "source_signatures.clean_manifest.sha256",
            "source_signatures.train_user_sequences.sha256",
            "parameters",
        ],
    }
    edge_signature = _file_signature(edges_path)
    edge_signature["path"] = "swing_recall_edges.jsonl"
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": "excluded_from_canonical_sha",
        "source": "swing_recall",
        **guard_contract,
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "input_contract": input_contract,
        "lifecycle_stage": "builder_complete",
        "provenance": {
            "clean_manifest_signature": _file_signature(clean_manifest_path),
            "train_user_sequences_signature": _file_signature(train_sequences_path),
        },
        "output_dir": "excluded_from_canonical_sha",
        "runtime_seconds": "excluded_from_canonical_sha",
        "canonical_sha_excluded_fields": ["generated_at", "output_dir", "runtime_seconds"],
        "edge_count": len(edges),
        "seed_count": len({edge["src_item"] for edge in edges}),
        "parameters": parameters,
        "required_artifacts": {
            "swing_recall_edges": "swing_recall_edges.jsonl",
            "source_index_manifest": "source_index_manifest.json",
            "custom_index_selection_manifest": "custom_index_selection_manifest.json",
            "dropped_hot_items": "dropped_hot_items.json",
            "resource_audit": "resource_audit.json",
            "no_holdout_audit": "no_holdout_audit.json",
        },
        "artifact_signatures": {
            "swing_recall_edges": edge_signature,
        },
        "partial_invalidation_keys": [
            "provenance.clean_manifest_signature.sha256",
            "provenance.train_user_sequences_signature.sha256",
            "parameters",
        ],
    }

    write_json(output_dir / "custom_index_selection_manifest.json", custom_index_selection_manifest)
    write_json(output_dir / "dropped_hot_items.json", dropped_hot_payload)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _validate_limits(
    max_item_user_freq: int,
    max_user_items: int,
    min_pair_support: int,
    per_seed_top_k: int,
    min_score: float,
    score_mode: str,
    alpha: float,
    min_user_items: int,
    min_src_item_positive_user_count: int,
    min_dst_item_positive_user_count: int,
) -> None:
    for label, value in {
        "max_item_user_freq": max_item_user_freq,
        "max_user_items": max_user_items,
        "min_pair_support": min_pair_support,
        "per_seed_top_k": per_seed_top_k,
    }.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if min_score < 0:
        raise ValueError("min_score must be non-negative")
    if score_mode not in SCORE_MODES:
        raise ValueError(f"score_mode must be one of {SCORE_MODES}")
    if alpha <= 0:
        raise ValueError("alpha must be positive")
    if min_user_items < 2:
        raise ValueError("min_user_items must be at least 2")
    if min_user_items > max_user_items:
        raise ValueError("min_user_items must be less than or equal to max_user_items")
    if min_src_item_positive_user_count <= 0:
        raise ValueError("min_src_item_positive_user_count must be positive")
    if min_dst_item_positive_user_count <= 0:
        raise ValueError("min_dst_item_positive_user_count must be positive")


def _input_contract(clean_manifest_path: Path, train_sequences_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed_inputs": ["clean_manifest.train_user_sequences_path"],
        "declared_inputs": [str(train_sequences_path)],
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "forbidden_manifest_inputs": list(FORBIDDEN_MANIFEST_INPUT_KEYS),
        "forbidden_files_not_read": [str(train_sequences_path.parent / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "manifest_has_outputs_train_user_sequences_path": isinstance(manifest.get("outputs"), dict)
        and bool(manifest.get("outputs", {}).get("train_user_sequences_path")),
    }


def _resolve_train_sequences_path(clean_manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path")
    if not raw_path:
        raise ValueError("Clean manifest must declare train_user_sequences_path")
    path = Path(str(raw_path))
    if path.is_absolute():
        return path.resolve()
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists():
        return root_candidate
    return (clean_manifest_path.parent / path).resolve()


def _validate_manifest_inputs(manifest: dict[str, Any]) -> None:
    outputs = manifest.get("outputs", {})
    declared_keys = {key for key, value in manifest.items() if value not in (None, "", [], {})}
    if isinstance(outputs, dict):
        declared_keys.update(f"outputs.{key}" for key, value in outputs.items() if value not in (None, "", [], {}))
    forbidden = sorted(
        key
        for key in declared_keys
        if key in FORBIDDEN_MANIFEST_INPUT_KEYS
        or key.removeprefix("outputs.") in FORBIDDEN_MANIFEST_INPUT_KEYS
    )
    if forbidden:
        raise ValueError("Forbidden Swing builder manifest inputs: " + ", ".join(forbidden))


def _has_forbidden_path_part(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & set(FORBIDDEN_PATH_PARTS))


def _precheck(clean_manifest_path: Path, train_sequences_path: Path, output_dir: Path, min_free_bytes: int, overwrite: bool) -> None:
    for path in (clean_manifest_path, train_sequences_path, output_dir):
        forbidden_input_files = set(FORBIDDEN_CANDIDATE_FILES) if path != output_dir else set()
        if _has_forbidden_path_part(path) or path.name.lower() in forbidden_input_files:
            raise ValueError(f"Forbidden input/output path for full-train Swing sidecar: {path}")
    if train_sequences_path.name != "user_sequences.train.jsonl":
        raise ValueError(f"Swing sidecar must read user_sequences.train.jsonl, got: {train_sequences_path}")
    missing = [str(path) for path in (clean_manifest_path, train_sequences_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input files: " + ", ".join(missing))
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"Free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _load_train_positive_sequences(path: Path, max_user_items: int, min_user_items: int) -> tuple[dict[str, list[str]], dict[str, Any]]:
    sequences_by_user: dict[str, list[str]] = {}
    raw_user_count_seen = 0
    raw_user_count_with_two_positive_items = 0
    raw_user_count_with_min_positive_items = 0
    raw_positive_count = 0
    retained_positive_count = 0
    truncated_user_count = 0
    skipped_user_count_below_min_raw_items = 0
    skipped_user_count_below_min_retained_unique_items = 0
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        raw_user_count_seen += 1
        raw_items = [str(item_id) for item_id in row.get("recent_positive_item_sequence", []) or [] if item_id]
        if not raw_items:
            skipped_user_count_below_min_raw_items += 1
            continue
        if len(raw_items) >= 2:
            raw_user_count_with_two_positive_items += 1
        if len(raw_items) >= min_user_items:
            raw_user_count_with_min_positive_items += 1
        else:
            skipped_user_count_below_min_raw_items += 1
        raw_positive_count += len(raw_items)
        items = list(dict.fromkeys(raw_items[-max_user_items:]))
        if len(raw_items) > max_user_items:
            truncated_user_count += 1
        if not items:
            skipped_user_count_below_min_retained_unique_items += 1
            continue
        if len(items) < min_user_items:
            skipped_user_count_below_min_retained_unique_items += 1
        sequences_by_user[user_id] = items
        retained_positive_count += len(items)
    return sequences_by_user, {
        "min_user_items": min_user_items,
        "user_filter_stage": "after_item_filter",
        "raw_user_count_seen": raw_user_count_seen,
        "raw_user_count_with_two_positive_items": raw_user_count_with_two_positive_items,
        "raw_user_count_with_min_positive_items": raw_user_count_with_min_positive_items,
        "retained_user_count_before_item_filter": len(sequences_by_user),
        "retained_user_count": len(sequences_by_user),
        "raw_positive_item_count": raw_positive_count,
        "retained_positive_item_count_before_item_filter": retained_positive_count,
        "retained_positive_item_count": retained_positive_count,
        "truncated_user_count_by_max_user_items": truncated_user_count,
        "skipped_user_count_below_min_raw_items": skipped_user_count_below_min_raw_items,
        "skipped_user_count_below_min_retained_unique_items": skipped_user_count_below_min_retained_unique_items,
    }


def _build_item_users(sequences_by_user: dict[str, list[str]]) -> dict[str, set[str]]:
    item_users: dict[str, set[str]] = defaultdict(set)
    for user_id, items in sequences_by_user.items():
        for item_id in items:
            item_users[item_id].add(user_id)
    return dict(item_users)


def _filter_sequences_by_user_item_count(sequences_by_user: dict[str, list[str]], min_user_items: int) -> dict[str, list[str]]:
    return {user_id: items for user_id, items in sequences_by_user.items() if len(items) >= min_user_items}


def _dropped_hot_items(item_users: dict[str, set[str]], max_item_user_freq: int) -> list[str]:
    return sorted(item_id for item_id, users in item_users.items() if len(users) > max_item_user_freq)


def _filter_sequences_by_item_count(
    *,
    sequences_by_user: dict[str, list[str]],
    item_users: dict[str, set[str]],
    dropped_hot_items: set[str],
    min_src_item_positive_user_count: int,
    min_dst_item_positive_user_count: int,
    min_user_items: int,
    apply_post_item_user_filter: bool = True,
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    item_train_positive_user_counts = {item_id: len(users) for item_id, users in item_users.items()}
    src_eligible_items = {
        item_id
        for item_id, count in item_train_positive_user_counts.items()
        if count >= min_src_item_positive_user_count and item_id not in dropped_hot_items
    }
    dst_eligible_items = {
        item_id
        for item_id, count in item_train_positive_user_counts.items()
        if count >= min_dst_item_positive_user_count and item_id not in dropped_hot_items
    }
    pair_eligible_items = src_eligible_items | dst_eligible_items
    filtered_sequences_by_user: dict[str, list[str]] = {}
    retained_item_count_buckets: Counter[str] = Counter()
    skipped_user_count_below_min_after_item_filter = 0
    for user_id, items in sequences_by_user.items():
        filtered_items = [item_id for item_id in items if item_id in pair_eligible_items]
        retained_item_count_buckets[_count_bucket(len(filtered_items))] += 1
        if len(filtered_items) < min_user_items:
            skipped_user_count_below_min_after_item_filter += 1
            if apply_post_item_user_filter:
                continue
        if filtered_items:
            filtered_sequences_by_user[user_id] = filtered_items
    return filtered_sequences_by_user, {
        "item_train_positive_user_count_source": "train_user_sequences_only_distinct_users",
        "min_src_item_positive_user_count": min_src_item_positive_user_count,
        "min_dst_item_positive_user_count": min_dst_item_positive_user_count,
        "apply_post_item_user_filter": apply_post_item_user_filter,
        "dropped_hot_item_count": len(dropped_hot_items),
        "src_eligible_item_count": len(src_eligible_items),
        "dst_eligible_item_count": len(dst_eligible_items),
        "pair_eligible_item_count": len(pair_eligible_items),
        "dropped_src_item_count_below_min": sum(
            1 for item_id, count in item_train_positive_user_counts.items()
            if count < min_src_item_positive_user_count and item_id not in dropped_hot_items
        ),
        "dropped_dst_item_count_below_min": sum(
            1 for item_id, count in item_train_positive_user_counts.items()
            if count < min_dst_item_positive_user_count and item_id not in dropped_hot_items
        ),
        "skipped_user_count_below_min_after_item_filter": skipped_user_count_below_min_after_item_filter,
        "retained_user_count_after_item_filter": len(filtered_sequences_by_user),
        "retained_positive_item_count_after_item_filter": sum(len(items) for items in filtered_sequences_by_user.values()),
        "retained_item_count_bucket_distribution_after_item_filter": dict(sorted(retained_item_count_buckets.items())),
        "src_eligible_items": sorted(src_eligible_items),
        "dst_eligible_items": sorted(dst_eligible_items),
    }


def _public_item_filter_audit(item_filter_audit: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item_filter_audit.items() if key not in {"src_eligible_items", "dst_eligible_items"}}


def _count_bucket(count: int) -> str:
    if count == 0:
        return "0"
    if count == 1:
        return "1"
    if count == 2:
        return "2"
    if count <= 4:
        return "3_4"
    if count <= 9:
        return "5_9"
    if count <= 19:
        return "10_19"
    if count <= 50:
        return "20_50"
    return "gt_50"


def _build_swing_edges(
    *,
    sequences_by_user: dict[str, list[str]],
    item_users: dict[str, set[str]],
    src_eligible_items: set[str],
    dst_eligible_items: set[str],
    min_pair_support: int,
    per_seed_top_k: int,
    min_score: float,
    score_mode: str,
    alpha: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    user_item_sets = {user_id: set(items) for user_id, items in sequences_by_user.items()}
    user_weights = {
        user_id: 1.0 / math.sqrt(len(items))
        for user_id, items in user_item_sets.items()
        if items
    }
    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    pair_support: dict[str, Counter[str]] = defaultdict(Counter)
    user_pair_overlap_cache: dict[tuple[str, str], int] = {}
    pair_update_count = 0
    standard_user_pair_contribution_count = 0
    for left_item in sorted(item_id for item_id in item_users if item_id in src_eligible_items):
        related: Counter[str] = Counter()
        for user_id in sorted(item_users[left_item]):
            for right_item in user_item_sets.get(user_id, set()):
                if right_item == left_item or right_item not in dst_eligible_items:
                    continue
                related[right_item] += 1
                pair_update_count += 1
        for right_item, co_count in related.items():
            if co_count < min_pair_support:
                continue
            common_users = item_users[left_item] & item_users.get(right_item, set())
            if score_mode == SCORE_MODE_LEGACY_APPROX:
                score = _legacy_approx_swing_score(common_users, user_item_sets, co_count, alpha)
            else:
                score, contribution_count = _datawhale_standard_swing_score(
                    common_users,
                    user_item_sets,
                    user_weights,
                    alpha,
                    user_pair_overlap_cache,
                )
                standard_user_pair_contribution_count += contribution_count
                if contribution_count == 0:
                    continue
            if score >= min_score:
                pair_scores[left_item][right_item] = score
                pair_support[left_item][right_item] = co_count

    edges: list[dict[str, Any]] = []
    for src_item in sorted(pair_scores):
        ranked = sorted(pair_scores[src_item].items(), key=lambda item: (-float(item[1]), item[0]))[:per_seed_top_k]
        for rank, (dst_item, score) in enumerate(ranked, start=1):
            edges.append(
                {
                    "src_item": src_item,
                    "dst_item": dst_item,
                    "score": round(float(score), 6),
                    "rank": rank,
                    "source": "swing_recall",
                }
            )
    build_audit = {
        "pair_update_count": pair_update_count,
        "supported_pair_count": sum(len(scores) for scores in pair_scores.values()),
        "min_pair_support": min_pair_support,
        "per_seed_top_k": per_seed_top_k,
        "min_score": min_score,
        "score_mode": score_mode,
        "alpha": alpha,
        "user_weight_mode": USER_WEIGHT_MODE if score_mode == SCORE_MODE_DATAWHALE_STANDARD else "none",
        "common_user_pair_mode": COMMON_USER_PAIR_MODE if score_mode == SCORE_MODE_DATAWHALE_STANDARD else "not_used",
        "formula_reference": "datawhale_swing" if score_mode == SCORE_MODE_DATAWHALE_STANDARD else "legacy_approximation",
        "user_pair_overlap_cache_size": len(user_pair_overlap_cache),
        "standard_user_pair_contribution_count": standard_user_pair_contribution_count,
        "filter_before_build": True,
        "src_item_filter_applied_before_edge_write": True,
        "dst_item_filter_applied_before_edge_write": True,
        "src_eligible_item_count": len(src_eligible_items),
        "dst_eligible_item_count": len(dst_eligible_items),
    }
    return edges, build_audit


def _legacy_approx_swing_score(common_users: set[str], user_item_sets: dict[str, set[str]], co_count: int, alpha: float) -> float:
    denom = alpha + sum(1.0 / max(1, len(user_item_sets[user_id])) for user_id in common_users)
    return float(co_count) / denom if denom else 0.0


def _datawhale_standard_swing_score(
    common_users: set[str],
    user_item_sets: dict[str, set[str]],
    user_weights: dict[str, float],
    alpha: float,
    user_pair_overlap_cache: dict[tuple[str, str], int],
) -> tuple[float, int]:
    users = sorted(user_id for user_id in common_users if user_id in user_item_sets and user_id in user_weights)
    score = 0.0
    contribution_count = 0
    for index, user_id in enumerate(users):
        user_items = user_item_sets[user_id]
        user_weight = user_weights[user_id]
        for other_user_id in users[index + 1 :]:
            cache_key = (user_id, other_user_id)
            overlap = user_pair_overlap_cache.get(cache_key)
            if overlap is None:
                overlap = len(user_items & user_item_sets[other_user_id])
                user_pair_overlap_cache[cache_key] = overlap
            score += (user_weight * user_weights[other_user_id]) / (alpha + overlap)
            contribution_count += 1
    return score, contribution_count


def _shard_audit(edges: list[dict[str, Any]]) -> dict[str, Any]:
    shard_counts: Counter[str] = Counter(str(edge["src_item"])[:2] or "__" for edge in edges)
    return {
        "strategy": "src_item_prefix_2_audit_only",
        "shard_count": len(shard_counts),
        "max_edges_per_shard": max(shard_counts.values()) if shard_counts else 0,
        "shards": dict(sorted(shard_counts.items())),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    manifest = build_full_train_swing_sidecar(
        clean_manifest_path=Path(args.clean_manifest),
        output_dir=Path(args.output_dir),
        max_item_user_freq=args.max_item_user_freq,
        max_user_items=args.max_user_items,
        min_pair_support=args.min_pair_support,
        per_seed_top_k=args.per_seed_top_k,
        min_score=args.min_score,
        score_mode=args.score_mode,
        alpha=args.alpha,
        min_user_items=args.min_user_items,
        min_src_item_positive_user_count=args.min_src_item_positive_user_count,
        min_dst_item_positive_user_count=args.min_dst_item_positive_user_count,
        pre_filter_users_before_item_count=args.pre_filter_users_before_item_count,
        disable_post_item_user_filter=args.disable_post_item_user_filter,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
        overwrite=args.overwrite,
    )
    print(f"Full-train Swing sidecar status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['source_index_manifest']}")


if __name__ == "__main__":
    main()
