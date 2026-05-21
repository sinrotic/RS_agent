from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl
from rs_core.recsys.candidate_merge import metadata_neighbor_candidates_for_user
from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS, method_output_dir

SOURCE = "co_visit_fallback_repair"
SOURCE_STATUS = "TARGET_SLICE_DIAGNOSTIC"
SCHEMA_VERSION = "pool500_co_visit_fallback_repair_v1"
FORBIDDEN_TOKENS = ("holdout", "valid", "test", "lopo", "clean_10000")


def build_co_visit_fallback_repair_source(
    *,
    clean_manifest_path: Path,
    lightweight_views_manifest_path: Path,
    eligible_user_manifest_path: Path,
    output_root: Path,
    run_id: str,
    config_path: Path | None = None,
    max_metadata_rows: int = 250_000,
    candidate_per_user: int = 120,
    candidate_per_seed: int = 40,
    seed_window: int = 30,
    checkpoint_every_users: int = 50,
    overwrite: bool = False,
) -> dict[str, Any]:
    config = _load_yaml(config_path) if config_path else {}
    method_config = config.get("method_config") if isinstance(config.get("method_config"), dict) else {}
    max_metadata_rows = int(method_config.get("max_metadata_rows", max_metadata_rows))
    candidate_per_user = int(method_config.get("candidate_per_user", candidate_per_user))
    candidate_per_seed = int(method_config.get("candidate_per_seed", candidate_per_seed))
    seed_window = int(method_config.get("seed_window", seed_window))
    checkpoint_every_users = int(method_config.get("checkpoint_every_users", checkpoint_every_users))

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
    semantic_inputs_path = _resolve_repo_path(views_manifest["outputs"]["semantic_recall_inputs"])
    target_users = [str(user_id) for user_id in eligible_manifest.get("eligible_user_ids", [])]
    sequences = _load_target_sequences(train_sequences_path, target_users)
    target_seed_items = {
        item_id
        for sequence in sequences.values()
        for item_id in _recent_unique(sequence.get("recent_positive_item_sequence", []), seed_window)
    }
    metadata_index = _load_metadata_index(semantic_inputs_path, sequences, max_metadata_rows, seed_window)

    generation_config = {
        "metadata_neighbor_enabled": True,
        "metadata_neighbor_seed_window": seed_window,
        "metadata_neighbor_per_seed": candidate_per_seed,
        "metadata_neighbor_per_user": candidate_per_user,
        "metadata_neighbor_min_token_overlap": int(method_config.get("min_token_overlap", 1)),
        "metadata_neighbor_max_bucket_candidates": int(method_config.get("max_bucket_candidates", 1000)),
        "metadata_neighbor_category_weight": float(method_config.get("category_weight", 2.0)),
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
        candidates = metadata_neighbor_candidates_for_user(sequence or {"user_id": user_id}, metadata_index, generation_config) if sequence else []
        seed_items = _recent_unique(sequence.get("recent_positive_item_sequence", []) if sequence else [], seed_window)
        co_visit_seed_count = sum(1 for item_id in seed_items if item_id in metadata_index)
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
            "metadata_neighbor_candidate_count": len(user_rows),
            "metadata_neighbor_covered": len(user_rows) > 0,
            "repair_candidate_count": len(user_rows),
        }
        if checkpoint_every_users > 0 and processed_count % checkpoint_every_users == 0:
            write_json(checkpoint_dir / f"processed_{processed_count:04d}.json", {"processed_user_count": processed_count, "candidate_row_count": len(rows)})

    write_jsonl(source_candidates_path, rows)
    candidate_counts = [per_user[user_id]["repair_candidate_count"] for user_id in target_users]
    stats = _count_stats(candidate_counts)
    seed_covered_users = sum(1 for item in per_user.values() if item["co_visit_seed_covered"])
    metadata_covered_users = sum(1 for item in per_user.values() if item["metadata_neighbor_covered"])
    user_coverage_count = sum(1 for count in candidate_counts if count > 0)
    unique_items = len({row["item_id"] for row in rows})
    input_paths = [clean_manifest_path, lightweight_views_manifest_path, eligible_user_manifest_path, train_sequences_path, semantic_inputs_path]
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
        "co_visit_seed_coverage": _coverage(seed_covered_users, len(target_users)),
        "metadata_neighbor_coverage": _coverage(metadata_covered_users, len(target_users)),
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
    }
    coverage_audit = {
        "schema_version": f"{SCHEMA_VERSION}.coverage_audit",
        "status": "PASS" if user_coverage_count else "EMPTY",
        "source": SOURCE,
        "co_visit_seed_coverage": _coverage(seed_covered_users, len(target_users)),
        "metadata_neighbor_coverage": _coverage(metadata_covered_users, len(target_users)),
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
    parser.add_argument("--clean-manifest", type=Path, default=Path("data/processed/amazon_2023_recall_clean_full/manifest.json"))
    parser.add_argument("--lightweight-views-manifest", type=Path, default=Path("data/processed/amazon_2023_recall_views_full_lightweight/manifest.json"))
    parser.add_argument("--eligible-user-manifest", type=Path, default=Path("outputs/recall/pool500_main_route_direct_recall_full_promoted/eligible_user_manifest.json"))
    parser.add_argument("--config", type=Path, default=Path("configs/recall/full_data_pool500/co_visit_fallback_repair/source_config.yaml"))
    parser.add_argument("--output-root", type=Path, default=Path("outputs/recall/pool500_method_sources"))
    parser.add_argument("--run-id", default=datetime.now(UTC).strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--max-metadata-rows", type=int, default=250_000)
    parser.add_argument("--candidate-per-user", type=int, default=120)
    parser.add_argument("--candidate-per-seed", type=int, default=40)
    parser.add_argument("--seed-window", type=int, default=30)
    parser.add_argument("--checkpoint-every-users", type=int, default=50)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_co_visit_fallback_repair_source(
        clean_manifest_path=args.clean_manifest,
        lightweight_views_manifest_path=args.lightweight_views_manifest,
        eligible_user_manifest_path=args.eligible_user_manifest,
        output_root=args.output_root,
        run_id=args.run_id,
        config_path=args.config,
        max_metadata_rows=args.max_metadata_rows,
        candidate_per_user=args.candidate_per_user,
        candidate_per_seed=args.candidate_per_seed,
        seed_window=args.seed_window,
        checkpoint_every_users=args.checkpoint_every_users,
        overwrite=args.overwrite,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _resolve_repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parents[6] / candidate


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
