from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    _candidate_row,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _flatten_candidates,
    _merge_rows,
)

SCHEMA_VERSION = "pool500_swing_recall_enhanced_source_v1"
SOURCE = "swing_recall"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_BASELINE_DIR = ROOT / "outputs" / "recall" / "pool500_main_route_direct_recall_full_promoted"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources" / SOURCE
DEFAULT_MIN_FREE_BYTES = 10 * 1024**3
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
    "holdout",
    "valid",
    "test",
    "LOPO",
    "clean_10000",
)
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a pool500 TARGET_SLICE_DIAGNOSTIC Swing recall source.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--baseline-dir", default=str(DEFAULT_BASELINE_DIR))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-graph-users", type=int, default=120000)
    parser.add_argument("--max-items-per-user", type=int, default=80)
    parser.add_argument("--max-item-user-freq", type=int, default=600)
    parser.add_argument("--min-user-items", type=int, default=2)
    parser.add_argument("--min-pair-support", type=int, default=1)
    parser.add_argument("--per-seed-top-k", type=int, default=120)
    parser.add_argument("--seed-window", type=int, default=40)
    parser.add_argument("--per-user", type=int, default=120)
    parser.add_argument("--swing-alpha", type=float, default=1.0)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_swing_recall_enhanced_source(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    baseline_dir: Path = DEFAULT_BASELINE_DIR,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    max_graph_users: int = 120000,
    max_items_per_user: int = 80,
    max_item_user_freq: int = 600,
    min_user_items: int = 2,
    min_pair_support: int = 1,
    per_seed_top_k: int = 120,
    seed_window: int = 40,
    per_user: int = 120,
    swing_alpha: float = 1.0,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    started = perf_counter()
    _validate_parameters(max_graph_users, max_items_per_user, max_item_user_freq, min_user_items, min_pair_support, per_seed_top_k, seed_window, per_user, swing_alpha)
    if enforce_venv:
        _enforce_project_venv()

    clean_manifest_path = clean_manifest_path.resolve()
    baseline_dir = baseline_dir.resolve()
    output_root = output_root.resolve()
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / run_id
    _precheck(clean_manifest_path, baseline_dir, output_dir, min_free_bytes, overwrite)
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free

    clean_manifest = read_json(clean_manifest_path)
    train_sequences_path = _resolve_train_sequences_path(clean_manifest_path, clean_manifest)
    eligible_user_manifest_path = baseline_dir / "eligible_user_manifest.json"
    old_swing_candidates_path = baseline_dir / "sources" / SOURCE / "candidates.jsonl"
    target_users = _load_target_users(eligible_user_manifest_path)
    target_sequences, target_seed_items = _load_target_sequences(train_sequences_path, target_users, max_items_per_user, seed_window)
    graph_sequences, load_audit = _load_graph_sequences(
        train_sequences_path,
        target_seed_items,
        max_graph_users=max_graph_users,
        max_items_per_user=max_items_per_user,
        min_user_items=min_user_items,
    )
    checkpoint_path = output_dir / "graph_user_sequences.checkpoint.jsonl"
    write_jsonl(
        checkpoint_path,
        [
            {"user_id": user_id, "recent_positive_item_sequence": items}
            for user_id, items in sorted(graph_sequences.items())
        ],
    )

    item_users = _build_item_users(graph_sequences)
    dropped_hot_items = sorted(item_id for item_id, users in item_users.items() if len(users) > max_item_user_freq)
    allowed_item_users = {item_id: users for item_id, users in item_users.items() if item_id not in set(dropped_hot_items)}
    edges, swing_build_audit = _build_edges(
        graph_sequences=graph_sequences,
        item_users=allowed_item_users,
        dropped_hot_items=set(dropped_hot_items),
        min_pair_support=min_pair_support,
        per_seed_top_k=per_seed_top_k,
        alpha=swing_alpha,
    )
    edges_path = output_dir / "swing_recall_edges.jsonl"
    write_jsonl(edges_path, edges)
    edge_index = _edge_index(edges)

    old_candidates_by_user = _load_old_candidates(old_swing_candidates_path)
    candidates_by_user: dict[str, list[dict[str, Any]]] = {}
    enhanced_only_by_user: dict[str, list[dict[str, Any]]] = {}
    for user_id in target_users:
        old_rows = old_candidates_by_user.get(user_id, [])
        old_items = {row["item_id"] for row in old_rows}
        new_rows = _candidate_rows_for_user(
            user_id=user_id,
            sequence=target_sequences.get(user_id, []),
            edge_index=edge_index,
            existing_items=old_items,
            seed_window=seed_window,
            per_seed=per_seed_top_k,
            per_user=per_user,
        )
        enhanced_only_by_user[user_id] = new_rows
        candidates_by_user[user_id] = _merge_rows(old_rows, new_rows, per_user)

    candidates_path = output_dir / "candidates.jsonl"
    enhanced_only_path = output_dir / "enhanced_only_candidates.jsonl"
    write_jsonl(candidates_path, _flatten_candidates(candidates_by_user))
    write_jsonl(enhanced_only_path, _flatten_candidates(enhanced_only_by_user))

    coverage_audit = _coverage_audit(target_users, candidates_by_user, enhanced_only_by_user, edges, target_sequences, old_candidates_by_user)
    undercoverage_audit = _undercoverage_audit(target_users, candidates_by_user, enhanced_only_by_user, target_sequences, edge_index)
    no_holdout_audit = _no_holdout_audit(clean_manifest_path, train_sequences_path, eligible_user_manifest_path, old_swing_candidates_path)
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "source_status": "TARGET_SLICE_DIAGNOSTIC",
        "heavy_job": False,
        "checkpoint_enabled": True,
        "checkpoint_path": str(checkpoint_path),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "min_free_bytes": min_free_bytes,
        "max_graph_users": max_graph_users,
        "graph_user_count": len(graph_sequences),
        "target_user_count": len(target_users),
        "target_sequence_user_count": len(target_sequences),
        "target_seed_item_count": len(target_seed_items),
        "item_count_before_hot_drop": len(item_users),
        "item_count_after_hot_drop": len(allowed_item_users),
        "dropped_hot_item_count": len(dropped_hot_items),
        "edge_count": len(edges),
        "load_audit": load_audit,
        "swing_build_audit": swing_build_audit,
        "bounded_controls": {
            "max_items_per_user": max_items_per_user,
            "max_item_user_freq": max_item_user_freq,
            "min_user_items": min_user_items,
            "min_pair_support": min_pair_support,
            "per_seed_top_k": per_seed_top_k,
            "seed_window": seed_window,
            "per_user": per_user,
            "swing_alpha": swing_alpha,
        },
    }
    method_dataset_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "source_status": "TARGET_SLICE_DIAGNOSTIC",
        "dataset_policy": "method_specific_swing_pair_graph_dataset",
        "train_only": True,
        "target_user_manifest_path": str(eligible_user_manifest_path),
        "target_user_count": len(target_users),
        "train_user_sequences_path": str(train_sequences_path),
        "graph_user_selection": "train users with target seed overlap, bounded by max_graph_users",
        "forbidden_data_sources": list(FORBIDDEN_PATH_PARTS),
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "outputs_required": [
            "method_dataset_manifest.json",
            "source_index_manifest.json",
            "candidates.jsonl",
            "coverage_audit.json",
            "undercoverage_audit.json",
            "resource_audit.json",
            "no_holdout_audit.json",
        ],
    }
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "source_status": "TARGET_SLICE_DIAGNOSTIC",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "output_dir": str(output_dir),
        "run_id": run_id,
        "runtime_seconds": round(perf_counter() - started, 6),
        "edge_count": len(edges),
        "seed_count": len(edge_index),
        "candidate_row_count": coverage_audit["candidate_row_count"],
        "user_coverage_count": coverage_audit["user_coverage_count"],
        "generation_config_overrides": {
            "swing_per_user": min(per_user, 120),
            "swing_per_seed": min(per_seed_top_k, 120),
        },
        "required_artifacts": {
            "method_dataset_manifest": "method_dataset_manifest.json",
            "source_index_manifest": "source_index_manifest.json",
            "swing_recall_edges": "swing_recall_edges.jsonl",
            "candidates": "candidates.jsonl",
            "enhanced_only_candidates": "enhanced_only_candidates.jsonl",
            "coverage_audit": "coverage_audit.json",
            "undercoverage_audit": "undercoverage_audit.json",
            "resource_audit": "resource_audit.json",
            "no_holdout_audit": "no_holdout_audit.json",
        },
    }

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    source_index_manifest["artifact_signatures"] = {
        "method_dataset_manifest": _file_signature(output_dir / "method_dataset_manifest.json"),
        "swing_recall_edges": _file_signature(edges_path),
        "candidates": _file_signature(candidates_path),
        "coverage_audit": _file_signature(output_dir / "coverage_audit.json"),
        "undercoverage_audit": _file_signature(output_dir / "undercoverage_audit.json"),
        "resource_audit": _file_signature(output_dir / "resource_audit.json"),
        "no_holdout_audit": _file_signature(output_dir / "no_holdout_audit.json"),
    }
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _validate_parameters(*values: int | float) -> None:
    for value in values:
        if value <= 0:
            raise ValueError("all numeric limits must be positive")


