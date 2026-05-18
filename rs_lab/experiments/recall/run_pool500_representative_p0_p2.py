from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_lab.experiments.recall.run_full_lightweight_recall_e2e import MIN_FREE_BYTES, run_representative_e2e
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    _candidate_metrics,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _load_baseline_candidates,
    _load_evaluation_positives,
)

SCHEMA_VERSION = "pool500_representative_p0_p2_v1"
DEFAULT_CLEAN_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_VIEWS_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_views_full_lightweight"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "contract_precheck_or_p0_p2"
FORBIDDEN_PATH_PARTS = ("amazon_2023_recall_clean_10000", "amazon_2023_recall_views_10000")
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run representative pool500 recall-only P0-P2 artifacts.")
    parser.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    parser.add_argument("--views-dir", default=str(DEFAULT_VIEWS_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--limit-users", type=int, default=500)
    parser.add_argument("--pool200-size", type=int, default=200)
    parser.add_argument("--pool500-size", type=int, default=500)
    parser.add_argument("--popular-per-user", type=int, default=220)
    parser.add_argument("--category-per-user", type=int, default=220)
    parser.add_argument("--category-per-bucket", type=int, default=80)
    parser.add_argument("--semantic-per-user", type=int, default=120)
    parser.add_argument("--semantic-seed-window", type=int, default=10)
    parser.add_argument("--semantic-min-overlap", type=int, default=1)
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_representative_p0_p2(
    *,
    clean_dir: Path = DEFAULT_CLEAN_DIR,
    views_dir: Path = DEFAULT_VIEWS_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    limit_users: int = 500,
    pool200_size: int = 200,
    pool500_size: int = 500,
    popular_per_user: int = 220,
    category_per_user: int = 220,
    category_per_bucket: int = 80,
    semantic_per_user: int = 120,
    semantic_seed_window: int = 10,
    semantic_min_overlap: int = 1,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()
    if limit_users <= 0 or limit_users > 1000:
        raise ValueError("--limit-users must be between 1 and 1000 for representative scope")
    if pool200_size != 200:
        raise ValueError("P0-P2 same-scope baseline must remain pool200")
    if pool500_size != 500:
        raise ValueError("P0-P2 experiment must remain pool500")
    if pool500_size <= pool200_size:
        raise ValueError("pool500-size must be greater than pool200-size")

    clean_dir = clean_dir.resolve()
    views_dir = views_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck_scope(clean_dir, views_dir, output_dir, min_free_bytes)

    output_dir.mkdir(parents=True)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    sample_path = output_dir / "representative_user_sample.json"
    representative_sample = _write_representative_sample(clean_dir / "user_sequences.train.jsonl", sample_path, limit_users)

    common_generation_args = {
        "clean_dir": clean_dir,
        "views_dir": views_dir,
        "limit_users": limit_users,
        "popular_per_user": popular_per_user,
        "category_per_user": category_per_user,
        "category_per_bucket": category_per_bucket,
        "semantic_per_user": semantic_per_user,
        "semantic_seed_window": semantic_seed_window,
        "semantic_min_overlap": semantic_min_overlap,
        "min_free_bytes": min_free_bytes,
        "enforce_venv": enforce_venv,
    }
    pool200_manifest = run_representative_e2e(
        output_dir=output_dir / "pool200_same_scope",
        candidate_pool_size=pool200_size,
        **common_generation_args,
    )
    pool500_manifest = run_representative_e2e(
        output_dir=output_dir / "pool500_recall_only",
        candidate_pool_size=pool500_size,
        **common_generation_args,
    )

    user_ids = set(representative_sample["user_ids"])
    eval_paths = [clean_dir / name for name in ("canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl")]
    positives_by_user = _load_evaluation_positives(eval_paths, user_ids)
    pool200_by_user = _load_baseline_candidates(output_dir / "pool200_same_scope" / "candidates.jsonl")
    pool500_by_user = _load_baseline_candidates(output_dir / "pool500_recall_only" / "candidates.jsonl")
    pool200_metrics = _candidate_metrics(pool200_by_user, positives_by_user)
    pool500_metrics = _candidate_metrics(pool500_by_user, positives_by_user)
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "scope": "representative_pool500_recall_only_p0_p2",
        "train_only_candidate_generation": True,
        "evaluation_only": {
            "read_files": [str(path) for path in eval_paths],
            "contract": "valid/test are read only after candidate generation for metrics and never construct candidates",
        },
        "pool200_same_scope": pool200_metrics,
        "pool500_recall_only": pool500_metrics,
        "delta": {
            "candidate_row_count": pool500_metrics["candidate_row_count"] - pool200_metrics["candidate_row_count"],
            "candidate_hit_users": pool500_metrics["candidate_hit_users"] - pool200_metrics["candidate_hit_users"],
            "recall_at_pool": round(pool500_metrics["recall_at_pool"] - pool200_metrics["recall_at_pool"], 6),
            "empty_candidate_rate": round(pool500_metrics["empty_candidate_rate"] - pool200_metrics["empty_candidate_rate"], 6),
        },
    }
    write_json(output_dir / "pool200_same_scope" / "metrics.json", pool200_metrics)
    write_json(output_dir / "pool500_recall_only" / "metrics.json", pool500_metrics)
    write_json(output_dir / "metrics.json", metrics)

    resolved_inputs = _resolved_inputs(clean_dir, views_dir, output_dir, representative_sample, pool200_manifest, pool500_manifest)
    source_audit = _source_audit(clean_dir, views_dir, output_dir, eval_paths, resolved_inputs)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "representative_pool500_recall_only_not_ranking_input",
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "min_free_bytes": min_free_bytes,
        "representative_user_count": representative_sample["user_count"],
        "pool200_candidate_pool_size": pool200_size,
        "pool500_candidate_pool_size": pool500_size,
        "train_only_candidate_generation": True,
        "candidate_generation_uses_holdout": False,
        "ranking_isolation": {
            "pool500_as_ranking_input": False,
            "ranking_default_input_modified": False,
            "frozen_pool200_ranking_baseline_replaced": False,
        },
        "disabled_outputs": {
            "pool1000": True,
            "two_tower_training": True,
            "graph_training": True,
            "mf_training": True,
            "ranking": True,
        },
        "required_artifacts": {
            "representative_user_sample": str(sample_path),
            "resolved_inputs": str(output_dir / "resolved_inputs.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "metrics": str(output_dir / "metrics.json"),
            "manifest": str(output_dir / "manifest.json"),
            "pool200_candidates": str(output_dir / "pool200_same_scope" / "candidates.jsonl"),
            "pool200_metrics": str(output_dir / "pool200_same_scope" / "metrics.json"),
            "pool500_candidates": str(output_dir / "pool500_recall_only" / "candidates.jsonl"),
            "pool500_metrics": str(output_dir / "pool500_recall_only" / "metrics.json"),
        },
    }
    write_json(output_dir / "resolved_inputs.json", resolved_inputs)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _precheck_scope(clean_dir: Path, views_dir: Path, output_dir: Path, min_free_bytes: int) -> None:
    for path in (clean_dir, views_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden 10k path for representative pool500 P0-P2: {path}")
    if output_dir.exists() and (output_dir / "manifest.json").exists():
        raise FileExistsError(f"Completed output directory already exists: {output_dir}")
    for child_name in ("pool200_same_scope", "pool500_recall_only"):
        if (output_dir / child_name).exists():
            raise FileExistsError(f"Partial child output directory already exists: {output_dir / child_name}")
    if not (clean_dir / "user_sequences.train.jsonl").is_file():
        raise FileNotFoundError(clean_dir / "user_sequences.train.jsonl")
    if not views_dir.is_dir():
        raise FileNotFoundError(views_dir)
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _write_representative_sample(sequence_path: Path, output_path: Path, limit_users: int) -> dict[str, Any]:
    user_ids: list[str] = []
    sequence_lengths: dict[str, int] = {}
    for row in iter_jsonl(sequence_path):
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        user_ids.append(user_id)
        sequence_lengths[user_id] = len(row.get("recent_item_sequence", []) or [])
        if len(user_ids) >= limit_users:
            break
    if len(user_ids) < limit_users:
        raise ValueError(f"Only found {len(user_ids)} representative users, need {limit_users}")
    sample = {
        "schema_version": SCHEMA_VERSION,
        "selection": "first_n_train_sequence_users",
        "user_count": len(user_ids),
        "user_ids": user_ids,
        "sequence_length_summary": {
            "min": min(sequence_lengths.values()),
            "max": max(sequence_lengths.values()),
            "avg": round(sum(sequence_lengths.values()) / len(sequence_lengths), 6),
        },
        "source_file": str(sequence_path),
        "source_signature": _file_signature(sequence_path),
    }
    write_json(output_path, sample)
    return sample


def _resolved_inputs(
    clean_dir: Path,
    views_dir: Path,
    output_dir: Path,
    representative_sample: dict[str, Any],
    pool200_manifest: dict[str, Any],
    pool500_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "full_clean_dir": str(clean_dir),
        "full_lightweight_views_dir": str(views_dir),
        "representative_user_sample": {
            "path": str(output_dir / "representative_user_sample.json"),
            "user_count": representative_sample["user_count"],
            "selection": representative_sample["selection"],
        },
        "pool200_same_scope": {
            "output_dir": pool200_manifest["output_dir"],
            "candidate_pool_size": pool200_manifest["config"]["candidate_pool_size"],
            "candidates": pool200_manifest["outputs"]["candidates"],
            "manifest": str(output_dir / "pool200_same_scope" / "manifest.json"),
        },
        "pool500_recall_only": {
            "output_dir": pool500_manifest["output_dir"],
            "candidate_pool_size": pool500_manifest["config"]["candidate_pool_size"],
            "candidates": pool500_manifest["outputs"]["candidates"],
            "manifest": str(output_dir / "pool500_recall_only" / "manifest.json"),
        },
    }


def _source_audit(clean_dir: Path, views_dir: Path, output_dir: Path, eval_paths: list[Path], resolved_inputs: dict[str, Any]) -> dict[str, Any]:
    candidate_read_files = [
        str(clean_dir / "user_sequences.train.jsonl"),
        str(views_dir / "manifest.json"),
        str(views_dir / "stats.json"),
        str(views_dir / "popular_recall.jsonl"),
        str(views_dir / "category_recall_items.jsonl"),
        str(views_dir / "category_top_items.jsonl"),
        str(views_dir / "semantic_recall_inputs.jsonl"),
        str(views_dir / "semantic_inverted_index.jsonl"),
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "scope": "representative_pool500_recall_only_p0_p2",
        "train_only_candidate_generation": True,
        "candidate_generation_uses_holdout": False,
        "candidate_generation_read_files": candidate_read_files,
        "evaluation_only_read_files": [str(path) for path in eval_paths],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "no_10k_source": True,
        "no_full_clean_copy": True,
        "ranking_isolation": {
            "ranking_default_input_modified": False,
            "pool500_as_ranking_input": False,
            "pool1000_generated": False,
        },
        "resolved_inputs": resolved_inputs,
        "source_signatures": {
            "train_sequences": _file_signature(clean_dir / "user_sequences.train.jsonl"),
            "views_manifest": _file_signature(views_dir / "manifest.json"),
            "pool200_candidates": _file_signature(output_dir / "pool200_same_scope" / "candidates.jsonl"),
            "pool500_candidates": _file_signature(output_dir / "pool500_recall_only" / "candidates.jsonl"),
        },
    }


def main() -> None:
    args = parse_args()
    manifest = run_pool500_representative_p0_p2(
        clean_dir=Path(args.clean_dir),
        views_dir=Path(args.views_dir),
        output_dir=Path(args.output_dir),
        limit_users=args.limit_users,
        pool200_size=args.pool200_size,
        pool500_size=args.pool500_size,
        popular_per_user=args.popular_per_user,
        category_per_user=args.category_per_user,
        category_per_bucket=args.category_per_bucket,
        semantic_per_user=args.semantic_per_user,
        semantic_seed_window=args.semantic_seed_window,
        semantic_min_overlap=args.semantic_min_overlap,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["required_artifacts"]["manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
