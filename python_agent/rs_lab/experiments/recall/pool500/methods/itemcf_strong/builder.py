from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS, method_output_dir

ROOT = Path(__file__).resolve().parents[6]
SOURCE = "itemcf_strong"
SCHEMA_VERSION = "pool500_itemcf_strong_method_source_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources"
FORBIDDEN_PATH_PARTS = ("holdout", "valid", "test", "lopo", "clean_10000", "10000", "pool1000")
FORBIDDEN_INPUT_NAMES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def build_itemcf_strong_method_source(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    output_dir: Path | None = None,
    run_id: str | None = None,
    target_user_limit: int = 500,
    batch_size: int = 50,
    max_items_per_user: int = 50,
    max_item_user_freq: int = 5000,
    top_k_per_seed: int = 100,
    candidate_limit_per_user: int = 500,
    min_free_bytes: int = 10 * 1024**3,
    overwrite: bool = False,
    enforce_venv: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    config = config or {}
    clean_manifest_path = Path(str(config.get("clean_manifest") or config.get("clean_manifest_path") or clean_manifest_path))
    output_root = Path(str(config.get("output_root") or output_root))
    target_user_limit = _config_int(config, "target_user_limit", target_user_limit)
    batch_size = _config_int(config, "batch_size", _config_int(config, "target_batch_size", batch_size))
    max_items_per_user = _config_int(config, "max_items_per_user", _config_int(config, "max_seed_items_per_user", max_items_per_user))
    max_item_user_freq = _config_int(config, "max_item_user_freq", max_item_user_freq)
    top_k_per_seed = _config_int(config, "top_k_per_seed", _config_int(config, "candidate_top_k_per_user", top_k_per_seed))
    candidate_limit_per_user = _config_int(config, "candidate_limit_per_user", _config_int(config, "candidate_top_k_per_user", candidate_limit_per_user))
    min_free_bytes = _config_int(config, "min_free_bytes", min_free_bytes)
    if enforce_venv:
        _enforce_project_venv()
    _validate_positive(
        target_user_limit=target_user_limit,
        batch_size=batch_size,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        top_k_per_seed=top_k_per_seed,
        candidate_limit_per_user=candidate_limit_per_user,
        min_free_bytes=min_free_bytes,
    )
    clean_manifest_path = clean_manifest_path.resolve()
    output_root = output_root.resolve()
    run_id = run_id or str(config.get("run_id") or _default_run_id())
    output_dir = (output_dir if output_dir is not None else method_output_dir(output_root, SOURCE, run_id)).resolve()
    _precheck_paths(clean_manifest_path, output_dir, min_free_bytes, overwrite)

    clean_manifest = read_json(clean_manifest_path)
    train_sequences_path = _resolve_train_sequences_path(clean_manifest_path, clean_manifest)
    clean_signature = _file_signature(clean_manifest_path)
    train_signature = _file_signature(train_sequences_path)
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir)).free

    target_sequences = _load_target_sequences(train_sequences_path, target_user_limit)
    target_user_ids = [str(row["user_id"]) for row in target_sequences]
    target_seed_by_user = {
        str(row["user_id"]): _recent_unique_items(row.get("recent_strong_positive_item_sequence"), max_items_per_user)
        for row in target_sequences
    }
    seen_items_by_user = {
        str(row["user_id"]): set(_recent_unique_items(row.get("recent_positive_item_sequence"), max_items_per_user * 2))
        | set(target_seed_by_user[str(row["user_id"])])
        for row in target_sequences
    }
    target_seed_items = {item for items in target_seed_by_user.values() for item in items}

    scan = _scan_train_for_target_seed_edges(
        train_sequences_path=train_sequences_path,
        target_seed_items=target_seed_items,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        top_k_per_seed=top_k_per_seed,
    )
    checkpoint_dir = output_dir / "batch_checkpoints"
    checkpoint_dir.mkdir()
    edges_path = output_dir / "itemcf_strong_edges.jsonl"
    _write_edges(edges_path, scan["outgoing_edges"])
    edge_rows = _load_edges_by_seed(edges_path)
    candidates_path = output_dir / "candidates.jsonl"
    candidate_stats = _write_candidates(
        candidates_path=candidates_path,
        target_user_ids=target_user_ids,
        target_seed_by_user=target_seed_by_user,
        seen_items_by_user=seen_items_by_user,
        edge_rows=edge_rows,
        candidate_limit_per_user=candidate_limit_per_user,
    )
    checkpoint_manifests = _write_batch_checkpoints(
        checkpoint_dir=checkpoint_dir,
        batch_size=batch_size,
        target_user_ids=target_user_ids,
        candidate_count_by_user=candidate_stats["candidate_count_by_user"],
        seed_hit_by_user=candidate_stats["seed_hit_by_user"],
        strong_edge_hit_by_user=candidate_stats["strong_edge_hit_by_user"],
    )

    edge_signature = _file_signature(edges_path)
    candidate_signature = _file_signature(candidates_path)
    forbidden_inputs = [str(train_sequences_path.parent / name) for name in FORBIDDEN_INPUT_NAMES]
    strong_edge_quality = _strong_edge_quality(scan["edge_quality_values"])
    per_user_summary = _per_user_summary(candidate_stats["candidate_count_by_user"], target_user_ids)
    source_index_manifest_path = output_dir / "source_index_manifest.json"
    method_dataset_manifest_path = output_dir / "method_dataset_manifest.json"
    coverage_audit_path = output_dir / "coverage_audit.json"
    undercoverage_audit_path = output_dir / "undercoverage_audit.json"
    resource_audit_path = output_dir / "resource_audit.json"
    no_holdout_audit_path = output_dir / "no_holdout_audit.json"

    common_governance = _governance_fields()
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        **common_governance,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "clean_manifest_sha256": clean_signature["sha256"],
        "train_sequence_sha256": train_signature["sha256"],
        "edges_path": str(edges_path),
        "candidates_path": str(candidates_path),
        "edge_signature": edge_signature,
        "candidate_signature": candidate_signature,
        "target_user_count": len(target_user_ids),
        "target_seed_count": len(target_seed_items),
        "seed_hit_count": candidate_stats["seed_hit_count"],
        "strong_edge_hit_count": candidate_stats["strong_edge_hit_count"],
        "strong_edge_quality": strong_edge_quality,
        "candidate_user_count": candidate_stats["user_coverage_count"],
        "user_coverage_count": candidate_stats["user_coverage_count"],
        "candidate_total_count": candidate_stats["candidate_row_count"],
        "candidate_row_count": candidate_stats["candidate_row_count"],
        "edge_count": edge_signature["row_count"],
        "row_count": candidate_stats["candidate_row_count"],
        "per_user_candidate_count": per_user_summary,
        "generation_config_overrides": {
            "itemcf_strong_per_seed": top_k_per_seed,
            "itemcf_recent_strong_window": max_items_per_user,
        },
        "outputs": {
            "method_dataset_manifest": str(method_dataset_manifest_path),
            "source_index_manifest": str(source_index_manifest_path),
            "candidates": str(candidates_path),
            "coverage_audit": str(coverage_audit_path),
            "undercoverage_audit": str(undercoverage_audit_path),
            "resource_audit": str(resource_audit_path),
            "no_holdout_audit": str(no_holdout_audit_path),
            "edges": str(edges_path),
            "batch_checkpoints": str(checkpoint_dir),
        },
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    method_dataset_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": "DIAGNOSTIC_ONLY",
        "dataset_policy": "target500_train_only_high_confidence_seed_strong_item_edges",
        "train_only": True,
        **common_governance,
        "run_id": run_id,
        "target_user_count": len(target_user_ids),
        "target_user_ids_sha256": hashlib.sha256("\n".join(target_user_ids).encode("utf-8")).hexdigest(),
        "seed_sequence_field": "recent_strong_positive_item_sequence",
        "positive_history_field_for_seen_filter": "recent_positive_item_sequence",
        "clean_manifest_path": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "read_files": [str(clean_manifest_path), str(train_sequences_path)],
        "forbidden_inputs": forbidden_inputs,
        "required_outputs": list(REQUIRED_SOURCE_OUTPUTS),
    }
    insufficiency_reasons = _insufficiency_reasons(candidate_stats["reason_counts"])
    coverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": "DIAGNOSTIC_ONLY",
        "train_only": True,
        **common_governance,
        "target_user_count": len(target_user_ids),
        "seed_hit_count": candidate_stats["seed_hit_count"],
        "strong_edge_hit_count": candidate_stats["strong_edge_hit_count"],
        "strong_edge_quality": strong_edge_quality,
        "user_coverage_count": candidate_stats["user_coverage_count"],
        "candidate_row_count": candidate_stats["candidate_row_count"],
        "per_user_candidate_count": per_user_summary,
        "users_with_no_strong_seed": candidate_stats["reason_counts"].get("no_strong_seed", 0),
        "users_with_seed_but_no_strong_edge": candidate_stats["reason_counts"].get("seed_without_strong_edge", 0),
        "users_with_edges_but_no_new_candidate": candidate_stats["reason_counts"].get("strong_edges_only_seen_items", 0),
        "reasons_for_insufficient_seed_or_strong_edge": insufficiency_reasons,
    }
    undercoverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": "DIAGNOSTIC_ONLY",
        "train_only": True,
        **common_governance,
        "undercovered_user_count": len(target_user_ids) - candidate_stats["user_coverage_count"],
        "users_below_500_count": sum(1 for count in candidate_stats["candidate_count_by_user"].values() if count < candidate_limit_per_user),
        "reason_counts": dict(sorted(candidate_stats["reason_counts"].items())),
        "reasons_for_insufficient_seed_or_strong_edge": insufficiency_reasons,
        "reason_by_user_sample": candidate_stats["reason_by_user_sample"],
        "candidate_limit_per_user": candidate_limit_per_user,
        "per_user_candidate_count": per_user_summary,
    }
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": "DIAGNOSTIC_ONLY",
        "train_only": True,
        **common_governance,
        "heavy_job": True,
        "batch_size": batch_size,
        "checkpoint_enabled": True,
        "checkpoint_dir": str(checkpoint_dir),
        "checkpoint_count": len(checkpoint_manifests),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir)).free,
        "min_free_bytes": min_free_bytes,
        "users_scanned": scan["users_scanned"],
        "users_used_for_edges": scan["users_used_for_edges"],
        "target_seed_count": len(target_seed_items),
        "unique_pair_count": scan["unique_pair_count"],
        "hot_item_count": len(scan["hot_items"]),
        "edge_count": edge_signature["row_count"],
        "candidate_row_count": candidate_stats["candidate_row_count"],
    }
    no_holdout_audit = {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": "DIAGNOSTIC_ONLY",
        "train_only": True,
        **common_governance,
        "read_files": [str(clean_manifest_path), str(train_sequences_path)],
        "forbidden_inputs": forbidden_inputs,
        "uses_holdout": False,
        "uses_valid": False,
        "uses_test": False,
        "uses_lopo": False,
        "uses_clean_10000": False,
        "uses_pool1000": False,
    }

    write_json(method_dataset_manifest_path, method_dataset_manifest)
    write_json(source_index_manifest_path, source_index_manifest)
    write_json(coverage_audit_path, coverage_audit)
    write_json(undercoverage_audit_path, undercoverage_audit)
    write_json(resource_audit_path, resource_audit)
    write_json(no_holdout_audit_path, no_holdout_audit)
    return source_index_manifest


