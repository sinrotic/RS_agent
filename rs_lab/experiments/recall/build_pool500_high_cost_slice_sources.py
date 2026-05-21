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

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.common.runtime import enforce_project_venv
from rs_lab.experiments.recall.build_full_train_usercf_sidecar import build_full_train_usercf_sidecar
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _existing_ancestor

SCHEMA_VERSION = "pool500_high_cost_slice_sources_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_TWO_TOWER_SOURCE_MANIFEST = ROOT / "outputs" / "recall" / "pool500_full_sources" / "two_tower" / "source_index_manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall"
FORBIDDEN_PATH_PARTS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "clean_10000",
    "holdout",
    "valid",
    "test",
    "lopo",
    "pool1000",
)
FORBIDDEN_INPUT_NAMES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build train-only target500 high-cost source slice artifacts for pool500 direct recall.")
    parser.add_argument("--clean-manifest", default=str(DEFAULT_CLEAN_MANIFEST))
    parser.add_argument("--two-tower-source-manifest", default=str(DEFAULT_TWO_TOWER_SOURCE_MANIFEST))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--target-user-limit", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--two-tower-per-user", type=int, default=150)
    parser.add_argument("--usercf-per-user", type=int, default=150)
    parser.add_argument("--itemcf-per-seed", type=int, default=100)
    parser.add_argument("--max-items-per-user", type=int, default=50)
    parser.add_argument("--max-item-user-freq", type=int, default=5000)
    parser.add_argument("--shard-count", type=int, default=16)
    parser.add_argument("--min-free-bytes", type=int, default=10 * 1024**3)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def build_pool500_high_cost_slice_sources(
    *,
    clean_manifest: Path = DEFAULT_CLEAN_MANIFEST,
    two_tower_source_manifest: Path = DEFAULT_TWO_TOWER_SOURCE_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    target_user_limit: int = 500,
    batch_size: int = 50,
    two_tower_per_user: int = 150,
    usercf_per_user: int = 150,
    itemcf_per_seed: int = 100,
    max_items_per_user: int = 50,
    max_item_user_freq: int = 5000,
    shard_count: int = 16,
    min_free_bytes: int = 10 * 1024**3,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    _validate_caps(target_user_limit, batch_size, two_tower_per_user, usercf_per_user, itemcf_per_seed, max_items_per_user, max_item_user_freq, shard_count, min_free_bytes)
    clean_manifest = clean_manifest.resolve()
    two_tower_source_manifest = two_tower_source_manifest.resolve()
    output_root = output_root.resolve()
    _precheck_paths(clean_manifest, two_tower_source_manifest, output_root, min_free_bytes)

    clean_payload = read_json(clean_manifest)
    train_sequences_path = _resolve_train_sequence_path(clean_manifest, clean_payload)
    target_sequences = _load_target_sequences(train_sequences_path, target_user_limit)
    target_user_ids = [str(row["user_id"]) for row in target_sequences]
    clean_signature = _file_signature(clean_manifest)
    train_signature = _file_signature(train_sequences_path)

    two_tower_manifest_path = output_root / "pool500_full_sources" / "two_tower_target500_slice_expanded" / "source_index_manifest.json"
    usercf_output_dir = output_root / "pool500_sidecar_fix" / "usercf_recall_target500_slice_expanded"
    itemcf_weak_output_dir = output_root / "pool500_sidecar_fix" / "itemcf_weak_target500_slice_expanded"
    itemcf_strong_output_dir = output_root / "pool500_sidecar_fix" / "itemcf_strong_target500_slice_expanded"
    target_user_manifest_path = output_root / "pool500_sidecar_fix" / "target500_train_only_user_manifest_for_high_cost_slice.json"
    for path in (two_tower_manifest_path.parent, usercf_output_dir, itemcf_weak_output_dir, itemcf_strong_output_dir):
        if path.exists() and overwrite:
            shutil.rmtree(path)
    for path in (two_tower_manifest_path.parent, itemcf_weak_output_dir, itemcf_strong_output_dir):
        path.mkdir(parents=True, exist_ok=False)
    target_user_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    target_user_manifest = _write_target_user_manifest(
        target_user_manifest_path,
        target_user_ids,
        clean_manifest,
        train_sequences_path,
        clean_signature,
        train_signature,
    )

    two_tower_manifest = _build_two_tower_slice(
        source_manifest_path=two_tower_source_manifest,
        output_dir=two_tower_manifest_path.parent,
        target_sequences=target_sequences,
        target_user_ids=target_user_ids,
        clean_manifest=clean_manifest,
        train_sequences_path=train_sequences_path,
        clean_signature=clean_signature,
        train_signature=train_signature,
        batch_size=batch_size,
        per_user=two_tower_per_user,
        shard_count=shard_count,
    )
    usercf_manifest = build_full_train_usercf_sidecar(
        clean_manifest=clean_manifest,
        output_dir=usercf_output_dir,
        eligible_user_quality_manifest=target_user_manifest_path,
        include_medium_behavior=False,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        similar_users_top_k=100,
        candidate_top_k_per_user=usercf_per_user,
        shard_count=shard_count,
        target_user_limit=target_user_limit,
        target_batch_size=batch_size,
        min_free_bytes=min_free_bytes,
        min_free_memory_bytes=0,
        max_rss_mb=4096,
        resume=False,
        overwrite=False,
        enforce_venv=enforce_venv,
    )
    _add_generation_overrides(usercf_output_dir / "source_index_manifest.json", {"usercf_per_user": usercf_per_user})
    itemcf_weak_manifest = _build_itemcf_slice(
        clean_manifest=clean_manifest,
        train_sequences_path=train_sequences_path,
        output_dir=itemcf_weak_output_dir,
        source="itemcf_weak",
        sequence_key="recent_positive_item_sequence",
        target_sequences=target_sequences,
        target_user_ids=target_user_ids,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        top_k_per_seed=itemcf_per_seed,
        batch_size=batch_size,
        clean_signature=clean_signature,
        train_signature=train_signature,
    )
    itemcf_strong_manifest = _build_itemcf_slice(
        clean_manifest=clean_manifest,
        train_sequences_path=train_sequences_path,
        output_dir=itemcf_strong_output_dir,
        source="itemcf_strong",
        sequence_key="recent_strong_positive_item_sequence",
        target_sequences=target_sequences,
        target_user_ids=target_user_ids,
        max_items_per_user=max_items_per_user,
        max_item_user_freq=max_item_user_freq,
        top_k_per_seed=itemcf_per_seed,
        batch_size=batch_size,
        clean_signature=clean_signature,
        train_signature=train_signature,
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": _now(),
        "runtime_seconds": round(perf_counter() - started, 6),
        "target_user_count": len(target_user_ids),
        "target_user_limit": target_user_limit,
        "batch_size": batch_size,
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "final_pool500_ready_claimed": False,
        "target_user_manifest": target_user_manifest,
        "source_manifests": {
            "two_tower": two_tower_manifest["outputs"]["source_index_manifest"],
            "usercf_recall": str(usercf_output_dir / "source_index_manifest.json"),
            "itemcf_weak": itemcf_weak_manifest["outputs"]["source_index_manifest"],
            "itemcf_strong": itemcf_strong_manifest["outputs"]["source_index_manifest"],
        },
        "source_summary": {
            "two_tower": _summary(two_tower_manifest),
            "usercf_recall": _summary(usercf_manifest),
            "itemcf_weak": _summary(itemcf_weak_manifest),
            "itemcf_strong": _summary(itemcf_strong_manifest),
        },
    }
    write_json(output_root / "pool500_sidecar_fix" / "high_cost_target500_slice_expanded_manifest.json", manifest)
    return manifest


def _build_two_tower_slice(
    *,
    source_manifest_path: Path,
    output_dir: Path,
    target_sequences: list[dict[str, Any]],
    target_user_ids: list[str],
    clean_manifest: Path,
    train_sequences_path: Path,
    clean_signature: dict[str, Any],
    train_signature: dict[str, Any],
    batch_size: int,
    per_user: int,
    shard_count: int,
) -> dict[str, Any]:
    started = perf_counter()
    source_manifest = read_json(source_manifest_path)
    checkpoint_dir = output_dir / "batch_checkpoints"
    checkpoint_dir.mkdir()
    batch_manifests = []
    for batch_index, start in enumerate(range(0, len(target_sequences), batch_size)):
        batch = target_sequences[start : start + batch_size]
        users_with_positive_seed = [
            str(sequence["user_id"])
            for sequence in batch
            if sequence.get("user_id") and _recent_unique_items(sequence.get("recent_positive_item_sequence", []), 20)
        ]
        batch_manifest = {
            "schema_version": f"{SCHEMA_VERSION}.two_tower_batch",
            "status": "PASS",
            "batch_index": batch_index,
            "batch_size": len(batch),
            "target_user_ids": [str(row["user_id"]) for row in batch],
            "query_user_count": len(users_with_positive_seed),
            "candidate_generation_deferred_to_direct_recall": True,
        }
        write_json(checkpoint_dir / f"two_tower_batch_{batch_index:05d}.json", batch_manifest)
        batch_manifests.append(batch_manifest)
    query_user_count = sum(int(batch["query_user_count"]) for batch in batch_manifests)
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": "two_tower",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "batch_size": batch_size,
        "per_user": per_user,
        "target_user_count": len(target_user_ids),
        "query_user_count": query_user_count,
        "candidate_user_count": 0,
        "candidate_total_count": 0,
        "candidate_generation_deferred_to_direct_recall": True,
        "item_embedding_row_count": source_manifest.get("item_embedding_row_count"),
        "user_embedding_row_count": source_manifest.get("user_embedding_row_count"),
        "recall_index_row_count": source_manifest.get("recall_index_row_count"),
        "batches": batch_manifests,
    }
    no_holdout_audit = _no_holdout_audit("two_tower", clean_manifest, train_sequences_path)
    manifest = {
        **source_manifest,
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": "two_tower",
        "canonical_source": "two_tower",
        "source_name": "two_tower_youtube_dnn",
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "source_status": "MAIN_ROUTE_GENERATION_ONLY",
        "readiness_status": "MAIN_ROUTE_ARTIFACT_ONLY",
        "target_user_count": len(target_user_ids),
        "query_user_count": query_user_count,
        "candidate_user_count": 0,
        "candidate_total_count": 0,
        "row_count": 0,
        "candidate_generation_deferred_to_direct_recall": True,
        "batch_checkpoint_dir": str(checkpoint_dir),
        "clean_manifest_sha256": clean_signature["sha256"],
        "train_sequence_sha256": train_signature["sha256"],
        "generation_config_overrides": {"two_tower_per_user": per_user, "two_tower_seed_window": 20, "two_tower_query_batch_size": min(batch_size, 10)},
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "outputs": {
            "batch_checkpoints": str(checkpoint_dir),
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
        },
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", no_holdout_audit)
    write_json(output_dir / "source_index_manifest.json", manifest)
    return manifest


def _build_itemcf_slice(
    *,
    clean_manifest: Path,
    train_sequences_path: Path,
    output_dir: Path,
    source: str,
    sequence_key: str,
    target_sequences: list[dict[str, Any]],
    target_user_ids: list[str],
    max_items_per_user: int,
    max_item_user_freq: int,
    top_k_per_seed: int,
    batch_size: int,
    clean_signature: dict[str, Any],
    train_signature: dict[str, Any],
) -> dict[str, Any]:
    started = perf_counter()
    target_seed_items: set[str] = set()
    users_with_source_items = 0
    for sequence in target_sequences:
        items = _recent_unique_items(sequence.get(sequence_key, []), max_items_per_user)
        if items:
            users_with_source_items += 1
            target_seed_items.update(items)
    item_user_count: Counter[str] = Counter()
    contributing_sequences: list[list[str]] = []
    users_scanned = 0
    for row in iter_jsonl(train_sequences_path):
        users_scanned += 1
        items = _recent_unique_items(row.get(sequence_key, []), max_items_per_user)
        if not items or not (set(items) & target_seed_items):
            continue
        unique_items = sorted(set(items))
        contributing_sequences.append(unique_items)
        item_user_count.update(unique_items)
    hot_items = {item for item, count in item_user_count.items() if count > max_item_user_freq}
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
        if item_a in hot_items or item_b in hot_items:
            continue
        denom = (item_user_count[item_a] * item_user_count[item_b]) ** 0.5
        score = round(cooc_cnt / denom, 6) if denom else 0.0
        for src_item, dst_item in ((item_a, item_b), (item_b, item_a)):
            if src_item not in target_seed_items:
                continue
            outgoing[src_item].append({
                "src_item": src_item,
                "dst_item": dst_item,
                "score": score,
                "source": source,
                "label_variant": sequence_key,
                "cooc_cnt": cooc_cnt,
                "src_user_cnt": item_user_count[src_item],
                "dst_user_cnt": item_user_count[dst_item],
            })
    checkpoint_dir = output_dir / "batch_checkpoints"
    checkpoint_dir.mkdir()
    edges_path = output_dir / f"{source}_edges.jsonl"
    rows_written = 0
    with edges_path.open("w", encoding="utf-8") as handle:
        for batch_index, seed_batch in enumerate(_chunks(sorted(outgoing), batch_size)):
            for src_item in seed_batch:
                rows = sorted(outgoing[src_item], key=lambda row: (-row["score"], -row["cooc_cnt"], row["dst_item"]))[:top_k_per_seed]
                for rank, row in enumerate(rows, start=1):
                    handle.write(json.dumps({**row, "rank": rank}, ensure_ascii=False) + "\n")
                    rows_written += 1
            write_json(output_dir / "batch_checkpoints" / f"{source}_seed_batch_{batch_index:05d}.json", {"status": "PASS", "source": source, "batch_index": batch_index, "seed_count": len(seed_batch)})
    edge_signature = _file_signature(edges_path)
    source_index_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": source,
        "label_variant": sequence_key,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "source_status": "DIAGNOSTIC_ONLY",
        "diagnostic_only": True,
        "source_clean_manifest": str(clean_manifest),
        "train_user_sequences_path": str(train_sequences_path),
        "edges_path": str(edges_path),
        "clean_manifest_sha256": clean_signature["sha256"],
        "train_sequence_sha256": train_signature["sha256"],
        "target_user_count": len(target_user_ids),
        "candidate_user_count": users_with_source_items,
        "candidate_total_count": rows_written,
        "users_with_source_items": users_with_source_items,
        "target_seed_count": len(target_seed_items),
        "rows_written": rows_written,
        "edge_count": rows_written,
        "row_count": rows_written,
        "edge_signature": edge_signature,
        "generation_config_overrides": {
            f"{source}_per_seed": top_k_per_seed,
            "itemcf_recent_positive_window" if source == "itemcf_weak" else "itemcf_recent_strong_window": max_items_per_user,
        },
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "outputs": {
            "edges_path": str(edges_path),
            "source_index_manifest": str(output_dir / "source_index_manifest.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "no_holdout_audit": str(output_dir / "no_holdout_audit.json"),
            "per_source_candidate_manifest": str(output_dir / "per_source_candidate_manifest.json"),
        },
        "runtime_seconds": round(perf_counter() - started, 6),
    }
    resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.resource_audit",
        "status": "PASS",
        "source": source,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "batch_size": batch_size,
        "top_k_per_seed": top_k_per_seed,
        "target_user_count": len(target_user_ids),
        "users_scanned": users_scanned,
        "users_used": users_used,
        "users_with_source_items": users_with_source_items,
        "target_seed_count": len(target_seed_items),
        "unique_pair_count": len(pair_count),
        "rows_written": rows_written,
        "hot_item_count": len(hot_items),
    }
    per_source_candidate_manifest = {
        "schema_version": f"{SCHEMA_VERSION}.per_source_candidate_manifest",
        "status": "PASS",
        "source": source,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "diagnostic_only": True,
        "candidate_path": str(edges_path),
        "candidate_signature": edge_signature,
        "target_user_count": len(target_user_ids),
        "candidate_user_count": users_with_source_items,
        "candidate_total_count": rows_written,
        "rows_written": rows_written,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
    }
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "no_holdout_audit.json", _no_holdout_audit(source, clean_manifest, train_sequences_path))
    write_json(output_dir / "per_source_candidate_manifest.json", per_source_candidate_manifest)
    write_json(output_dir / "source_index_manifest.json", source_index_manifest)
    return source_index_manifest