def _precheck(clean_manifest_path: Path, baseline_dir: Path, output_dir: Path, min_free_bytes: int, overwrite: bool) -> None:
    for path in (clean_manifest_path, baseline_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(part.lower() in lowered for part in FORBIDDEN_PATH_PARTS if part not in {"valid", "test"}):
            raise ValueError(f"Forbidden path for swing_recall pool500 source: {path}")
    required = [
        clean_manifest_path,
        baseline_dir / "eligible_user_manifest.json",
        baseline_dir / "sources" / SOURCE / "candidates.jsonl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input files: " + ", ".join(missing))
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"Free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _resolve_train_sequences_path(clean_manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path") or manifest.get("outputs", {}).get("train_user_sequences_path")
    if not raw_path:
        raise ValueError("Clean manifest must declare train_user_sequences_path")
    path = Path(str(raw_path))
    resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    lowered = str(resolved).replace("\\", "/").lower()
    if resolved.name != "user_sequences.train.jsonl" or any(name.lower() in lowered for name in FORBIDDEN_CANDIDATE_FILES):
        raise ValueError(f"swing_recall must read train user sequences only, got: {resolved}")
    if not resolved.is_file():
        fallback = (clean_manifest_path.parent / path).resolve()
        if fallback.is_file():
            return fallback
        raise FileNotFoundError(f"Missing train sequence file: {resolved}")
    return resolved


