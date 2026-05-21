from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.common.runtime import enforce_project_venv
from rs_core.recsys.candidate_merge import semantic_title_category_expansion_candidates_for_user
from rs_lab.experiments.recall.pool500.common.source_layout import method_output_dir

ROOT = Path(__file__).resolve().parents[6]
SOURCE = "semantic_title_category_expansion"
SCHEMA_VERSION = "pool500_semantic_title_category_expansion_source_v1"
DEFAULT_CLEAN_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full" / "manifest.json"
DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight" / "manifest.json"
DEFAULT_ELIGIBLE_USER_MANIFEST = ROOT / "outputs" / "recall" / "pool500_main_route_direct_recall_full_promoted" / "eligible_user_manifest.json"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "recall" / "pool500_method_sources"
DEFAULT_SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
FORBIDDEN_SPLIT_PARTS = {"valid", "test", "lopo"}
FORBIDDEN_PATH_SUBSTRINGS = ("holdout", "clean_10000", "views_10000", "pool1000")
TEXT_FIELDS = ("title_clean", "main_category", "categories_flat")


def build_semantic_title_category_expansion_source(
    *,
    clean_manifest_path: Path = DEFAULT_CLEAN_MANIFEST,
    lightweight_views_manifest_path: Path = DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST,
    eligible_user_manifest_path: Path | None = DEFAULT_ELIGIBLE_USER_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    limit_users: int = 500,
    seed_window: int = 20,
    per_user: int = 80,
    per_seed: int = 40,
    per_token_item_limit: int = 2000,
    max_candidate_items: int = 80000,
    overwrite: bool = False,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        enforce_project_venv(ROOT)
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
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

    target_user_ids = _target_user_ids(eligible_user_manifest_path, limit_users)
    sequences = _load_target_sequences(train_sequences_path, target_user_ids, limit_users)
    checkpoint_path = output_dir / "checkpoint.json"
    write_json(checkpoint_path, {"stage": "target_sequences_loaded", "user_count": len(sequences), "source": SOURCE})

    seed_items_by_user = _seed_items_by_user(sequences, seed_window)
    seed_items = {item for items in seed_items_by_user.values() for item in items}
    seed_records = _load_records_by_ids(semantic_inputs_path, seed_items)
    seed_tokens = _record_tokens(seed_records.values())
    candidate_item_ids, token_bucket_stats = _candidate_ids_from_inverted_index(
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
        "source": SOURCE,
    })

    input_dataset_path = output_dir / "semantic_title_category_input_dataset.jsonl"
    write_jsonl(input_dataset_path, _input_dataset_rows(semantic_index))

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
        }
    }
    rows: list[dict[str, Any]] = []
    per_user_counts: dict[str, int] = {}
    undercovered_reasons: Counter[str] = Counter()
    user_seed_metadata_hits: dict[str, int] = {}
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        candidates = semantic_title_category_expansion_candidates_for_user(sequence, semantic_index, generation_config)
        per_user_counts[user_id] = len(candidates)
        seed_hits = sum(1 for item in seed_items_by_user.get(user_id, []) if item in seed_records)
        user_seed_metadata_hits[user_id] = seed_hits
        if not seed_items_by_user.get(user_id):
            undercovered_reasons["no_positive_seed_items"] += 1
        elif seed_hits == 0:
            undercovered_reasons["missing_seed_item_metadata"] += 1
        elif not candidates:
            undercovered_reasons["no_title_category_overlap_candidates"] += 1
        elif len(candidates) < per_user:
            undercovered_reasons["below_method_target_per_user"] += 1
        for rank, candidate in enumerate(candidates, start=1):
            rows.append({
                "user_id": user_id,
                "item_id": candidate.item_id,
                "source": SOURCE,
                "canonical_source": SOURCE,
                "sources": [SOURCE],
                "score": candidate.score,
                "rank": rank,
                "metadata": {**candidate.metadata, "source_scores": {SOURCE: candidate.score}},
            })
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
        },
        "runtime_seconds": round(perf_counter() - started, 6),
        "source_signatures": signatures,
    }
    method_dataset_manifest = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "canonical_source": SOURCE,
        "source_status": DEFAULT_SOURCE_STATUS,
        "dataset_name": "semantic_title_category_input_dataset",
        "train_only": True,
        "target_user_count": len(sequences),
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
    path = Path(raw_path)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _target_user_ids(path: Path | None, limit_users: int) -> set[str] | None:
    if path is None or not path.is_file():
        return None
    payload = read_json(path)
    user_ids = payload.get("eligible_user_ids")
    if not isinstance(user_ids, list):
        return None
    selected = [str(user_id) for user_id in user_ids if user_id]
    if limit_users > 0:
        selected = selected[:limit_users]
    return set(selected)


def _load_target_sequences(path: Path, target_user_ids: set[str] | None, limit_users: int) -> list[dict[str, Any]]:
    sequences: list[dict[str, Any]] = []
    if target_user_ids:
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


def _candidate_ids_from_inverted_index(
    path: Path,
    seed_tokens: set[str],
    *,
    per_token_item_limit: int,
    max_candidate_items: int,
) -> tuple[set[str], dict[str, Any]]:
    candidate_ids: set[str] = set()
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
        for item_id in raw_items[:per_token_item_limit]:
            candidate_ids.add(str(item_id))
            if len(candidate_ids) >= max_candidate_items:
                return candidate_ids, {
                    "seed_token_count": len(seed_tokens),
                    "matched_token_count": matched_tokens,
                    "truncated_token_bucket_count": truncated_token_buckets,
                    "candidate_item_id_count": len(candidate_ids),
                    "max_candidate_items_reached": True,
                }
    return candidate_ids, {
        "seed_token_count": len(seed_tokens),
        "matched_token_count": matched_tokens,
        "truncated_token_bucket_count": truncated_token_buckets,
        "candidate_item_id_count": len(candidate_ids),
        "max_candidate_items_reached": False,
    }


def _with_semantic_tokens(record: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(record)
    enriched["semantic_tokens"] = _tokens_from_fields(record, TEXT_FIELDS)
    return enriched


def _record_tokens(records: Iterable[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for record in records:
        tokens.update(_tokens_from_fields(record, TEXT_FIELDS))
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


def _title_tokens(record: dict[str, Any]) -> set[str]:
    return _tokens_from_fields(record, ("title_clean",))


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
    parser.add_argument("--clean-manifest", type=Path, default=DEFAULT_CLEAN_MANIFEST)
    parser.add_argument("--lightweight-views-manifest", type=Path, default=DEFAULT_LIGHTWEIGHT_VIEWS_MANIFEST)
    parser.add_argument("--eligible-user-manifest", type=Path, default=DEFAULT_ELIGIBLE_USER_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--limit-users", type=int, default=500)
    parser.add_argument("--per-user", type=int, default=80)
    parser.add_argument("--per-seed", type=int, default=40)
    parser.add_argument("--per-token-item-limit", type=int, default=2000)
    parser.add_argument("--max-candidate-items", type=int, default=80000)
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
        limit_users=args.limit_users,
        per_user=args.per_user,
        per_seed=args.per_seed,
        per_token_item_limit=args.per_token_item_limit,
        max_candidate_items=args.max_candidate_items,
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