def _validate_caps(*values: int) -> None:
    for value in values:
        if value <= 0:
            raise ValueError("all numeric caps must be positive")


def _precheck_paths(clean_manifest: Path, two_tower_source_manifest: Path, output_root: Path, min_free_bytes: int) -> None:
    for path in (clean_manifest, two_tower_source_manifest, output_root):
        lowered = str(path).replace("\\", "/").lower()
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden non-train/pool1000 path is not allowed: {path}")
    if not clean_manifest.is_file():
        raise FileNotFoundError(clean_manifest)
    if not two_tower_source_manifest.is_file():
        raise FileNotFoundError(two_tower_source_manifest)
    if shutil.disk_usage(_existing_ancestor(output_root)).free < min_free_bytes:
        raise RuntimeError("free disk bytes below --min-free-bytes")


def _resolve_train_sequence_path(clean_manifest: Path, manifest_payload: dict[str, Any]) -> Path:
    path = Path(str(manifest_payload.get("train_user_sequences_path") or clean_manifest.parent / "user_sequences.train.jsonl"))
    path = path if path.is_absolute() else ROOT / path
    lowered = str(path).replace("\\", "/").lower()
    if path.name != "user_sequences.train.jsonl" or any(name in lowered for name in FORBIDDEN_INPUT_NAMES) or any(part in lowered for part in FORBIDDEN_PATH_PARTS):
        raise ValueError(f"Only full clean train user sequences are allowed: {path}")
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