def _load_target_users(path: Path) -> list[str]:
    payload = read_json(path)
    users = [str(user_id) for user_id in payload.get("eligible_user_ids", []) if user_id]
    if not users:
        raise ValueError("eligible_user_manifest has no eligible_user_ids")
    return users


def _load_target_sequences(path: Path, target_users: list[str], max_items_per_user: int, seed_window: int) -> tuple[dict[str, list[str]], set[str]]:
    target_set = set(target_users)
    sequences: dict[str, list[str]] = {}
    seed_items: set[str] = set()
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        if user_id not in target_set:
            continue
        raw = row.get("recent_strong_positive_item_sequence") or row.get("recent_positive_item_sequence") or row.get("recent_item_sequence") or []
        items = list(dict.fromkeys(str(item) for item in raw if item))[-max_items_per_user:]
        sequences[user_id] = items
        seed_items.update(items[-seed_window:])
        if len(sequences) == len(target_set):
            break
    return sequences, seed_items


def _load_graph_sequences(path: Path, target_seed_items: set[str], *, max_graph_users: int, max_items_per_user: int, min_user_items: int) -> tuple[dict[str, list[str]], dict[str, Any]]:
    graph_sequences: dict[str, list[str]] = {}
    scanned_users = 0
    overlap_user_count = 0
    skipped_short_users = 0
    for row in iter_jsonl(path):
        raw = row.get("recent_strong_positive_item_sequence") or row.get("recent_positive_item_sequence") or row.get("recent_item_sequence") or []
        items = list(dict.fromkeys(str(item) for item in raw if item))[-max_items_per_user:]
        if len(items) < min_user_items:
            skipped_short_users += 1
            continue
        scanned_users += 1
        if target_seed_items and not (set(items) & target_seed_items):
            continue
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        overlap_user_count += 1
        graph_sequences[user_id] = items
        if len(graph_sequences) >= max_graph_users:
            break
    return graph_sequences, {
        "train_users_scanned_with_min_items": scanned_users,
        "overlap_user_count": overlap_user_count,
        "retained_graph_user_count": len(graph_sequences),
        "skipped_short_users": skipped_short_users,
        "truncated_by_max_graph_users": len(graph_sequences) >= max_graph_users,
    }


def _build_item_users(sequences_by_user: dict[str, list[str]]) -> dict[str, set[str]]:
    item_users: dict[str, set[str]] = defaultdict(set)
    for user_id, items in sequences_by_user.items():
        for item_id in items:
            item_users[item_id].add(user_id)
    return dict(item_users)