def _scan_train_for_target_seed_edges(
    *,
    train_sequences_path: Path,
    target_seed_items: set[str],
    max_items_per_user: int,
    max_item_user_freq: int,
    top_k_per_seed: int,
) -> dict[str, Any]:
    item_user_count: Counter[str] = Counter()
    contributing_sequences: list[list[str]] = []
    users_scanned = 0
    for row in iter_jsonl(train_sequences_path):
        users_scanned += 1
        items = _recent_unique_items(row.get("recent_strong_positive_item_sequence"), max_items_per_user)
        if not items or not (set(items) & target_seed_items):
            continue
        unique_items = sorted(set(items))
        contributing_sequences.append(unique_items)
        item_user_count.update(unique_items)
    hot_items = {item for item, count in item_user_count.items() if count > max_item_user_freq}
    pair_count: Counter[tuple[str, str]] = Counter()
    users_used_for_edges = 0
    for items in contributing_sequences:
        filtered = [item for item in items if item not in hot_items]
        if len(filtered) < 2:
            continue
        users_used_for_edges += 1
        for item_a, item_b in combinations(filtered, 2):
            if item_a in target_seed_items or item_b in target_seed_items:
                pair_count[(item_a, item_b)] += 1
    outgoing: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    edge_quality_values = []
    for (item_a, item_b), cooc_cnt in pair_count.items():
        denom = (item_user_count[item_a] * item_user_count[item_b]) ** 0.5
        score = round(cooc_cnt / denom, 6) if denom else 0.0
        edge_quality_values.append(score)
        for src_item, dst_item in ((item_a, item_b), (item_b, item_a)):
            if src_item not in target_seed_items:
                continue
            outgoing[src_item].append(
                {
                    "src_item": src_item,
                    "dst_item": dst_item,
                    "score": score,
                    "source": SOURCE,
                    "canonical_source": SOURCE,
                    "label_variant": "recent_strong_positive_item_sequence",
                    "cooc_cnt": cooc_cnt,
                    "src_user_cnt": item_user_count[src_item],
                    "dst_user_cnt": item_user_count[dst_item],
                }
            )
    for src_item, rows in list(outgoing.items()):
        outgoing[src_item] = sorted(rows, key=lambda row: (-row["score"], -row["cooc_cnt"], row["dst_item"]))[:top_k_per_seed]
    return {
        "outgoing_edges": outgoing,
        "edge_quality_values": edge_quality_values,
        "users_scanned": users_scanned,
        "users_used_for_edges": users_used_for_edges,
        "unique_pair_count": len(pair_count),
        "hot_items": sorted(hot_items),
    }