def _write_target_user_manifest(
    path: Path,
    target_user_ids: list[str],
    clean_manifest: Path,
    train_sequences_path: Path,
    clean_signature: dict[str, Any],
    train_signature: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "schema_version": f"{SCHEMA_VERSION}.target_user_manifest",
        "status": "PASS",
        "scope": "target500_train_only_high_cost_slice_users",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "clean_manifest_path": str(clean_manifest),
        "train_user_sequences_path": str(train_sequences_path),
        "clean_manifest_sha256": clean_signature["sha256"],
        "train_sequence_sha256": train_signature["sha256"],
        "target_user_count": len(target_user_ids),
        "target_user_ids": target_user_ids,
        "profiles": [
            {
                "user_id": user_id,
                "quality_bucket": "target500_high_cost_slice",
                "eligible_for_usercf_slice": True,
                "eligible_for_usercf": False,
            }
            for user_id in target_user_ids
        ],
        "forbidden_inputs": [str(train_sequences_path.parent / name) for name in FORBIDDEN_INPUT_NAMES],
    }
    write_json(path, payload)
    return {"path": str(path), "target_user_count": len(target_user_ids), "sha256": _file_signature(path)["sha256"]}


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


def _append_candidate_shards(shard_paths: list[Path], rows_by_user: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    stats = [{"shard_id": index, "path": str(path), "row_count": 0, "candidate_count": 0} for index, path in enumerate(shard_paths)]
    handles = [path.open("a", encoding="utf-8") for path in shard_paths]
    try:
        for user_id in sorted(rows_by_user):
            shard_id = int(hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:16], 16) % len(shard_paths)
            handles[shard_id].write(json.dumps({"user_id": user_id, "candidates": rows_by_user[user_id]}, ensure_ascii=False) + "\n")
            stats[shard_id]["row_count"] += 1
            stats[shard_id]["candidate_count"] += len(rows_by_user[user_id])
    finally:
        for handle in handles:
            handle.close()
    return stats