def _build_edges(
    *,
    graph_sequences: dict[str, list[str]],
    item_users: dict[str, set[str]],
    dropped_hot_items: set[str],
    min_pair_support: int,
    per_seed_top_k: int,
    alpha: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    user_item_sets = {
        user_id: {item_id for item_id in items if item_id not in dropped_hot_items}
        for user_id, items in graph_sequences.items()
    }
    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    pair_support: dict[str, Counter[str]] = defaultdict(Counter)
    pair_update_count = 0
    for left_item in sorted(item_users):
        related: Counter[str] = Counter()
        for user_id in sorted(item_users[left_item]):
            for right_item in user_item_sets.get(user_id, set()):
                if right_item == left_item:
                    continue
                related[right_item] += 1
                pair_update_count += 1
        for right_item, co_count in related.items():
            if co_count < min_pair_support:
                continue
            common_users = item_users[left_item] & item_users.get(right_item, set())
            denom = alpha + sum(1.0 / max(1, len(user_item_sets[user_id])) for user_id in common_users)
            score = float(co_count) / denom if denom else 0.0
            if score > 0:
                pair_scores[left_item][right_item] = score
                pair_support[left_item][right_item] = co_count
    edges: list[dict[str, Any]] = []
    for src_item in sorted(pair_scores):
        ranked = sorted(pair_scores[src_item].items(), key=lambda item: (-float(item[1]), item[0]))[:per_seed_top_k]
        for rank, (dst_item, score) in enumerate(ranked, start=1):
            edges.append({"src_item": src_item, "dst_item": dst_item, "item_id": dst_item, "score": round(float(score), 6), "rank": rank, "source": SOURCE})
    return edges, {
        "pair_update_count": pair_update_count,
        "supported_pair_count": sum(len(scores) for scores in pair_scores.values()),
        "seed_count": len(pair_scores),
        "min_pair_support": min_pair_support,
        "per_seed_top_k": per_seed_top_k,
        "swing_alpha": alpha,
    }


def _edge_index(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        index[str(edge["src_item"])].append({"item_id": str(edge["dst_item"]), "score": float(edge["score"]), "rank": int(edge["rank"]), "seed_item_id": str(edge["src_item"])})
    return dict(index)


def _load_old_candidates(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if not user_id or not item_id:
            continue
        scores = row.get("source_scores") or row.get("metadata", {}).get("source_scores") or {SOURCE: row.get("score", 0.0)}
        by_user[user_id].append(_candidate_row(user_id, item_id, [SOURCE], {SOURCE: float(scores.get(SOURCE, row.get("score", 0.0)) or 0.0)}, str(row.get("category", "")), {"reason": "old_promoted_swing_recall_baseline"}))
    for rows in by_user.values():
        rows.sort(key=lambda item: int(item.get("rank", 0) or 0))
    return dict(by_user)


def _candidate_rows_for_user(*, user_id: str, sequence: list[str], edge_index: dict[str, list[dict[str, Any]]], existing_items: set[str], seed_window: int, per_seed: int, per_user: int) -> list[dict[str, Any]]:
    seen_items = set(sequence)
    seeds = list(dict.fromkeys(reversed(sequence[-seed_window:])))
    by_item: dict[str, dict[str, Any]] = {}
    for seed_rank, seed in enumerate(seeds):
        for candidate in edge_index.get(seed, [])[:per_seed]:
            item_id = str(candidate.get("item_id", ""))
            if not item_id or item_id in seen_items or item_id in existing_items:
                continue
            score = round(float(candidate.get("score", 0.0) or 0.0), 6)
            current = by_item.get(item_id)
            if current is None or score > float(current["score"]):
                by_item[item_id] = {**candidate, "score": score, "seed_rank": seed_rank}
    rows = sorted(by_item.values(), key=lambda item: (-float(item["score"]), str(item["item_id"])))[:per_user]
    return [
        _candidate_row(
            user_id,
            str(row["item_id"]),
            [SOURCE],
            {SOURCE: round(float(row["score"]), 6)},
            "",
            {"reason": "pool500_target_slice_swing_item_pair", "seed_item_id": row.get("seed_item_id"), "source_rank": row.get("rank"), "seed_rank": row.get("seed_rank")},
        )
        for row in rows
    ]


def _coverage_audit(target_users: list[str], candidates_by_user: dict[str, list[dict[str, Any]]], enhanced_only_by_user: dict[str, list[dict[str, Any]]], edges: list[dict[str, Any]], target_sequences: dict[str, list[str]], old_candidates_by_user: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    counts = [len(candidates_by_user.get(user_id, [])) for user_id in target_users]
    enhanced_counts = [len(enhanced_only_by_user.get(user_id, [])) for user_id in target_users]
    old_counts = [len(old_candidates_by_user.get(user_id, [])) for user_id in target_users]
    graph_seed_items = {str(edge["src_item"]) for edge in edges}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "source_status": "TARGET_SLICE_DIAGNOSTIC",
        "target_user_count": len(target_users),
        "candidate_row_count": sum(counts),
        "enhanced_only_candidate_row_count": sum(enhanced_counts),
        "old_promoted_candidate_row_count": sum(old_counts),
        "user_coverage_count": sum(1 for count in counts if count > 0),
        "enhanced_only_user_coverage_count": sum(1 for count in enhanced_counts if count > 0),
        "old_promoted_user_coverage_count": sum(1 for count in old_counts if count > 0),
        "candidate_count_distribution": _distribution(counts),
        "enhanced_only_candidate_count_distribution": _distribution(enhanced_counts),
        "old_promoted_candidate_count_distribution": _distribution(old_counts),
        "swing_pair_coverage": {
            "edge_count": len(edges),
            "seed_count": len(graph_seed_items),
            "target_seed_hit_user_count": sum(1 for items in target_sequences.values() if graph_seed_items & set(items)),
        },
        "item_graph_coverage": {
            "unique_src_item_count": len(graph_seed_items),
            "unique_dst_item_count": len({edge["dst_item"] for edge in edges}),
        },
    }


def _undercoverage_audit(target_users: list[str], candidates_by_user: dict[str, list[dict[str, Any]]], enhanced_only_by_user: dict[str, list[dict[str, Any]]], target_sequences: dict[str, list[str]], edge_index: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    users: list[dict[str, Any]] = []
    for user_id in target_users:
        count = len(candidates_by_user.get(user_id, []))
        enhanced_count = len(enhanced_only_by_user.get(user_id, []))
        if count > 0:
            continue
        sequence = target_sequences.get(user_id, [])
        seed_hit_count = sum(1 for item_id in sequence if item_id in edge_index)
        if not sequence:
            reason = "missing_train_sequence"
        elif seed_hit_count == 0:
            reason = "no_seed_item_in_swing_graph"
        elif enhanced_count == 0:
            reason = "swing_neighbors_filtered_by_seen_or_existing_items"
        else:
            reason = "unknown"
        reasons[reason] += 1
        users.append({"user_id": user_id, "reason": reason, "train_sequence_length": len(sequence), "seed_hit_count": seed_hit_count})
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "undercovered_user_count": len(users),
        "reason_counts": dict(sorted(reasons.items())),
        "users": users[:200],
    }


def _no_holdout_audit(clean_manifest_path: Path, train_sequences_path: Path, eligible_user_manifest_path: Path, old_swing_candidates_path: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "source_status": "TARGET_SLICE_DIAGNOSTIC",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "read_files": [str(clean_manifest_path), str(train_sequences_path), str(eligible_user_manifest_path), str(old_swing_candidates_path)],
        "forbidden_files_not_read": [str(train_sequences_path.parent / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "valid_test_holdout_usage": "not_read",
        "source_signatures": {
            "clean_manifest": _file_signature(clean_manifest_path),
            "train_user_sequences": _file_signature(train_sequences_path),
            "eligible_user_manifest": _file_signature(eligible_user_manifest_path),
            "old_swing_candidates": _file_signature(old_swing_candidates_path),
        },
    }


def _distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    ordered = sorted(values)
    p50 = ordered[len(ordered) // 2]
    p90 = ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.9)))]
    return {"min": ordered[0], "p50": p50, "p90": p90, "max": ordered[-1], "avg": round(sum(values) / len(values), 6)}


def main() -> None:
    args = parse_args()
    manifest = build_pool500_swing_recall_enhanced_source(
        clean_manifest_path=Path(args.clean_manifest),
        baseline_dir=Path(args.baseline_dir),
        output_root=Path(args.output_root),
        run_id=args.run_id,
        max_graph_users=args.max_graph_users,
        max_items_per_user=args.max_items_per_user,
        max_item_user_freq=args.max_item_user_freq,
        min_user_items=args.min_user_items,
        min_pair_support=args.min_pair_support,
        per_seed_top_k=args.per_seed_top_k,
        seed_window=args.seed_window,
        per_user=args.per_user,
        swing_alpha=args.swing_alpha,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
        overwrite=args.overwrite,
    )
    print(json.dumps({"status": manifest["status"], "output_dir": manifest["output_dir"], "source_index_manifest": str(Path(manifest["output_dir"]) / "source_index_manifest.json")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
