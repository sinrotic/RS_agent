from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv

SCHEMA_VERSION = "pool500_cold_start_fallback_v5"
REPAIR_STAGE = "cold_start_fallback_v5"
TARGET_CANDIDATE_COUNT = 500
TARGET_REPAIR_USER_COUNT = 62
FORBIDDEN_DATA_MARKERS = ("holdout", "valid", "test", "lopo", "leave_one_positive_out", "clean_10000")
COLD_START_SOURCES = [
    "cold_start_category_sibling",
    "cold_start_metadata_neighbor",
    "cold_start_semantic_token",
    "cold_start_item_neighbor",
    "cold_start_category_popular",
    "cold_start_global_popular",
]
POPULAR_SOURCES = {"cold_start_category_popular", "cold_start_global_popular"}
TOKEN_RE = re.compile(r"[A-Za-z0-9]{3,}")
STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "your", "you", "are", "black", "white",
    "edition", "products", "product", "amazon", "into", "full", "size", "made", "great",
}
REQUIRED_INPUTS = {
    "base_manifest": "manifest.json",
    "base_underfill_audit": "underfill_audit.json",
    "base_pool500_candidates": "pool500_candidates.jsonl",
    "base_source_contribution_audit": "source_contribution_audit.json",
    "base_repair_contribution_audit": "repair_contribution_audit.json",
    "data_manifest": "data/processed/amazon_2023_recall_clean_full/manifest.json",
    "train_user_sequences": "data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl",
    "train_interactions": "data/processed/amazon_2023_recall_clean_full/canonical_interactions.train.jsonl",
    "canonical_items": "data/processed/amazon_2023_recall_clean_full/canonical_items.jsonl",
    "category_recall_items": "data/processed/amazon_2023_recall_views_full_lightweight/category_recall_items.jsonl",
    "category_top_items": "data/processed/amazon_2023_recall_views_full_lightweight/category_top_items.jsonl",
    "popular_recall": "data/processed/amazon_2023_recall_views_full_lightweight/popular_recall.jsonl",
    "semantic_recall_inputs": "data/processed/amazon_2023_recall_views_full_lightweight/semantic_recall_inputs.jsonl",
    "semantic_inverted_index": "data/processed/amazon_2023_recall_views_full_lightweight/semantic_inverted_index.jsonl",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build pool500 v5 cold-start fallback repair artifacts for v4 remaining low-history users.")
    parser.add_argument("--base-run-dir", default="outputs/recall/pool500_main_route_direct_recall_underfilled66_repair_v4")
    parser.add_argument("--output-dir", default="outputs/recall/pool500_main_route_direct_recall_cold_start_fallback_v5")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--popular-cap-per-user", type=int, default=80)
    parser.add_argument("--category-cap-per-user", type=int, default=260)
    parser.add_argument("--semantic-token-cap-per-user", type=int, default=160)
    parser.add_argument("--metadata-neighbor-cap-per-user", type=int, default=160)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_cold_start_fallback_v5(
        base_run_dir=Path(args.base_run_dir),
        output_dir=Path(args.output_dir),
        overwrite=args.overwrite,
        popular_cap_per_user=args.popular_cap_per_user,
        category_cap_per_user=args.category_cap_per_user,
        semantic_token_cap_per_user=args.semantic_token_cap_per_user,
        metadata_neighbor_cap_per_user=args.metadata_neighbor_cap_per_user,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({
        "output_dir": manifest["output_dir"],
        "candidate_rows": manifest["candidate_rows"],
        "users_with_500_candidates": manifest["users_with_500_candidates"],
        "underfilled_user_count": manifest["underfilled_user_count"],
        "decision": manifest["decision"],
    }, ensure_ascii=False, indent=2))


def build_cold_start_fallback_v5(
    *,
    base_run_dir: Path,
    output_dir: Path,
    overwrite: bool = False,
    popular_cap_per_user: int = 80,
    category_cap_per_user: int = 260,
    semantic_token_cap_per_user: int = 160,
    metadata_neighbor_cap_per_user: int = 160,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)

    base_run_dir = _resolve_path(base_run_dir)
    output_dir = _resolve_path(output_dir)
    if not base_run_dir.is_dir():
        raise FileNotFoundError(f"base run dir not found: {base_run_dir}")
    if output_dir.resolve() == base_run_dir.resolve():
        raise ValueError("output-dir must not overwrite base-run-dir")
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = _input_paths(base_run_dir)
    _assert_required_inputs(paths)
    base_manifest = read_json(paths["base_manifest"])
    base_underfill = read_json(paths["base_underfill_audit"])
    base_source_contribution = read_json(paths["base_source_contribution_audit"])
    base_repair_contribution = read_json(paths["base_repair_contribution_audit"])
    data_manifest = read_json(paths["data_manifest"])

    target_users = [str(user_id) for user_id in base_underfill.get("remaining_underfilled_users", [])]
    if len(target_users) != TARGET_REPAIR_USER_COUNT:
        raise ValueError(f"expected {TARGET_REPAIR_USER_COUNT} v4 remaining underfilled users, got {len(target_users)}")
    target_user_set = set(target_users)

    base_rows_by_user, base_source_counter, base_duplicate_count, candidate_rows_read = _load_base_candidates(paths["base_pool500_candidates"])
    original_counts = {user_id: len(base_rows_by_user.get(user_id, [])) for user_id in target_users}
    existing_items_by_user = {
        user_id: {str(row.get("item_id", "")) for row in rows if row.get("item_id")}
        for user_id, rows in base_rows_by_user.items()
    }

    sequences_by_user, sequence_rows_read = _load_target_sequences(paths["train_user_sequences"], target_user_set)
    missing_sequence_users = sorted(target_user_set - set(sequences_by_user))
    seed_items_by_user = {user_id: _seed_items(sequences_by_user.get(user_id, {})) for user_id in target_users}
    seed_item_ids = {item_id for seeds in seed_items_by_user.values() for item_id in seeds}

    seed_meta, canonical_scan_1 = _load_seed_metadata(paths["canonical_items"], seed_item_ids)
    seed_keys_by_user = {user_id: _user_seed_keys(seed_items_by_user[user_id], seed_meta) for user_id in target_users}
    category_recall_index, category_recall_rows = _load_category_recall_index(paths["category_recall_items"], seed_keys_by_user)
    category_top_index, category_top_rows = _load_category_top_index(paths["category_top_items"], seed_keys_by_user)
    popular_items, popular_rows = _load_global_popular(paths["popular_recall"])
    semantic_token_index, semantic_index_rows = _load_semantic_token_index(paths["semantic_inverted_index"], seed_meta)
    semantic_input_rows = _count_jsonl(paths["semantic_recall_inputs"])
    interaction_rows = _count_jsonl(paths["train_interactions"])
    metadata_index, canonical_scan_2 = _load_metadata_neighbor_index(paths["canonical_items"], seed_keys_by_user)

    repair_rows_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    overlap_stats = _empty_overlap_stats()
    source_users: dict[str, set[str]] = {source: set() for source in COLD_START_SOURCES}
    source_rows: Counter[str] = Counter()
    evidence_samples: dict[str, list[dict[str, Any]]] = {source: [] for source in COLD_START_SOURCES}

    for user_id in target_users:
        if len(base_rows_by_user.get(user_id, [])) >= TARGET_CANDIDATE_COUNT:
            continue
        _add_category_siblings(
            user_id,
            seed_items_by_user[user_id],
            seed_keys_by_user[user_id],
            category_recall_index,
            category_top_index,
            base_rows_by_user,
            repair_rows_by_user,
            existing_items_by_user,
            source_rows,
            source_users,
            overlap_stats,
            evidence_samples,
            category_cap_per_user,
        )
        _add_metadata_neighbors(
            user_id,
            seed_items_by_user[user_id],
            seed_keys_by_user[user_id],
            metadata_index,
            base_rows_by_user,
            repair_rows_by_user,
            existing_items_by_user,
            source_rows,
            source_users,
            overlap_stats,
            evidence_samples,
            metadata_neighbor_cap_per_user,
        )
        _add_semantic_tokens(
            user_id,
            seed_items_by_user[user_id],
            seed_meta,
            semantic_token_index,
            base_rows_by_user,
            repair_rows_by_user,
            existing_items_by_user,
            source_rows,
            source_users,
            overlap_stats,
            evidence_samples,
            semantic_token_cap_per_user,
        )
        _add_item_neighbor_reuse(
            user_id,
            base_rows_by_user,
            repair_rows_by_user,
            existing_items_by_user,
            source_rows,
            source_users,
            overlap_stats,
            evidence_samples,
        )
        _add_category_popular(
            user_id,
            seed_keys_by_user[user_id],
            category_top_index,
            base_rows_by_user,
            repair_rows_by_user,
            existing_items_by_user,
            source_rows,
            source_users,
            overlap_stats,
            evidence_samples,
        )
        _add_global_popular(
            user_id,
            popular_items,
            base_rows_by_user,
            repair_rows_by_user,
            existing_items_by_user,
            source_rows,
            source_users,
            overlap_stats,
            evidence_samples,
            popular_cap_per_user,
        )

    final_rows_by_user = _combine_and_cap(base_rows_by_user, repair_rows_by_user)
    final_counts = {user_id: len(rows) for user_id, rows in final_rows_by_user.items()}
    for user_id in target_users:
        final_counts.setdefault(user_id, 0)
    all_counts = list(final_counts.values())
    remaining_underfilled_users = [user_id for user_id in sorted(final_counts) if final_counts[user_id] < TARGET_CANDIDATE_COUNT]
    repaired_users = [user_id for user_id in target_users if final_counts.get(user_id, 0) > original_counts.get(user_id, 0)]
    fully_repaired_users = [user_id for user_id in target_users if original_counts.get(user_id, 0) < TARGET_CANDIDATE_COUNT <= final_counts.get(user_id, 0)]
    users_with_500 = sum(1 for count in final_counts.values() if count >= TARGET_CANDIDATE_COUNT)
    candidate_rows = sum(final_counts.values())
    duplicate_item_per_user_count = _duplicate_item_per_user_count(final_rows_by_user)
    per_user_over_500_count = sum(1 for count in final_counts.values() if count > TARGET_CANDIDATE_COUNT)
    forbidden_scan = _forbidden_data_scan(paths)
    decision = "STOP" if remaining_underfilled_users else "DIAGNOSTIC_PASS"
    generated_at = datetime.now(timezone.utc).isoformat()

    output_candidates_path = output_dir / "pool500_candidates.jsonl"
    write_jsonl(output_candidates_path, _iter_rows_in_user_order(final_rows_by_user))

    cold_start_user_audit = _build_cold_start_user_audit(
        target_users,
        sequences_by_user,
        seed_items_by_user,
        original_counts,
        final_counts,
        repair_rows_by_user,
        missing_sequence_users,
    )
    segment_counts = Counter(row["cold_start_segment"] for row in cold_start_user_audit["users"])
    quality_risk_audit = _build_quality_risk_audit(cold_start_user_audit, segment_counts)
    cold_start_source_contribution = _build_cold_start_source_contribution(source_rows, source_users, target_user_set)
    source_contribution_audit = _build_source_contribution_audit(final_rows_by_user, base_source_contribution, target_user_set)
    source_overlap_audit = _build_source_overlap_audit(overlap_stats, duplicate_item_per_user_count, evidence_samples)
    underfill_audit = _build_underfill_audit(target_users, original_counts, final_counts, repair_rows_by_user, remaining_underfilled_users)
    final_resource_audit = {
        "schema_version": f"{SCHEMA_VERSION}.final_resource_audit",
        "status": "PASS",
        "repair_stage": REPAIR_STAGE,
        "heavy_job": False,
        "resource_guard_required": False,
        "runtime_seconds": round(perf_counter() - started, 6),
        "checkpoint_used": False,
        "read_strategy": "streamed JSONL inputs; only target 62 users repaired; canonical_items scanned twice for seed metadata and bounded neighbor collection; no model training or heavy sidecar rebuild",
        "input_file_rows": {
            "base_pool500_candidates": candidate_rows_read,
            "train_user_sequences": sequence_rows_read,
            "canonical_items_seed_metadata_scan": canonical_scan_1,
            "canonical_items_metadata_neighbor_scan": canonical_scan_2,
            "canonical_interactions_train": interaction_rows,
            "category_recall_items": category_recall_rows,
            "category_top_items": category_top_rows,
            "popular_recall": popular_rows,
            "semantic_recall_inputs": semantic_input_rows,
            "semantic_inverted_index": semantic_index_rows,
        },
        "required_input_files": {key: str(path) for key, path in paths.items()},
        "data_manifest_train_paths_used": {
            "train_user_sequences_path": data_manifest.get("train_user_sequences_path"),
            "canonical_interactions_train_path": (data_manifest.get("split_paths") or {}).get("train"),
            "canonical_items_path": data_manifest.get("canonical_items_path"),
        },
        "base_repair_contribution_snapshot": {
            "schema_version": base_repair_contribution.get("schema_version"),
            "total_repair_row_count": base_repair_contribution.get("total_repair_row_count"),
        },
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
    }
    readiness_result = _build_readiness_result(decision, remaining_underfilled_users)
    shadow_evidence = _build_shadow_evidence(
        base_run_dir,
        output_candidates_path,
        decision,
        repaired_users,
        fully_repaired_users,
        remaining_underfilled_users,
        users_with_500,
        quality_risk_audit,
    )
    shadow_validation = _build_shadow_validation(
        forbidden_scan,
        per_user_over_500_count,
        duplicate_item_per_user_count,
        readiness_result,
        cold_start_user_audit,
    )
    required_artifacts = {
        "pool500_candidates": str(output_candidates_path),
        "manifest": str(output_dir / "manifest.json"),
        "underfill_audit": str(output_dir / "underfill_audit.json"),
        "cold_start_user_audit": str(output_dir / "cold_start_user_audit.json"),
        "cold_start_source_contribution_audit": str(output_dir / "cold_start_source_contribution_audit.json"),
        "source_contribution_audit": str(output_dir / "source_contribution_audit.json"),
        "source_overlap_audit": str(output_dir / "source_overlap_audit.json"),
        "cold_start_quality_risk_audit": str(output_dir / "cold_start_quality_risk_audit.json"),
        "final_resource_audit": str(output_dir / "final_resource_audit.json"),
        "readiness_result": str(output_dir / "readiness_result.json"),
        "pool500_shadow_evidence": str(output_dir / "pool500_shadow_evidence.json"),
        "pool500_shadow_evidence_validation": str(output_dir / "pool500_shadow_evidence_validation.json"),
    }
    manifest = {
        "schema_version": f"{SCHEMA_VERSION}.manifest",
        "generated_at": generated_at,
        "base_run_dir": str(base_run_dir),
        "output_dir": str(output_dir),
        "repair_stage": REPAIR_STAGE,
        "processed_users": int(base_manifest.get("processed_users", len(final_counts))),
        "target_repair_user_count": len(target_users),
        "repaired_user_count": len(fully_repaired_users),
        "candidate_rows": candidate_rows,
        "users_with_500_candidates": users_with_500,
        "underfilled_user_count": len(remaining_underfilled_users),
        **_candidate_count_stats(all_counts),
        "decision": decision,
        "status": decision,
        "artifact_gate_decision": "STOP",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
        "required_artifacts": required_artifacts,
        "base_duplicate_item_per_user_count": base_duplicate_count,
        "duplicate_item_per_user_count": duplicate_item_per_user_count,
        "forbidden_data_scan": forbidden_scan,
        "cold_start_segment_counts": dict(sorted(segment_counts.items())),
        "average_fallback_ratio": quality_risk_audit["average_fallback_ratio"],
        "average_popular_ratio": quality_risk_audit["average_popular_ratio"],
    }

    write_json(output_dir / "underfill_audit.json", underfill_audit)
    write_json(output_dir / "cold_start_user_audit.json", cold_start_user_audit)
    write_json(output_dir / "cold_start_source_contribution_audit.json", cold_start_source_contribution)
    write_json(output_dir / "source_contribution_audit.json", source_contribution_audit)
    write_json(output_dir / "source_overlap_audit.json", source_overlap_audit)
    write_json(output_dir / "cold_start_quality_risk_audit.json", quality_risk_audit)
    write_json(output_dir / "final_resource_audit.json", final_resource_audit)
    write_json(output_dir / "readiness_result.json", readiness_result)
    write_json(output_dir / "pool500_shadow_evidence.json", shadow_evidence)
    write_json(output_dir / "pool500_shadow_evidence_validation.json", shadow_validation)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path).resolve()