def _scan_candidate_shards(shard_paths: list[Path]) -> list[dict[str, Any]]:
    stats = []
    for index, path in enumerate(shard_paths):
        row_count = 0
        candidate_count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            row_count += 1
            candidate_count += len(row.get("candidates") or [])
        stats.append({"shard_id": index, "path": str(path), "row_count": row_count, "candidate_count": candidate_count})
    return stats


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


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


def _no_holdout_audit(source: str, clean_manifest: Path, train_sequences_path: Path) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.no_holdout_audit",
        "status": "PASS",
        "source": source,
        "index_scope": "FULL_DERIVED_INDEX",
        "train_only": True,
        "read_files": [str(clean_manifest), str(train_sequences_path)],
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


def _add_generation_overrides(manifest_path: Path, overrides: dict[str, int]) -> None:
    payload = read_json(manifest_path)
    payload["generation_config_overrides"] = overrides
    payload["promotion_allowed"] = False
    payload["final_pool500_ready_claimed"] = False
    write_json(manifest_path, payload)


def _summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": manifest.get("source"),
        "target_user_count": manifest.get("target_user_count"),
        "candidate_user_count": manifest.get("candidate_user_count"),
        "candidate_total_count": manifest.get("candidate_total_count"),
        "row_count": manifest.get("row_count") or manifest.get("rows_written") or manifest.get("edge_count"),
    }


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()
    manifest = build_pool500_high_cost_slice_sources(
        clean_manifest=Path(args.clean_manifest),
        two_tower_source_manifest=Path(args.two_tower_source_manifest),
        output_root=Path(args.output_root),
        target_user_limit=args.target_user_limit,
        batch_size=args.batch_size,
        two_tower_per_user=args.two_tower_per_user,
        usercf_per_user=args.usercf_per_user,
        itemcf_per_seed=args.itemcf_per_seed,
        max_items_per_user=args.max_items_per_user,
        max_item_user_freq=args.max_item_user_freq,
        shard_count=args.shard_count,
        min_free_bytes=args.min_free_bytes,
        overwrite=args.overwrite,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "source_manifests": manifest["source_manifests"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
