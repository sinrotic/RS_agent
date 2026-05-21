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
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[6]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_core.recsys.candidate_merge import load_itemcf_by_source, unique_recent_items
from rs_core.recsys.types import RecallCandidate
from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS, method_output_dir
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _existing_ancestor

SCHEMA_VERSION = "pool500_itemcf_weak_method_source_v1"
SOURCE = "itemcf_weak"
SOURCE_STATUS = "DIAGNOSTIC_ONLY"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources"
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "clean_10000",
    "pool1000",
)
FORBIDDEN_PATH_TOKENS = {"holdout", "valid", "test", "lopo"}
FORBIDDEN_INPUT_NAMES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def build_itemcf_weak_method_source(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    target_user_limit: int = 500,
    batch_size: int = 50,
    max_items_per_user: int = 50,
    max_item_user_freq: int = 5000,
    top_k_per_seed: int = 100,
    per_user_candidate_limit: int = 500,
    min_free_bytes: int = 0,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    _validate_positive(
        target_user_limit=target_user_limit,
        batch_size=batch_size,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        top_k_per_seed=top_k_per_seed,
        per_user_candidate_limit=per_user_candidate_limit,
    )
    clean_manifest_path = clean_manifest_path.resolve()
    output_root = output_root.resolve()
    run_id = run_id or _default_run_id()
    output_dir = method_output_dir(output_root, SOURCE, run_id).resolve()
    _precheck_paths(clean_manifest_path, output_dir, min_free_bytes)
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    checkpoint_dir = output_dir / "batch_checkpoints"
    checkpoint_dir.mkdir()

    clean_manifest = read_json(clean_manifest_path)
    train_sequences_path = _resolve_train_sequence_path(clean_manifest_path, clean_manifest)
    clean_signature = _file_signature(clean_manifest_path)
    train_signature = _file_signature(train_sequences_path)
    target_sequences = _load_target_sequences(train_sequences_path, target_user_limit)
    target_user_ids = [str(row["user_id"]) for row in target_sequences]
    target_seed_items = _target_seed_items(target_sequences, max_items_per_user)

    edges_path = output_dir / f"{SOURCE}_edges.jsonl"
    sidecar_stats = _build_weak_edges(
        train_sequences_path=train_sequences_path,
        edges_path=edges_path,
        target_seed_items=target_seed_items,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        top_k_per_seed=top_k_per_seed,
        batch_size=batch_size,
        checkpoint_dir=checkpoint_dir,
    )
    itemcf = load_itemcf_by_source(edges_path, SOURCE)
    candidates_path = output_dir / "candidates.jsonl"
    candidate_stats = _write_candidates(
        target_sequences=target_sequences,
        itemcf=itemcf,
        candidates_path=candidates_path,
        max_items_per_user=max_items_per_user,
        per_seed=top_k_per_seed,
        per_user_candidate_limit=per_user_candidate_limit,
    )

    edge_signature = _file_signature(edges_path)
    candidate_signature = _file_signature(candidates_path)
    no_holdout_audit = _no_holdout_audit(clean_manifest_path, train_sequences_path)
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": True,
        "index_scope": "FULL_DERIVED_INDEX",
        "target_user_count": len(target_user_ids),
        "batch_size": batch_size,
        "checkpoint_enabled": True,
        "checkpoint_dir": str(checkpoint_dir),
        "max_items_per_user": max_items_per_user,
        "max_item_user_freq": max_item_user_freq,
        "top_k_per_seed": top_k_per_seed,
        "per_user_candidate_limit": per_user_candidate_limit,
        **sidecar_stats,
        "candidate_row_count": candidate_stats["candidate_row_count"],
        "user_coverage_count": candidate_stats["user_coverage_count"],
    }
    coverage_audit = _coverage_audit(candidate_stats, sidecar_stats, target_user_ids, edges_path, candidates_path)
    undercoverage_audit = _undercoverage_audit(candidate_stats, target_user_ids)
    method_dataset_manifest = _method_dataset_manifest(
        output_dir=output_dir,
        run_id=run_id,
        clean_manifest_path=clean_manifest_path,
        train_sequences_path=train_sequences_path,
        clean_signature=clean_signature,
        train_signature=train_signature,
        target_user_ids=target_user_ids,
        config={
            "target_user_limit": target_user_limit,
            "batch_size": batch_size,
            "max_items_per_user": max_items_per_user,
            "max_item_user_freq": max_item_user_freq,
            "top_k_per_seed": top_k_per_seed,
            "per_user_candidate_limit": per_user_candidate_limit,
        },
    )
    source_index_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.source_index_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "diagnostic_only": True,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "label_variant": "recent_positive_item_sequence",
        "run_id": run_id,
        "output_dir": str(output_dir),
        "source_clean_manifest": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "edges_path": str(edges_path),
        "candidates_path": str(candidates_path),
        "clean_manifest_sha256": clean_signature["sha256"],
        "train_sequence_sha256": train_signature["sha256"],
        "edge_signature": edge_signature,
        "candidate_signature": candidate_signature,
        "target_user_count": len(target_user_ids),
        "candidate_user_count": candidate_stats["user_coverage_count"],
        "candidate_total_count": candidate_stats["candidate_row_count"],
        "row_count": candidate_stats["candidate_row_count"],
        "edge_count": sidecar_stats["rows_written"],
        "seed_hit_count": candidate_stats["seed_hit_count"],
        "weak_edge_hit_count": candidate_stats["weak_edge_hit_count"],
        "total_seed_count": candidate_stats["total_seed_count"],
        "edge_coverage": candidate_stats["edge_coverage"],
        "candidate_count_stats": candidate_stats["candidate_count_stats"],
        "generation_config_overrides": {
            "itemcf_weak_per_seed": top_k_per_seed,
            "itemcf_recent_positive_window": max_items_per_user,
        },
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "outputs": {
            "method_dataset_manifest": str(output_dir / "method_dataset_manifest.json"),
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "edges_path": str(edges_path),
            "candidates": str(candidates_path),
            "coverage_audit": str(output_dir / "coverage_audit.json"),
            "undercoverage_audit": str(output_dir / "undercoverage_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
        },
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    method_dataset_manifest["source_index_manifest_sha256"] = canonical_manifest_sha256(source_index_manifest)

    write_json(output_dir / "method_dataset_manifest.json", method_dataset_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    write_json(output_dir / "coverage_audit.json", coverage_audit)
    write_json(output_dir / "undercoverage_audit.json", undercoverage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    return {
        **source_index_manifest,
        "required_outputs_present": {name: (output_dir / name).is_file() for name in REQUIRED_SOURCE_OUTPUTS},
        "coverage_audit": coverage_audit,
        "undercoverage_audit": undercoverage_audit,
    }


def _build_weak_edges(
    *,
    train_sequences_path: Path,
    edges_path: Path,
    target_seed_items: set[str],
    max_items_per_user: int,
    max_item_user_freq: int,
    top_k_per_seed: int,
    batch_size: int,
    checkpoint_dir: Path,
) -> dict[str, Any]:
    item_user_count: Counter[str] = Counter()
    contributing_sequences: list[list[str]] = []
    users_scanned = 0
    users_with_target_seed = 0
    for row in iter_jsonl(train_sequences_path):
        users_scanned += 1
        items = unique_recent_items(row.get("recent_positive_item_sequence", []), max_items_per_user)
        if not items or not (set(items) & target_seed_items):
            continue
        users_with_target_seed += 1
        unique_items = sorted(set(items))
        contributing_sequences.append(unique_items)
        item_user_count.update(unique_items)

    hot_items = {item for item, count in item_user_count.items() if count > max_item_user_freq}
    capped_item_user_count = Counter({item: count for item, count in item_user_count.items() if item not in hot_items})
    pair_count: Counter[tuple[str, str]] = Counter()
    users_used = 0
    for items in contributing_sequences:
        filtered = [item for item in items if item not in hot_items]
        if len(filtered) < 2:
            continue
        users_used += 1
        for item_a, item_b in combinations(filtered, 2):
            if item_a in target_seed_items or item_b in target_seed_items:
                pair_count[(item_a, item_b)] += 1

    outgoing: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for (item_a, item_b), cooc_cnt in pair_count.items():
        denom = (capped_item_user_count[item_a] * capped_item_user_count[item_b]) ** 0.5
        score = round(cooc_cnt / denom, 6) if denom else 0.0
        for src_item, dst_item in ((item_a, item_b), (item_b, item_a)):
            if src_item not in target_seed_items:
                continue
            outgoing[src_item].append({
                "src_item": src_item,
                "dst_item": dst_item,
                "score": score,
                "source": SOURCE,
                "label_variant": "recent_positive_item_sequence",
                "cooc_cnt": cooc_cnt,
                "src_user_cnt": capped_item_user_count[src_item],
                "dst_user_cnt": capped_item_user_count[dst_item],
            })

    rows_written = 0
    with edges_path.open("w", encoding="utf-8") as handle:
        for batch_index, seed_batch in enumerate(_chunks(sorted(outgoing), batch_size)):
            batch_rows = 0
            for src_item in seed_batch:
                rows = sorted(outgoing[src_item], key=lambda row: (-row["score"], -row["cooc_cnt"], row["dst_item"]))[:top_k_per_seed]
                for rank, row in enumerate(rows, start=1):
                    handle.write(json.dumps({**row, "rank": rank}, ensure_ascii=False) + "\n")
                    rows_written += 1
                    batch_rows += 1
            write_json(checkpoint_dir / f"{SOURCE}_seed_batch_{batch_index:05d}.json", {"status": "PASS", "source": SOURCE, "batch_index": batch_index, "seed_count": len(seed_batch), "row_count": batch_rows})

    return {
        "users_scanned": users_scanned,
        "users_with_target_seed": users_with_target_seed,
        "users_used": users_used,
        "target_seed_count": len(target_seed_items),
        "edge_seed_count": len(outgoing),
        "unique_pair_count": len(pair_count),
        "hot_item_count": len(hot_items),
        "rows_written": rows_written,
    }


def _write_candidates(
    *,
    target_sequences: list[dict[str, Any]],
    itemcf: dict[str, list[RecallCandidate]],
    candidates_path: Path,
    max_items_per_user: int,
    per_seed: int,
    per_user_candidate_limit: int,
) -> dict[str, Any]:
    candidate_counts: list[int] = []
    seed_hit_count = 0
    weak_edge_hit_count = 0
    total_seed_count = 0
    user_coverage_count = 0
    undercovered_users: list[dict[str, Any]] = []
    candidate_row_count = 0
    with candidates_path.open("w", encoding="utf-8") as handle:
        for sequence in target_sequences:
            user_id = str(sequence.get("user_id") or "")
            seen_items = {str(item) for item in sequence.get("recent_item_sequence", []) if item}
            seed_items = list(dict.fromkeys(reversed(unique_recent_items(sequence.get("recent_positive_item_sequence", []), max_items_per_user))))
            total_seed_count += len(seed_items)
            seed_hits = [seed for seed in seed_items if seed in itemcf]
            if seed_hits:
                seed_hit_count += 1
            by_item: dict[str, dict[str, Any]] = {}
            for seed_rank, seed in enumerate(seed_items):
                edges = itemcf.get(seed, [])[:per_seed]
                if edges:
                    weak_edge_hit_count += 1
                for edge_rank, candidate in enumerate(edges, start=1):
                    if candidate.item_id in seen_items or candidate.item_id == seed:
                        continue
                    score = float(candidate.score) * (0.85 ** seed_rank)
                    current = by_item.get(candidate.item_id)
                    if current is None or score > float(current["score"]):
                        by_item[candidate.item_id] = {
                            "user_id": user_id,
                            "item_id": candidate.item_id,
                            "source": SOURCE,
                            "canonical_source": SOURCE,
                            "sources": [SOURCE],
                            "score": round(score, 8),
                            "metadata": {
                                "seed_item": seed,
                                "seed_rank": seed_rank + 1,
                                "edge_rank": edge_rank,
                                "edge_score": float(candidate.score),
                            },
                        }
            rows = sorted(by_item.values(), key=lambda row: (-float(row["score"]), str(row["item_id"])))[:per_user_candidate_limit]
            for rank, row in enumerate(rows, start=1):
                handle.write(json.dumps({**row, "rank": rank}, ensure_ascii=False) + "\n")
            count = len(rows)
            candidate_counts.append(count)
            candidate_row_count += count
            if count:
                user_coverage_count += 1
            if count < per_user_candidate_limit:
                undercovered_users.append({
                    "user_id": user_id,
                    "candidate_count": count,
                    "seed_item_count": len(seed_items),
                    "seed_hit_count": len(seed_hits),
                    "reason": _undercoverage_reason(seed_items, seed_hits, count),
                })
    return {
        "candidate_row_count": candidate_row_count,
        "user_coverage_count": user_coverage_count,
        "seed_hit_count": seed_hit_count,
        "weak_edge_hit_count": weak_edge_hit_count,
        "total_seed_count": total_seed_count,
        "edge_coverage": weak_edge_hit_count / total_seed_count if total_seed_count else 0.0,
        "candidate_count_stats": _count_stats(candidate_counts),
        "users_with_500_candidates": sum(1 for count in candidate_counts if count >= per_user_candidate_limit),
        "undercovered_users": undercovered_users,
    }


def _undercoverage_reason(seed_items: list[str], seed_hits: list[str], candidate_count: int) -> str:
    if not seed_items:
        return "no_recent_positive_seed_items"
    if not seed_hits:
        return "seed_items_missing_from_weak_itemcf_edges"
    if candidate_count == 0:
        return "weak_edges_only_return_seen_or_self_items"
    return "weak_edge_fanout_below_500"


def _coverage_audit(candidate_stats: dict[str, Any], sidecar_stats: dict[str, Any], target_user_ids: list[str], edges_path: Path, candidates_path: Path) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": True,
        "target_user_count": len(target_user_ids),
        "candidate_row_count": candidate_stats["candidate_row_count"],
        "user_coverage_count": candidate_stats["user_coverage_count"],
        "seed_hit_count": candidate_stats["seed_hit_count"],
        "weak_edge_hit_count": candidate_stats["weak_edge_hit_count"],
        "total_seed_count": candidate_stats["total_seed_count"],
        "edge_coverage": candidate_stats["edge_coverage"],
        "candidate_count_stats": candidate_stats["candidate_count_stats"],
        "target_seed_count": sidecar_stats["target_seed_count"],
        "edge_seed_count": sidecar_stats["edge_seed_count"],
        "edge_count": sidecar_stats["rows_written"],
        "edges_path": str(edges_path),
        "candidates_path": str(candidates_path),
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def _undercoverage_audit(candidate_stats: dict[str, Any], target_user_ids: list[str]) -> dict[str, Any]:
    reasons = Counter(row["reason"] for row in candidate_stats["undercovered_users"])
    return {
        "schema_version": f"{SCHEMA_VERSION}.undercoverage_audit",
        "status": "DIAGNOSTIC_ONLY",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": True,
        "target_user_count": len(target_user_ids),
        "undercovered_user_count": len(candidate_stats["undercovered_users"]),
        "users_with_500_candidates": candidate_stats["users_with_500_candidates"],
        "reason_counts": dict(sorted(reasons.items())),
        "sample_users": candidate_stats["undercovered_users"][:50],
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def _method_dataset_manifest(
    *,
    output_dir: Path,
    run_id: str,
    clean_manifest_path: Path,
    train_sequences_path: Path,
    clean_signature: dict[str, Any],
    train_signature: dict[str, Any],
    target_user_ids: list[str],
    config: dict[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.method_dataset_manifest",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "run_id": run_id,
        "output_dir": str(output_dir),
        "dataset_policy": "method_specific_seed_item_weak_edge_dataset",
        "train_only": True,
        "source_clean_manifest": str(clean_manifest_path),
        "train_user_sequences_path": str(train_sequences_path),
        "clean_manifest_sha256": clean_signature["sha256"],
        "train_sequence_sha256": train_signature["sha256"],
        "target_user_count": len(target_user_ids),
        "target_user_ids_sha256": hashlib.sha256("\n".join(target_user_ids).encode("utf-8")).hexdigest(),
        "config": config,
        "forbidden_inputs": [str(train_sequences_path.parent / name) for name in FORBIDDEN_INPUT_NAMES],
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def _no_holdout_audit(clean_manifest_path: Path, train_sequences_path: Path) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS",
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": SOURCE_STATUS,
        "train_only": True,
        "read_files": [str(clean_manifest_path), str(train_sequences_path)],
        "forbidden_inputs": [str(train_sequences_path.parent / name) for name in FORBIDDEN_INPUT_NAMES],
        "uses_holdout": False,
        "uses_valid": False,
        "uses_test": False,
        "uses_lopo": False,
        "uses_10k": False,
        "uses_pool1000": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }


def _resolve_train_sequence_path(clean_manifest_path: Path, manifest: dict[str, Any]) -> Path:
    raw_path = manifest.get("train_user_sequences_path") or clean_manifest_path.parent / "user_sequences.train.jsonl"
    path = Path(str(raw_path))
    path = path if path.is_absolute() else ROOT / path
    lowered = str(path).replace("\\", "/").lower()
    path_tokens = {part for part in Path(lowered).parts}
    if path.name != "user_sequences.train.jsonl" or any(part in lowered for part in FORBIDDEN_PATH_PARTS) or path_tokens & FORBIDDEN_PATH_TOKENS:
        raise ValueError(f"Only train user_sequences input is allowed: {path}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


def _load_target_sequences(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = []
    for row in iter_jsonl(path):
        if row.get("user_id"):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _target_seed_items(sequences: list[dict[str, Any]], max_items_per_user: int) -> set[str]:
    seeds: set[str] = set()
    for row in sequences:
        seeds.update(unique_recent_items(row.get("recent_positive_item_sequence", []), max_items_per_user))
    return seeds


def _precheck_paths(clean_manifest_path: Path, output_dir: Path, min_free_bytes: int) -> None:
    for path in (clean_manifest_path, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        path_tokens = {part for part in Path(lowered).parts}
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS) or path_tokens & FORBIDDEN_PATH_TOKENS:
            raise ValueError(f"Forbidden non-train/pool1000 path is not allowed: {path}")
    if not clean_manifest_path.is_file():
        raise FileNotFoundError(clean_manifest_path)
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below --min-free-bytes: {free_bytes} < {min_free_bytes}")


def _validate_positive(**values: int) -> None:
    for label, value in values.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")


def _count_stats(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "p50": _percentile(ordered, 0.5),
        "p90": _percentile(ordered, 0.9),
        "max": ordered[-1],
    }


def _percentile(values: list[int], q: float) -> float:
    if len(values) == 1:
        return float(values[0])
    pos = (len(values) - 1) * q
    lower = int(pos)
    upper = min(lower + 1, len(values) - 1)
    weight = pos - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 6)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                rows += 1
            digest.update(line)
    return {"path": str(path), "bytes": path.stat().st_size, "row_count": rows, "sha256": digest.hexdigest()}


def canonical_manifest_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pool500 itemcf_weak method source artifacts.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--target-user-limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-items-per-user", type=int, default=50)
    parser.add_argument("--max-item-user-freq", type=int, default=5000)
    parser.add_argument("--top-k-per-seed", type=int, default=100)
    parser.add_argument("--per-user-candidate-limit", type=int, default=500)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_itemcf_weak_method_source(
        clean_manifest_path=Path(args.clean_manifest),
        output_root=Path(args.output_root),
        run_id=args.run_id or None,
        target_user_limit=args.target_user_limit,
        batch_size=args.batch_size,
        max_items_per_user=args.max_items_per_user,
        max_item_user_freq=args.max_item_user_freq,
        top_k_per_seed=args.top_k_per_seed,
        per_user_candidate_limit=args.per_user_candidate_limit,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({
        "status": manifest["status"],
        "source": SOURCE,
        "output_dir": manifest["output_dir"],
        "source_index_manifest": manifest["outputs"]["source_index_manifest"],
        "candidate_row_count": manifest["candidate_total_count"],
        "user_coverage_count": manifest["candidate_user_count"],
        "candidate_count_stats": manifest["candidate_count_stats"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