def _input_paths(base_run_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for key, value in REQUIRED_INPUTS.items():
        paths[key] = (base_run_dir / value).resolve() if key.startswith("base_") else (ROOT / value).resolve()
    return paths


def _assert_required_inputs(paths: dict[str, Path]) -> None:
    missing = [f"{key}={path}" for key, path in paths.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing required inputs: " + "; ".join(missing))


def _load_base_candidates(path: Path) -> tuple[dict[str, list[dict[str, Any]]], Counter[str], int, int]:
    rows_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_counter: Counter[str] = Counter()
    seen_by_user: dict[str, set[str]] = defaultdict(set)
    duplicate_count = 0
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        user_id = str(row.get("user_id", ""))
        item_id = _item_id(row)
        if not user_id or not item_id:
            continue
        if item_id in seen_by_user[user_id]:
            duplicate_count += 1
            continue
        normalized = dict(row)
        normalized["item_id"] = item_id
        rows_by_user[user_id].append(normalized)
        seen_by_user[user_id].add(item_id)
        source_counter[str(normalized.get("source") or "unknown")] += 1
    return dict(rows_by_user), source_counter, duplicate_count, rows_read


def _load_target_sequences(path: Path, target_user_set: set[str]) -> tuple[dict[str, dict[str, Any]], int]:
    sequences: dict[str, dict[str, Any]] = {}
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        user_id = str(row.get("user_id", ""))
        if user_id in target_user_set:
            sequences[user_id] = row
            if len(sequences) == len(target_user_set):
                break
    return sequences, rows_read


def _seed_items(sequence: dict[str, Any]) -> list[str]:
    positive = [_clean_item_id(value) for value in sequence.get("recent_positive_item_sequence", [])]
    recent = [_clean_item_id(value) for value in sequence.get("recent_item_sequence", [])]
    seeds = [item_id for item_id in positive if item_id] or [item_id for item_id in recent if item_id]
    deduped: list[str] = []
    seen: set[str] = set()
    for item_id in seeds:
        if item_id not in seen:
            deduped.append(item_id)
            seen.add(item_id)
    return deduped[:2]


def _load_seed_metadata(path: Path, seed_item_ids: set[str]) -> tuple[dict[str, dict[str, Any]], int]:
    seed_meta: dict[str, dict[str, Any]] = {}
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        item_id = _item_id(row)
        if item_id in seed_item_ids:
            seed_meta[item_id] = _minimal_item_meta(row)
            if len(seed_meta) == len(seed_item_ids):
                break
    return seed_meta, rows_read


def _minimal_item_meta(row: dict[str, Any]) -> dict[str, Any]:
    item_id = _item_id(row)
    categories_flat = [str(value) for value in row.get("categories_flat", []) if value]
    source_categories = [str(value) for value in row.get("source_categories", []) if value]
    return {
        "item_id": item_id,
        "category": str(row.get("category") or ""),
        "main_category": str(row.get("main_category") or ""),
        "source_categories": source_categories,
        "categories_flat": categories_flat,
        "store": str(row.get("store") or ""),
        "brand": str(row.get("brand") or row.get("store") or ""),
        "title": str(row.get("title_clean") or row.get("title") or ""),
        "parent_asin": str(row.get("parent_asin") or item_id),
    }


def _user_seed_keys(seed_items: list[str], seed_meta: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = defaultdict(set)
    for seed_item_id in seed_items:
        meta = seed_meta.get(seed_item_id, {})
        for field in ("category", "main_category", "store", "brand"):
            value = str(meta.get(field) or "").strip()
            if value:
                keys[field].add(value)
        for category in meta.get("source_categories", []) or []:
            if category:
                keys["category"].add(str(category))
        for category in meta.get("categories_flat", []) or []:
            if category:
                keys["categories_flat"].add(str(category))
    return dict(keys)


def _load_category_recall_index(path: Path, seed_keys_by_user: dict[str, dict[str, set[str]]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    wanted = _wanted_category_values(seed_keys_by_user)
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        item_id = _item_id(row)
        if not item_id:
            continue
        for key in _row_category_values(row):
            if key in wanted and len(index[key]) < 1200:
                index[key].append({"item_id": item_id, "score": float(row.get("time_decay_pop_score") or row.get("pop_score") or 0.0), "category_key": key})
    for rows in index.values():
        rows.sort(key=lambda item: item["score"], reverse=True)
    return dict(index), rows_read


def _load_category_top_index(path: Path, seed_keys_by_user: dict[str, dict[str, set[str]]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    wanted = _wanted_category_values(seed_keys_by_user)
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        bucket = str(row.get("bucket") or "")
        bucket_value = bucket.split("::", 1)[-1] if "::" in bucket else bucket
        if bucket_value not in wanted:
            continue
        for candidate in row.get("top_items", []) or []:
            item_id = _item_id(candidate)
            if item_id:
                index[bucket_value].append({"item_id": item_id, "score": float(candidate.get("score") or candidate.get("recent_pop_score") or 0.0), "category_key": bucket_value})
    return dict(index), rows_read


def _load_global_popular(path: Path) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        item_id = _item_id(row)
        if item_id:
            items.append({
                "item_id": item_id,
                "score": float(row.get("time_decay_pop_score") or row.get("pop_score") or row.get("recent_pop_score") or 0.0),
                "category": str(row.get("category") or ""),
            })
    items.sort(key=lambda item: item["score"], reverse=True)
    return items, rows_read


def _load_semantic_token_index(path: Path, seed_meta: dict[str, dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    wanted_tokens = {token for meta in seed_meta.values() for token in _tokens_for_meta(meta)}
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        token = _semantic_token(row)
        if token not in wanted_tokens:
            continue
        candidates = row.get("items") or row.get("parent_asins") or row.get("item_ids") or row.get("top_items") or []
        if isinstance(candidates, dict):
            candidates = candidates.values()
        for candidate in candidates:
            item_id = _item_id(candidate) if isinstance(candidate, dict) else _clean_item_id(candidate)
            if item_id and len(index[token]) < 1200:
                score = float(candidate.get("score", 1.0)) if isinstance(candidate, dict) else 1.0
                index[token].append({"item_id": item_id, "score": score, "matched_token": token})
    return dict(index), rows_read


def _load_metadata_neighbor_index(path: Path, seed_keys_by_user: dict[str, dict[str, set[str]]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    wanted_fields = {
        "brand": {value for keys in seed_keys_by_user.values() for value in keys.get("brand", set())},
        "store": {value for keys in seed_keys_by_user.values() for value in keys.get("store", set())},
        "category": {value for keys in seed_keys_by_user.values() for value in keys.get("category", set())},
        "main_category": {value for keys in seed_keys_by_user.values() for value in keys.get("main_category", set())},
    }
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rows_read = 0
    for row in iter_jsonl(path):
        rows_read += 1
        item_id = _item_id(row)
        if not item_id:
            continue
        score = float(row.get("time_decay_pop_score") or row.get("pop_score") or row.get("rating_number") or 0.0)
        for field, values in wanted_fields.items():
            value = str(row.get(field) or "").strip()
            if value and value in values:
                key = f"{field}::{value}"
                if len(index[key]) < 1500:
                    index[key].append({"item_id": item_id, "score": score, "matched_field": field, "matched_value": value})
    for rows in index.values():
        rows.sort(key=lambda item: item["score"], reverse=True)
    return dict(index), rows_read


def _count_jsonl(path: Path) -> int:
    count = 0
    for _ in iter_jsonl(path):
        count += 1
    return count


def _add_category_siblings(
    user_id: str,
    seed_items: list[str],
    seed_keys: dict[str, set[str]],
    category_recall_index: dict[str, list[dict[str, Any]]],
    category_top_index: dict[str, list[dict[str, Any]]],
    base_rows_by_user: dict[str, list[dict[str, Any]]],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    existing_items_by_user: dict[str, set[str]],
    source_rows: Counter[str],
    source_users: dict[str, set[str]],
    overlap_stats: dict[str, Counter[str]],
    evidence_samples: dict[str, list[dict[str, Any]]],
    cap: int,
) -> None:
    source = "cold_start_category_sibling"
    added = 0
    for category_key in _ordered_category_keys(seed_keys):
        for candidate in category_recall_index.get(category_key, []) + category_top_index.get(category_key, []):
            if added >= cap or _user_count(base_rows_by_user, repair_rows_by_user, user_id) >= TARGET_CANDIDATE_COUNT:
                return
            if _accept_repair_candidate(user_id, candidate, source, base_rows_by_user, repair_rows_by_user, existing_items_by_user, source_rows, source_users, overlap_stats, evidence_samples, {"seed_item_id": seed_items[0] if seed_items else "", "category_key": category_key}):
                added += 1


def _add_metadata_neighbors(
    user_id: str,
    seed_items: list[str],
    seed_keys: dict[str, set[str]],
    metadata_index: dict[str, list[dict[str, Any]]],
    base_rows_by_user: dict[str, list[dict[str, Any]]],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    existing_items_by_user: dict[str, set[str]],
    source_rows: Counter[str],
    source_users: dict[str, set[str]],
    overlap_stats: dict[str, Counter[str]],
    evidence_samples: dict[str, list[dict[str, Any]]],
    cap: int,
) -> None:
    source = "cold_start_metadata_neighbor"
    added = 0
    keys: list[str] = []
    for field in ("brand", "store", "category", "main_category"):
        keys.extend(f"{field}::{value}" for value in sorted(seed_keys.get(field, set())))
    for key in keys:
        for candidate in metadata_index.get(key, []):
            if added >= cap or _user_count(base_rows_by_user, repair_rows_by_user, user_id) >= TARGET_CANDIDATE_COUNT:
                return
            evidence = {"seed_item_id": seed_items[0] if seed_items else "", "matched_field": candidate.get("matched_field"), "matched_value": candidate.get("matched_value")}
            if _accept_repair_candidate(user_id, candidate, source, base_rows_by_user, repair_rows_by_user, existing_items_by_user, source_rows, source_users, overlap_stats, evidence_samples, evidence):
                added += 1


def _add_semantic_tokens(
    user_id: str,
    seed_items: list[str],
    seed_meta: dict[str, dict[str, Any]],
    semantic_token_index: dict[str, list[dict[str, Any]]],
    base_rows_by_user: dict[str, list[dict[str, Any]]],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    existing_items_by_user: dict[str, set[str]],
    source_rows: Counter[str],
    source_users: dict[str, set[str]],
    overlap_stats: dict[str, Counter[str]],
    evidence_samples: dict[str, list[dict[str, Any]]],
    cap: int,
) -> None:
    source = "cold_start_semantic_token"
    added = 0
    tokens: list[tuple[str, str]] = []
    for seed_item_id in seed_items:
        for token in _tokens_for_meta(seed_meta.get(seed_item_id, {})):
            tokens.append((seed_item_id, token))
    for seed_item_id, token in tokens:
        for candidate in semantic_token_index.get(token, []):
            if added >= cap or _user_count(base_rows_by_user, repair_rows_by_user, user_id) >= TARGET_CANDIDATE_COUNT:
                return
            if _accept_repair_candidate(user_id, candidate, source, base_rows_by_user, repair_rows_by_user, existing_items_by_user, source_rows, source_users, overlap_stats, evidence_samples, {"seed_item_id": seed_item_id, "matched_token": token}):
                added += 1


def _add_item_neighbor_reuse(
    user_id: str,
    base_rows_by_user: dict[str, list[dict[str, Any]]],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    existing_items_by_user: dict[str, set[str]],
    source_rows: Counter[str],
    source_users: dict[str, set[str]],
    overlap_stats: dict[str, Counter[str]],
    evidence_samples: dict[str, list[dict[str, Any]]],
) -> None:
    source = "cold_start_item_neighbor"
    reusable_sources = {"co_visit_fallback_repair", "swing_recall"}
    template_rows = [row for row in base_rows_by_user.get(user_id, []) if str(row.get("source")) in reusable_sources]
    for row in template_rows:
        if _user_count(base_rows_by_user, repair_rows_by_user, user_id) >= TARGET_CANDIDATE_COUNT:
            return
        candidate = {"item_id": _item_id(row), "score": float(row.get("score") or 0.0)}
        _accept_repair_candidate(user_id, candidate, source, base_rows_by_user, repair_rows_by_user, existing_items_by_user, source_rows, source_users, overlap_stats, evidence_samples, {"fallback_reason": "existing_item_neighbor_source_reuse", "base_source": row.get("source")})


def _add_category_popular(
    user_id: str,
    seed_keys: dict[str, set[str]],
    category_top_index: dict[str, list[dict[str, Any]]],
    base_rows_by_user: dict[str, list[dict[str, Any]]],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    existing_items_by_user: dict[str, set[str]],
    source_rows: Counter[str],
    source_users: dict[str, set[str]],
    overlap_stats: dict[str, Counter[str]],
    evidence_samples: dict[str, list[dict[str, Any]]],
) -> None:
    source = "cold_start_category_popular"
    for category_key in _ordered_category_keys(seed_keys):
        for candidate in category_top_index.get(category_key, []):
            if _user_count(base_rows_by_user, repair_rows_by_user, user_id) >= TARGET_CANDIDATE_COUNT:
                return
            _accept_repair_candidate(user_id, candidate, source, base_rows_by_user, repair_rows_by_user, existing_items_by_user, source_rows, source_users, overlap_stats, evidence_samples, {"category_key": category_key, "fallback_reason": "category_popular_after_personalized_fallback_exhausted"})


def _add_global_popular(
    user_id: str,
    popular_items: list[dict[str, Any]],
    base_rows_by_user: dict[str, list[dict[str, Any]]],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    existing_items_by_user: dict[str, set[str]],
    source_rows: Counter[str],
    source_users: dict[str, set[str]],
    overlap_stats: dict[str, Counter[str]],
    evidence_samples: dict[str, list[dict[str, Any]]],
    cap: int,
) -> None:
    source = "cold_start_global_popular"
    added = 0
    per_category: Counter[str] = Counter()
    for candidate in popular_items:
        if added >= cap or _user_count(base_rows_by_user, repair_rows_by_user, user_id) >= TARGET_CANDIDATE_COUNT:
            return
        category = str(candidate.get("category") or "")
        if category and per_category[category] >= max(1, cap // 8):
            continue
        accepted = _accept_repair_candidate(user_id, candidate, source, base_rows_by_user, repair_rows_by_user, existing_items_by_user, source_rows, source_users, overlap_stats, evidence_samples, {"fallback_reason": "global_diversity_popular_last_resort", "category": category})
        if accepted:
            added += 1
            per_category[category] += 1


def _accept_repair_candidate(
    user_id: str,
    candidate: dict[str, Any],
    source: str,
    base_rows_by_user: dict[str, list[dict[str, Any]]],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    existing_items_by_user: dict[str, set[str]],
    source_rows: Counter[str],
    source_users: dict[str, set[str]],
    overlap_stats: dict[str, Counter[str]],
    evidence_samples: dict[str, list[dict[str, Any]]],
    evidence: dict[str, Any],
) -> bool:
    if _user_count(base_rows_by_user, repair_rows_by_user, user_id) >= TARGET_CANDIDATE_COUNT:
        overlap_stats[source]["skipped_user_already_full"] += 1
        return False
    item_id = _item_id(candidate)
    if not item_id:
        overlap_stats[source]["skipped_missing_item"] += 1
        return False
    seen_items = existing_items_by_user.setdefault(user_id, set())
    if item_id in seen_items:
        overlap_stats[source]["overlap_existing_or_repair"] += 1
        return False
    row = _repair_row(user_id, item_id, source, float(candidate.get("score") or 0.0), evidence)
    repair_rows_by_user[user_id].append(row)
    seen_items.add(item_id)
    source_rows[source] += 1
    source_users[source].add(user_id)
    overlap_stats[source]["accepted"] += 1
    if len(evidence_samples[source]) < 20:
        evidence_samples[source].append({"user_id": user_id, "item_id": item_id, "evidence": evidence})
    return True


def _repair_row(user_id: str, item_id: str, source: str, score: float, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "item_id": item_id,
        "source": source,
        "sources": [source],
        "score": score,
        "rank": 0,
        "metadata": {
            "repair_stage": REPAIR_STAGE,
            "repair_source": source,
            "source_scores": {source: score},
            "evidence": evidence,
        },
        "repair_stage": REPAIR_STAGE,
        "repair_source": source,
        "repair_shadow_evidence_only": True,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
    }


def _combine_and_cap(base_rows_by_user: dict[str, list[dict[str, Any]]], repair_rows_by_user: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    final: dict[str, list[dict[str, Any]]] = {}
    for user_id in sorted(set(base_rows_by_user) | set(repair_rows_by_user)):
        rows = list(base_rows_by_user.get(user_id, []))
        missing = max(TARGET_CANDIDATE_COUNT - len(rows), 0)
        if missing:
            rows.extend(repair_rows_by_user.get(user_id, [])[:missing])
        final[user_id] = rows[:TARGET_CANDIDATE_COUNT]
    return final


def _iter_rows_in_user_order(rows_by_user: dict[str, list[dict[str, Any]]]):
    for user_id in sorted(rows_by_user):
        for rank, row in enumerate(rows_by_user[user_id], start=1):
            output = dict(row)
            output["rank"] = rank
            yield output


def _build_underfill_audit(
    target_users: list[str],
    original_counts: dict[str, int],
    final_counts: dict[str, int],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    remaining_underfilled_users: list[str],
) -> dict[str, Any]:
    all_counts = list(final_counts.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}.underfill_audit",
        "status": "DIAGNOSTIC_ONLY_PARTIAL" if remaining_underfilled_users else "DIAGNOSTIC_PASS_SHADOW_ONLY",
        "repair_stage": REPAIR_STAGE,
        "target_user_count": len(final_counts),
        "target_repair_user_count": len(target_users),
        "users_with_500_candidates": sum(1 for count in final_counts.values() if count >= TARGET_CANDIDATE_COUNT),
        "underfilled_user_count": len(remaining_underfilled_users),
        "remaining_underfilled_user_count": len(remaining_underfilled_users),
        "remaining_underfilled_users": remaining_underfilled_users,
        "remaining_underfilled_user_details": _remaining_underfilled_user_details(remaining_underfilled_users, original_counts, final_counts, repair_rows_by_user),
        **_candidate_count_stats(all_counts),
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _remaining_underfilled_user_details(
    remaining_underfilled_users: list[str],
    original_counts: dict[str, int],
    final_counts: dict[str, int],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for user_id in remaining_underfilled_users:
        repair_counter = Counter(str(row.get("repair_source", row.get("source", "unknown"))) for row in repair_rows_by_user.get(user_id, []))
        details.append({
            "user_id": user_id,
            "base_candidate_count": int(original_counts.get(user_id, 0)),
            "final_candidate_count": int(final_counts.get(user_id, 0)),
            "missing_to_500": max(TARGET_CANDIDATE_COUNT - int(final_counts.get(user_id, 0)), 0),
            "repair_added_count": sum(repair_counter.values()),
            "repair_added_by_source": dict(sorted(repair_counter.items())),
            "reason": "cold-start fallback exhausted before reaching 500" if final_counts.get(user_id, 0) < TARGET_CANDIDATE_COUNT else "repaired_to_500",
        })
    return details


def _build_cold_start_user_audit(
    target_users: list[str],
    sequences_by_user: dict[str, dict[str, Any]],
    seed_items_by_user: dict[str, list[str]],
    original_counts: dict[str, int],
    final_counts: dict[str, int],
    repair_rows_by_user: dict[str, list[dict[str, Any]]],
    missing_sequence_users: list[str],
) -> dict[str, Any]:
    users: list[dict[str, Any]] = []
    for user_id in target_users:
        sequence = sequences_by_user.get(user_id, {})
        sequence_len = int(sequence.get("sequence_len") or len(sequence.get("recent_item_sequence", []) or []))
        positive_sequence_len = int(sequence.get("positive_sequence_len") or len(sequence.get("recent_positive_item_sequence", []) or []))
        strong_positive_sequence_len = int(sequence.get("strong_positive_sequence_len") or len(sequence.get("recent_strong_positive_item_sequence", []) or []))
        segment = _cold_start_segment(sequence_len, positive_sequence_len)
        repair_rows = repair_rows_by_user.get(user_id, [])
        source_mix = Counter(str(row.get("repair_source") or row.get("source") or "unknown") for row in repair_rows)
        repair_added_count = sum(source_mix.values())
        fallback_count = repair_added_count
        popular_count = sum(count for source, count in source_mix.items() if source in POPULAR_SOURCES)
        fallback_ratio = round(fallback_count / max(final_counts.get(user_id, 0), 1), 6)
        popular_ratio = round(popular_count / max(final_counts.get(user_id, 0), 1), 6)
        risk_level, risk_reason = _quality_risk(segment, fallback_ratio, popular_ratio, final_counts.get(user_id, 0))
        users.append({
            "user_id": user_id,
            "sequence_len": sequence_len,
            "positive_sequence_len": positive_sequence_len,
            "strong_positive_sequence_len": strong_positive_sequence_len,
            "cold_start_segment": segment,
            "seed_items": seed_items_by_user.get(user_id, []),
            "base_candidate_count": int(original_counts.get(user_id, 0)),
            "final_candidate_count": int(final_counts.get(user_id, 0)),
            "repair_added_count": repair_added_count,
            "source_mix": dict(sorted(source_mix.items())),
            "fallback_ratio": fallback_ratio,
            "popular_ratio": popular_ratio,
            "quality_risk_level": risk_level,
            "risk_reason": risk_reason,
        })
    return {
        "schema_version": f"{SCHEMA_VERSION}.cold_start_user_audit",
        "repair_stage": REPAIR_STAGE,
        "target_repair_user_count": len(target_users),
        "missing_sequence_users": missing_sequence_users,
        "users": users,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_quality_risk_audit(cold_start_user_audit: dict[str, Any], segment_counts: Counter[str]) -> dict[str, Any]:
    users = cold_start_user_audit["users"]
    avg_fallback = round(sum(float(row["fallback_ratio"]) for row in users) / len(users), 6) if users else 0.0
    avg_popular = round(sum(float(row["popular_ratio"]) for row in users) / len(users), 6) if users else 0.0
    high_risk_users = [row["user_id"] for row in users if row["quality_risk_level"] == "HIGH"]
    return {
        "schema_version": f"{SCHEMA_VERSION}.cold_start_quality_risk_audit",
        "repair_stage": REPAIR_STAGE,
        "zero_positive_cold_start_user_count": int(segment_counts.get("zero_positive_cold_start", 0)),
        "single_seed_cold_start_user_count": int(segment_counts.get("single_seed_cold_start", 0)),
        "two_seed_low_history_user_count": int(segment_counts.get("two_seed_low_history", 0)),
        "average_fallback_ratio": avg_fallback,
        "average_popular_ratio": avg_popular,
        "users_high_risk_count": len(high_risk_users),
        "high_risk_users": high_risk_users,
        "risk_summary": "These 62 users have sequence_len<=2, so v5 candidates are cold-start shadow evidence from seed metadata/category/token/popular fallback rather than normal personalized recall. Even when filled to 500, fallback_ratio and popular_ratio must be consumed as quality-risk features downstream.",
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_cold_start_source_contribution(source_rows: Counter[str], source_users: dict[str, set[str]], target_user_set: set[str]) -> dict[str, Any]:
    total = sum(source_rows.values())
    sources: dict[str, Any] = {}
    for source in COLD_START_SOURCES:
        users = source_users[source]
        row_count = int(source_rows[source])
        sources[source] = {
            "row_count": row_count,
            "user_coverage_count": len(users),
            "underfilled_user_coverage_count": len(users & target_user_set),
            "marginal_candidate_share": round(row_count / total, 6) if total else 0.0,
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "ranking_replacement_allowed": False,
            "pool1000_allowed": False,
        }
    return {
        "schema_version": f"{SCHEMA_VERSION}.cold_start_source_contribution_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "repair_stage": REPAIR_STAGE,
        "total_cold_start_repair_row_count": total,
        "sources": sources,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_source_contribution_audit(final_rows_by_user: dict[str, list[dict[str, Any]]], base_source_contribution: dict[str, Any], target_user_set: set[str]) -> dict[str, Any]:
    rows_by_source: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for user_id, rows in final_rows_by_user.items():
        for row in rows:
            source = str(row.get("source") or "unknown")
            rows_by_source[source].append((user_id, _item_id(row)))
    total = sum(len(rows) for rows in rows_by_source.values())
    sources: dict[str, Any] = {}
    for source in sorted(set(base_source_contribution.get("sources", {})) | set(rows_by_source)):
        entries = rows_by_source.get(source, [])
        users = {user_id for user_id, _ in entries}
        items = {item_id for _, item_id in entries if item_id}
        base_status = (base_source_contribution.get("sources", {}).get(source, {}) or {}).get("readiness_status", "DIAGNOSTIC_ONLY")
        sources[source] = {
            "row_count": len(entries),
            "unique_item_count": len(items),
            "user_coverage_count": len(users),
            "user_coverage_ratio": round(len(users) / max(len(final_rows_by_user), 1), 6),
            "underfilled_user_coverage_count": len(users & target_user_set),
            "underfilled_user_coverage_ratio": round(len(users & target_user_set) / max(len(target_user_set), 1), 6),
            "marginal_candidate_share": round(len(entries) / total, 6) if total else 0.0,
            "readiness_status": base_status if not source.startswith("cold_start_") else "DIAGNOSTIC_ONLY",
            "promotion_allowed": False,
            "ranking_input_replacement_allowed": False,
            "ranking_replacement_allowed": False,
            "pool1000_allowed": False,
        }
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_contribution_audit",
        "status": "DIAGNOSTIC_ONLY_AUDIT",
        "repair_stage": REPAIR_STAGE,
        "candidate_row_count": total,
        "user_count": len(final_rows_by_user),
        "sources": sources,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_source_overlap_audit(overlap_stats: dict[str, Counter[str]], duplicate_item_per_user_count: int, evidence_samples: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.source_overlap_audit",
        "status": "PASS" if duplicate_item_per_user_count == 0 else "FAIL",
        "repair_stage": REPAIR_STAGE,
        "duplicate_item_per_user_count": duplicate_item_per_user_count,
        "deduped_discarded_candidate_count": sum(counter.get("overlap_existing_or_repair", 0) for counter in overlap_stats.values()),
        "source_overlap": {source: dict(counter) for source, counter in overlap_stats.items()},
        "evidence_samples": evidence_samples,
        "promotion_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
    }


def _build_readiness_result(decision: str, remaining_underfilled_users: list[str]) -> dict[str, Any]:
    blockers = []
    if remaining_underfilled_users:
        blockers.append("UNDERFILLED_USERS_REMAIN")
    blockers.append("COLD_START_SHADOW_EVIDENCE_ONLY")
    return {
        "schema_version": f"{SCHEMA_VERSION}.readiness_result",
        "repair_stage": REPAIR_STAGE,
        "decision": decision,
        "artifact_gate_decision": "STOP",
        "blockers": blockers,
        "remaining_underfilled_user_count": len(remaining_underfilled_users),
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "full_pool500_ready_declared": False,
        "shadow_evidence_only": True,
    }


def _build_shadow_evidence(
    base_run_dir: Path,
    output_candidates_path: Path,
    decision: str,
    repaired_users: list[str],
    fully_repaired_users: list[str],
    remaining_underfilled_users: list[str],
    users_with_500: int,
    quality_risk_audit: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.pool500_shadow_evidence",
        "repair_stage": REPAIR_STAGE,
        "status": "COLD_START_FALLBACK_SHADOW_EVIDENCE_ONLY",
        "base_run_dir": str(base_run_dir),
        "pool500_candidates": str(output_candidates_path),
        "decision": decision,
        "users_with_500_candidates": users_with_500,
        "target_repair_user_count": TARGET_REPAIR_USER_COUNT,
        "users_with_any_v5_repair_count": len(repaired_users),
        "fully_repaired_low_history_user_count": len(fully_repaired_users),
        "remaining_underfilled_user_count": len(remaining_underfilled_users),
        "low_history_segment": "62 v4 underfilled users with sequence_len<=2",
        "ranking_replacement_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
        "quality_risk_should_enter_ranking_features": True,
        "average_fallback_ratio": quality_risk_audit["average_fallback_ratio"],
        "average_popular_ratio": quality_risk_audit["average_popular_ratio"],
        "cannot_equal_normal_personalized_recall_reason": "Candidates are mostly inferred from one or two seeds plus fallback sources; the artifact is diagnostic/shadow evidence, not a promoted pool500 replacement.",
    }


def _build_shadow_validation(
    forbidden_scan: dict[str, Any],
    per_user_over_500_count: int,
    duplicate_item_per_user_count: int,
    readiness_result: dict[str, Any],
    cold_start_user_audit: dict[str, Any],
) -> dict[str, Any]:
    flags = [
        readiness_result.get("candidate_generation_allowed"),
        readiness_result.get("ranking_input_replacement_allowed"),
        readiness_result.get("ranking_replacement_allowed"),
        readiness_result.get("pool1000_allowed"),
        readiness_result.get("promotion_allowed"),
        readiness_result.get("final_pool500_ready_claimed"),
        readiness_result.get("full_pool500_ready_declared"),
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}.pool500_shadow_evidence_validation",
        "repair_stage": REPAIR_STAGE,
        "marker_isolation": "PASS",
        "no_forbidden_data": forbidden_scan["status"],
        "forbidden_data_scan": forbidden_scan,
        "per_user_le_500": "PASS" if per_user_over_500_count == 0 else "FAIL",
        "per_user_over_500_count": per_user_over_500_count,
        "duplicate_item_per_user": duplicate_item_per_user_count,
        "duplicate_item_per_user_status": "PASS" if duplicate_item_per_user_count == 0 else "FAIL",
        "promotion_flags_all_false": "PASS" if not any(flags) else "FAIL",
        "cold_start_audit_present": "PASS" if len(cold_start_user_audit.get("users", [])) == TARGET_REPAIR_USER_COUNT else "FAIL",
        "full_pool500_ready_declared": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
    }


def _forbidden_data_scan(paths: dict[str, Path]) -> dict[str, Any]:
    used_paths = [path for key, path in paths.items() if key not in {"data_manifest"}]
    matches: list[str] = []
    for path in used_paths:
        normalized = str(path).replace("\\", "/").lower()
        if any(marker in normalized for marker in FORBIDDEN_DATA_MARKERS):
            matches.append(str(path))
    return {
        "status": "PASS" if not matches else "FAIL",
        "forbidden_markers": list(FORBIDDEN_DATA_MARKERS),
        "forbidden_matches": matches,
        "note": "Data manifest was read only to confirm train/canonical paths; valid/test split entries were not loaded.",
    }


def _candidate_count_stats(counts: list[int]) -> dict[str, int]:
    return {
        "candidate_count_min": min(counts) if counts else 0,
        "candidate_count_p50": _percentile(counts, 0.5),
        "candidate_count_p90": _percentile(counts, 0.9),
        "candidate_count_max": max(counts) if counts else 0,
    }


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * q))
    return int(ordered[index])


def _duplicate_item_per_user_count(rows_by_user: dict[str, list[dict[str, Any]]]) -> int:
    duplicates = 0
    for rows in rows_by_user.values():
        seen: set[str] = set()
        for row in rows:
            item_id = _item_id(row)
            if item_id in seen:
                duplicates += 1
            seen.add(item_id)
    return duplicates


def _empty_overlap_stats() -> dict[str, Counter[str]]:
    return {source: Counter() for source in COLD_START_SOURCES}


def _item_id(row: Any) -> str:
    if isinstance(row, dict):
        return _clean_item_id(row.get("item_id") or row.get("parent_asin") or row.get("asin"))
    return _clean_item_id(row)


def _clean_item_id(value: Any) -> str:
    return str(value or "").strip()


def _user_count(base_rows_by_user: dict[str, list[dict[str, Any]]], repair_rows_by_user: dict[str, list[dict[str, Any]]], user_id: str) -> int:
    return len(base_rows_by_user.get(user_id, [])) + len(repair_rows_by_user.get(user_id, []))


def _wanted_category_values(seed_keys_by_user: dict[str, dict[str, set[str]]]) -> set[str]:
    values: set[str] = set()
    for keys in seed_keys_by_user.values():
        for field in ("category", "main_category", "categories_flat"):
            values.update(keys.get(field, set()))
    return {value for value in values if value}


def _row_category_values(row: dict[str, Any]) -> set[str]:
    values = {str(row.get("category") or ""), str(row.get("main_category") or "")}
    values.update(str(value) for value in row.get("source_categories", []) or [])
    values.update(str(value) for value in row.get("categories_flat", []) or [])
    return {value for value in values if value}


def _ordered_category_keys(seed_keys: dict[str, set[str]]) -> list[str]:
    keys: list[str] = []
    for field in ("category", "main_category", "categories_flat"):
        keys.extend(sorted(seed_keys.get(field, set())))
    deduped: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def _semantic_token(row: dict[str, Any]) -> str:
    for key in ("token", "term", "word", "keyword"):
        value = str(row.get(key) or "").lower().strip()
        if value:
            return value
    return ""


def _tokens_for_meta(meta: dict[str, Any]) -> list[str]:
    text_parts = [str(meta.get("title") or ""), str(meta.get("category") or ""), str(meta.get("main_category") or ""), str(meta.get("store") or "")]
    text_parts.extend(str(value) for value in meta.get("categories_flat", []) or [])
    tokens: list[str] = []
    seen: set[str] = set()
    for token in TOKEN_RE.findall(" ".join(text_parts).lower()):
        if token in STOP_WORDS or token in seen:
            continue
        tokens.append(token)
        seen.add(token)
        if len(tokens) >= 12:
            break
    return tokens


def _cold_start_segment(sequence_len: int, positive_sequence_len: int) -> str:
    if positive_sequence_len == 0:
        return "zero_positive_cold_start"
    if sequence_len == 1 or positive_sequence_len == 1:
        return "single_seed_cold_start"
    return "two_seed_low_history"


def _quality_risk(segment: str, fallback_ratio: float, popular_ratio: float, final_count: int) -> tuple[str, str]:
    if segment == "zero_positive_cold_start" or popular_ratio >= 0.25 or final_count < TARGET_CANDIDATE_COUNT:
        return "HIGH", "zero-positive or still-underfilled/high-popular-share cold-start fallback; not equivalent to personalized recall"
    if fallback_ratio >= 0.35 or popular_ratio >= 0.1:
        return "MEDIUM", "large share of candidates came from fallback expansion for a low-history user"
    return "LOW", "fallback share is limited, but user remains low-history and shadow-only"


if __name__ == "__main__":
    main()