def _write_edges(path: Path, outgoing_edges: dict[str, list[dict[str, Any]]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for src_item in sorted(outgoing_edges):
            for rank, row in enumerate(outgoing_edges[src_item], start=1):
                handle.write(json.dumps({**row, "rank": rank}, ensure_ascii=False) + "\n")


def _load_edges_by_seed(path: Path) -> dict[str, list[dict[str, Any]]]:
    rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in iter_jsonl(path):
        rows[str(row["src_item"])].append(row)
    return rows


def _write_candidates(
    *,
    candidates_path: Path,
    target_user_ids: list[str],
    target_seed_by_user: dict[str, list[str]],
    seen_items_by_user: dict[str, set[str]],
    edge_rows: dict[str, list[dict[str, Any]]],
    candidate_limit_per_user: int,
) -> dict[str, Any]:
    candidate_count_by_user: dict[str, int] = {}
    seed_hit_by_user: dict[str, int] = {}
    strong_edge_hit_by_user: dict[str, int] = {}
    reason_counts: Counter[str] = Counter()
    reason_by_user_sample: list[dict[str, Any]] = []
    candidate_row_count = 0
    user_coverage_count = 0
    seed_hit_count = 0
    strong_edge_hit_count = 0
    with candidates_path.open("w", encoding="utf-8") as handle:
        for user_id in target_user_ids:
            seeds = target_seed_by_user.get(user_id, [])
            seed_hits = [seed for seed in seeds if seed in edge_rows]
            edges = [edge for seed in seed_hits for edge in edge_rows[seed]]
            seen = seen_items_by_user.get(user_id, set())
            deduped: dict[str, dict[str, Any]] = {}
            for edge in edges:
                item_id = str(edge["dst_item"])
                if item_id in seen:
                    continue
                previous = deduped.get(item_id)
                if previous is None or (float(edge["score"]) > float(previous["score"])):
                    deduped[item_id] = edge
            ranked_edges = sorted(deduped.values(), key=lambda row: (-float(row["score"]), -int(row["cooc_cnt"]), str(row["dst_item"])))[:candidate_limit_per_user]
            seed_hit_by_user[user_id] = len(seed_hits)
            strong_edge_hit_by_user[user_id] = len(edges)
            seed_hit_count += len(seed_hits)
            strong_edge_hit_count += len(edges)
            candidate_count_by_user[user_id] = len(ranked_edges)
            if ranked_edges:
                user_coverage_count += 1
            else:
                reason = _undercoverage_reason(seeds, seed_hits, edges)
                reason_counts[reason] += 1
                if len(reason_by_user_sample) < 50:
                    reason_by_user_sample.append({"user_id": user_id, "reason": reason, "seed_count": len(seeds), "seed_hit_count": len(seed_hits), "strong_edge_hit_count": len(edges)})
            for rank, edge in enumerate(ranked_edges, start=1):
                handle.write(
                    json.dumps(
                        {
                            "user_id": user_id,
                            "item_id": edge["dst_item"],
                            "source": SOURCE,
                            "sources": [SOURCE],
                            "score": float(edge["score"]),
                            "rank": rank,
                            "metadata": {
                                "src_item": edge["src_item"],
                                "cooc_cnt": edge["cooc_cnt"],
                                "src_user_cnt": edge["src_user_cnt"],
                                "dst_user_cnt": edge["dst_user_cnt"],
                                "edge_rank": edge["rank"],
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                candidate_row_count += 1
    return {
        "candidate_count_by_user": candidate_count_by_user,
        "seed_hit_by_user": seed_hit_by_user,
        "strong_edge_hit_by_user": strong_edge_hit_by_user,
        "reason_counts": reason_counts,
        "reason_by_user_sample": reason_by_user_sample,
        "candidate_row_count": candidate_row_count,
        "user_coverage_count": user_coverage_count,
        "seed_hit_count": seed_hit_count,
        "strong_edge_hit_count": strong_edge_hit_count,
    }


def _write_batch_checkpoints(
    *,
    checkpoint_dir: Path,
    batch_size: int,
    target_user_ids: list[str],
    candidate_count_by_user: dict[str, int],
    seed_hit_by_user: dict[str, int],
    strong_edge_hit_by_user: dict[str, int],
) -> list[dict[str, Any]]:
    manifests = []
    for batch_index, start in enumerate(range(0, len(target_user_ids), batch_size)):
        user_ids = target_user_ids[start : start + batch_size]
        manifest = {
            "schema_version": f"{SCHEMA_VERSION}.batch_checkpoint",
            "status": "PASS",
            "source": SOURCE,
            "batch_index": batch_index,
            "user_count": len(user_ids),
            "candidate_row_count": sum(candidate_count_by_user[user_id] for user_id in user_ids),
            "seed_hit_count": sum(seed_hit_by_user[user_id] for user_id in user_ids),
            "strong_edge_hit_count": sum(strong_edge_hit_by_user[user_id] for user_id in user_ids),
        }
        write_json(checkpoint_dir / f"itemcf_strong_batch_{batch_index:05d}.json", manifest)
        manifests.append(manifest)
    return manifests


def _undercoverage_reason(seeds: list[str], seed_hits: list[str], edges: list[dict[str, Any]]) -> str:
    if not seeds:
        return "no_strong_seed"
    if not seed_hits:
        return "seed_without_strong_edge"
    if edges:
        return "strong_edges_only_seen_items"
    return "seed_without_strong_edge"


def _insufficiency_reasons(reason_counts: Counter[str]) -> list[str]:
    reasons = []
    if reason_counts.get("no_strong_seed", 0):
        reasons.append("insufficient seed: target user has no recent_strong_positive_item_sequence seed item")
    if reason_counts.get("seed_without_strong_edge", 0):
        reasons.append("insufficient strong edge: seed item did not appear in the train-only item-item strong edge graph")
    if reason_counts.get("strong_edges_only_seen_items", 0):
        reasons.append("insufficient new candidate: strong edges only pointed to already-seen items")
    return reasons or ["none"]


def _per_user_summary(candidate_count_by_user: dict[str, int], target_user_ids: list[str]) -> dict[str, Any]:
    counts = [candidate_count_by_user.get(user_id, 0) for user_id in target_user_ids]
    if not counts:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    return {"min": min(counts), "p50": int(median(counts)), "p90": _percentile(counts, 0.9), "max": max(counts)}


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return int(ordered[index])


def _strong_edge_quality(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"edge_count": 0, "min_score": 0.0, "p50_score": 0.0, "p90_score": 0.0, "max_score": 0.0}
    return {
        "edge_count": len(values),
        "min_score": min(values),
        "p50_score": float(median(values)),
        "p90_score": float(_percentile_float(values, 0.9)),
        "max_score": max(values),
    }


def _percentile_float(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _load_target_sequences(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = []
    for row in iter_jsonl(path):
        if row.get("user_id"):
            rows.append(row)
        if len(rows) >= limit:
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


def _resolve_train_sequences_path(clean_manifest_path: Path, clean_manifest: dict[str, Any]) -> Path:
    raw_path = clean_manifest.get("train_user_sequences_path") or clean_manifest_path.parent / "user_sequences.train.jsonl"
    path = Path(str(raw_path))
    path = path if path.is_absolute() else ROOT / path
    path = path.resolve()
    if path.name != "user_sequences.train.jsonl" or _has_forbidden_input_scope(path):
        raise ValueError(f"Only train user_sequences input is allowed: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _precheck_paths(clean_manifest_path: Path, output_dir: Path, min_free_bytes: int, overwrite: bool) -> None:
    if _has_forbidden_input_scope(clean_manifest_path):
        raise ValueError(f"Forbidden non-train/pool1000 path is not allowed: {clean_manifest_path}")
    lowered_output = str(output_dir).replace("\\", "/").lower()
    if "pool1000" in lowered_output or "clean_10000" in lowered_output:
        raise ValueError(f"Forbidden pool1000/clean_10000 output path is not allowed: {output_dir}")
    if not clean_manifest_path.is_file():
        raise FileNotFoundError(clean_manifest_path)
    if output_dir.exists() and not overwrite:
        raise FileExistsError(output_dir)
    if shutil.disk_usage(_existing_ancestor(output_dir)).free < min_free_bytes:
        raise RuntimeError("free disk bytes below --min-free-bytes")


def _validate_positive(**values: int) -> None:
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")


def _has_forbidden_input_scope(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if {"holdout", "valid", "test", "lopo", "clean_10000", "pool1000"} & parts:
        return True
    lowered_name = path.name.lower()
    return lowered_name in FORBIDDEN_INPUT_NAMES or "clean_10000" in lowered_name


def _config_int(config: dict[str, Any], name: str, default: int) -> int:
    value = config.get(name, default)
    if value is None:
        return default
    return int(value)


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if path.suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            rows = sum(1 for line in handle if line.strip())
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size, "row_count": rows}


def _existing_ancestor(path: Path) -> Path:
    current = path.resolve()
    while not current.exists():
        if current.parent == current:
            raise FileNotFoundError(path)
        current = current.parent
    return current


def _governance_fields() -> dict[str, bool]:
    return {
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _enforce_project_venv() -> None:
    executable = Path(sys.executable).resolve()
    expected = (ROOT / ".venv").resolve()
    try:
        executable.relative_to(expected)
    except ValueError as exc:
        raise RuntimeError(f"Project .venv Python is required, got {sys.executable}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pool500 itemcf_strong method source artifacts.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--target-user-limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-items-per-user", type=int, default=50)
    parser.add_argument("--max-item-user-freq", type=int, default=5000)
    parser.add_argument("--top-k-per-seed", type=int, default=100)
    parser.add_argument("--candidate-limit-per-user", type=int, default=500)
    parser.add_argument("--min-free-bytes", type=int, default=10 * 1024**3)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_itemcf_strong_method_source(
        clean_manifest_path=Path(args.clean_manifest),
        output_root=Path(args.output_root),
        run_id=args.run_id,
        target_user_limit=args.target_user_limit,
        batch_size=args.batch_size,
        max_items_per_user=args.max_items_per_user,
        max_item_user_freq=args.max_item_user_freq,
        top_k_per_seed=args.top_k_per_seed,
        candidate_limit_per_user=args.candidate_limit_per_user,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "source_index_manifest": manifest["outputs"]["source_index_manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
