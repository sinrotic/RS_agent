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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json
from scripts.run_full_lightweight_recall_e2e import MIN_FREE_BYTES
from scripts.run_phase1_itemcf_covisit_representative_merge_eval import (
    _candidate_metrics,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _load_evaluation_positives,
)

SCHEMA_VERSION = "pool500_representative_p3_p4_v1"
DEFAULT_INPUT_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "contract_precheck_or_p0_p2"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "p3_p4_audit"
DEFAULT_CLEAN_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
FORBIDDEN_PATH_MARKERS = (
    "amazon_2023_recall_clean_10000",
    "amazon_2023_recall_views_10000",
    "pool1000",
)
FORBIDDEN_GENERATION_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)
RANKING_BASELINE_CONFIG = ROOT / "configs" / "recall" / "phase_1_21" / "phase_1_21_recall_coverage_pool200_experimental.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate pool500 representative P3-P4 comparison and audits.")
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    parser.add_argument("--min-free-bytes", type=int, default=MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_representative_p3_p4_audit(
    *,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    clean_dir: Path = DEFAULT_CLEAN_DIR,
    min_free_bytes: int = MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()

    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    clean_dir = clean_dir.resolve()
    _precheck(input_dir, output_dir, clean_dir, min_free_bytes)

    sample = read_json(input_dir / "representative_user_sample.json")
    user_ids = set(sample["user_ids"])
    eval_paths = [clean_dir / "canonical_interactions.valid.jsonl", clean_dir / "canonical_interactions.test.jsonl"]
    positives_by_user = _load_evaluation_positives(eval_paths, user_ids)
    pool200_path = input_dir / "pool200_same_scope" / "candidates.jsonl"
    pool500_path = input_dir / "pool500_recall_only" / "candidates.jsonl"
    pool200_by_user, pool200_source_by_user = _load_candidates_with_sources(pool200_path)
    pool500_by_user, pool500_source_by_user = _load_candidates_with_sources(pool500_path)
    pool200_metrics = _candidate_metrics(pool200_by_user, positives_by_user)
    pool500_metrics = _candidate_metrics(pool500_by_user, positives_by_user)
    comparison = _comparison(
        sample=sample,
        positives_by_user=positives_by_user,
        pool200_by_user=pool200_by_user,
        pool500_by_user=pool500_by_user,
        pool200_source_by_user=pool200_source_by_user,
        pool500_source_by_user=pool500_source_by_user,
        pool200_metrics=pool200_metrics,
        pool500_metrics=pool500_metrics,
    )
    source_audit = read_json(input_dir / "source_audit.json")
    leakage_audit = _leakage_audit(input_dir, clean_dir, source_audit, eval_paths)
    resource_audit = _resource_audit(input_dir, output_dir, min_free_bytes)
    ranking_isolation_audit = _ranking_isolation_audit(input_dir, pool500_path)

    output_dir.mkdir(parents=True)
    write_json(output_dir / "pool500_vs_pool200_same_scope_comparison.json", comparison)
    write_json(output_dir / "leakage_audit.json", leakage_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "ranking_isolation_audit.json", ranking_isolation_audit)

    status = "PASS" if all(
        artifact["status"] == "PASS"
        for artifact in (comparison, leakage_audit, resource_audit, ranking_isolation_audit)
    ) else "FAIL"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "representative_pool500_p3_p4_recall_only_audit",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "same_representative_sample": True,
        "same_scope_comparison": True,
        "ranking_boundary": "pool500 audit only; frozen pool200 ranking input remains unchanged",
        "required_artifacts": {
            "pool500_vs_pool200_same_scope_comparison": str(output_dir / "pool500_vs_pool200_same_scope_comparison.json"),
            "leakage_audit": str(output_dir / "leakage_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "ranking_isolation_audit": str(output_dir / "ranking_isolation_audit.json"),
            "manifest": str(output_dir / "manifest.json"),
        },
        "input_signatures": {
            "representative_user_sample": _file_signature(input_dir / "representative_user_sample.json"),
            "pool200_candidates": _file_signature(pool200_path),
            "pool500_candidates": _file_signature(pool500_path),
            "source_audit": _file_signature(input_dir / "source_audit.json"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _precheck(input_dir: Path, output_dir: Path, clean_dir: Path, min_free_bytes: int) -> None:
    for path in (input_dir, output_dir, clean_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(marker in lowered for marker in FORBIDDEN_PATH_MARKERS):
            raise ValueError(f"Forbidden pool500 P3-P4 path marker in {path}")
    required = [
        input_dir / "representative_user_sample.json",
        input_dir / "source_audit.json",
        input_dir / "manifest.json",
        input_dir / "pool200_same_scope" / "candidates.jsonl",
        input_dir / "pool500_recall_only" / "candidates.jsonl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing P0-P2 inputs: {missing}")
    if output_dir.exists() and (output_dir / "manifest.json").exists():
        raise FileExistsError(f"Completed output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _load_candidates_with_sources(path: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, list[str]]]]:
    candidates_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_by_user: dict[str, dict[str, list[str]]] = defaultdict(dict)
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if not user_id or not item_id:
            continue
        candidates_by_user[user_id].append(row)
        source_by_user[user_id][item_id] = list(row.get("sources") or [])
    return dict(candidates_by_user), {user: dict(items) for user, items in source_by_user.items()}


def _comparison(
    *,
    sample: dict[str, Any],
    positives_by_user: dict[str, set[str]],
    pool200_by_user: dict[str, list[dict[str, Any]]],
    pool500_by_user: dict[str, list[dict[str, Any]]],
    pool200_source_by_user: dict[str, dict[str, list[dict[str, Any]]]],
    pool500_source_by_user: dict[str, dict[str, list[dict[str, Any]]]],
    pool200_metrics: dict[str, Any],
    pool500_metrics: dict[str, Any],
) -> dict[str, Any]:
    pool200_hit_users = _hit_users(pool200_by_user, positives_by_user)
    pool500_hit_users = _hit_users(pool500_by_user, positives_by_user)
    exclusive_hit_users = sorted(pool500_hit_users - pool200_hit_users)
    source_counter: Counter[str] = Counter()
    exclusive_details: list[dict[str, Any]] = []
    for user_id in exclusive_hit_users:
        positives = positives_by_user[user_id]
        pool200_items = _candidate_item_set(pool200_by_user.get(user_id, []))
        exclusive_items = []
        for row in pool500_by_user.get(user_id, []):
            item_id = str(row.get("item_id", ""))
            if item_id in positives and item_id not in pool200_items:
                sources = pool500_source_by_user.get(user_id, {}).get(item_id, [])
                source_counter.update(sources or ["unknown"])
                exclusive_items.append({"item_id": item_id, "sources": sources, "rank_pool500": row.get("rank")})
        exclusive_details.append({"user_id": user_id, "exclusive_hit_items": exclusive_items})
    pool200_counts = [len(items) for items in pool200_by_user.values()]
    pool500_counts = [len(items) for items in pool500_by_user.values()]
    same_users = set(pool200_by_user) == set(pool500_by_user) == set(sample["user_ids"])
    recall_delta = round(pool500_metrics["recall_at_pool"] - pool200_metrics["recall_at_pool"], 6)
    hit_delta = pool500_metrics["candidate_hit_users"] - pool200_metrics["candidate_hit_users"]
    adds_recall_side_value = hit_delta > 0 and recall_delta > 0
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "scope": "same_representative_users_same_recall_only_scope",
        "same_representative_sample": same_users,
        "representative_user_count": sample["user_count"],
        "users_with_holdout": pool500_metrics["users_with_holdout"],
        "candidate_hit_users_pool200": pool200_metrics["candidate_hit_users"],
        "candidate_hit_users_pool500": pool500_metrics["candidate_hit_users"],
        "recall_at_pool200": pool200_metrics["recall_at_pool"],
        "recall_at_pool500": pool500_metrics["recall_at_pool"],
        "delta": {
            "candidate_hit_users": hit_delta,
            "recall_at_pool": recall_delta,
            "candidate_row_count": pool500_metrics["candidate_row_count"] - pool200_metrics["candidate_row_count"],
        },
        "candidate_count_stats": {
            "pool200": _count_stats(pool200_counts),
            "pool500": _count_stats(pool500_counts),
        },
        "duplicate_empty_fallback_comparison": {
            "pool200": {
                "duplicate_candidate_rows": _duplicate_count(pool200_by_user),
                "empty_candidate_users": pool200_metrics["empty_candidate_users"],
                "empty_candidate_rate": pool200_metrics["empty_candidate_rate"],
                "fallback_rate": pool200_metrics["fallback_rate"],
            },
            "pool500": {
                "duplicate_candidate_rows": _duplicate_count(pool500_by_user),
                "empty_candidate_users": pool500_metrics["empty_candidate_users"],
                "empty_candidate_rate": pool500_metrics["empty_candidate_rate"],
                "fallback_rate": pool500_metrics["fallback_rate"],
            },
        },
        "exclusive_hit_users_201_500": len(exclusive_hit_users),
        "exclusive_hit_user_ids_201_500": exclusive_hit_users,
        "exclusive_hit_details_201_500": exclusive_details,
        "source_attribution_for_exclusive_hits": dict(sorted(source_counter.items())),
        "pool500_adds_recall_side_value": adds_recall_side_value,
        "decision_reason": "pool500 improves same-scope representative candidate-hit users and recall@pool" if adds_recall_side_value else "pool500 does not improve both same-scope candidate-hit users and recall@pool",
    }


def _hit_users(candidates_by_user: dict[str, list[dict[str, Any]]], positives_by_user: dict[str, set[str]]) -> set[str]:
    return {user_id for user_id, positives in positives_by_user.items() if positives & _candidate_item_set(candidates_by_user.get(user_id, []))}


def _candidate_item_set(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("item_id", "")) for row in rows if row.get("item_id")}


def _count_stats(counts: list[int]) -> dict[str, float | int]:
    sorted_counts = sorted(counts)
    if not sorted_counts:
        return {"min": 0, "max": 0, "avg": 0.0, "p50": 0, "p95": 0}
    return {
        "min": sorted_counts[0],
        "max": sorted_counts[-1],
        "avg": round(sum(sorted_counts) / len(sorted_counts), 6),
        "p50": sorted_counts[len(sorted_counts) // 2],
        "p95": sorted_counts[min(len(sorted_counts) - 1, int(len(sorted_counts) * 0.95))],
    }


def _duplicate_count(candidates_by_user: dict[str, list[dict[str, Any]]]) -> int:
    return sum(len(items) - len(_candidate_item_set(items)) for items in candidates_by_user.values())


def _leakage_audit(input_dir: Path, clean_dir: Path, source_audit: dict[str, Any], eval_paths: list[Path]) -> dict[str, Any]:
    generation_files = [Path(path) for path in source_audit.get("candidate_generation_read_files", [])]
    forbidden_files = [clean_dir / name for name in FORBIDDEN_GENERATION_FILES]
    forbidden_in_generation = sorted(
        str(path) for path in generation_files if path.name in {forbidden.name for forbidden in forbidden_files}
    )
    forbidden_marker_paths = [
        str(path) for path in generation_files if any(marker in str(path).replace("\\", "/").lower() for marker in FORBIDDEN_PATH_MARKERS)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not forbidden_in_generation and not forbidden_marker_paths else "FAIL",
        "candidate_generation_uses_valid_test_holdout": bool(forbidden_in_generation),
        "candidate_generation_forbidden_inputs_found": forbidden_in_generation,
        "candidate_generation_read_files": [str(path) for path in generation_files],
        "evaluation_only_read_files": [str(path) for path in eval_paths],
        "no_10k": not forbidden_marker_paths,
        "forbidden_marker_paths": forbidden_marker_paths,
        "no_full_clean_copy": source_audit.get("no_full_clean_copy") is True and not (input_dir / "amazon_2023_recall_clean_full").exists(),
        "source_audit_path": str(input_dir / "source_audit.json"),
    }


def _resource_audit(input_dir: Path, output_dir: Path, min_free_bytes: int) -> dict[str, Any]:
    drive_root = _existing_ancestor(output_dir.parent)
    usage = shutil.disk_usage(drive_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if usage.free >= min_free_bytes else "FAIL",
        "drive_path": str(drive_root),
        "disk_total_bytes": usage.total,
        "disk_used_bytes": usage.used,
        "disk_free_bytes": usage.free,
        "disk_free_gib": round(usage.free / (1024**3), 3),
        "min_free_bytes": min_free_bytes,
        "min_free_gib": round(min_free_bytes / (1024**3), 3),
        "p0_p2_manifest_disk_free_bytes_end": read_json(input_dir / "manifest.json").get("disk_free_bytes_end"),
        "resource_summary": "D drive free space is above 50GiB threshold" if usage.free >= min_free_bytes else "D drive free space is below threshold",
    }


def _ranking_isolation_audit(input_dir: Path, pool500_path: Path) -> dict[str, Any]:
    p0_p2_manifest = read_json(input_dir / "manifest.json")
    ranking_isolation = p0_p2_manifest.get("ranking_isolation", {})
    pool500_signature = _file_signature(pool500_path)
    baseline_config_signature = _file_signature(RANKING_BASELINE_CONFIG) if RANKING_BASELINE_CONFIG.is_file() else None
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if ranking_isolation.get("ranking_default_input_modified") is False and ranking_isolation.get("frozen_pool200_ranking_baseline_replaced") is False else "FAIL",
        "pool500_as_ranking_input": ranking_isolation.get("pool500_as_ranking_input"),
        "ranking_default_input_modified": ranking_isolation.get("ranking_default_input_modified"),
        "frozen_pool200_ranking_baseline_replaced": ranking_isolation.get("frozen_pool200_ranking_baseline_replaced"),
        "pool500_candidate_artifact": {
            "path": str(pool500_path),
            "role": "recall_only_audit_candidate_pool_not_ranking_input",
            "signature": pool500_signature,
        },
        "frozen_pool200_ranking_reference": {
            "config_path": str(RANKING_BASELINE_CONFIG),
            "config_available": RANKING_BASELINE_CONFIG.is_file(),
            "config_signature": baseline_config_signature,
        },
        "disabled_outputs": p0_p2_manifest.get("disabled_outputs", {}),
        "decision_reason": "pool500 audit reads P0-P2 recall-only outputs and does not modify or replace frozen pool200 ranking input",
    }


def main() -> None:
    args = parse_args()
    manifest = run_pool500_representative_p3_p4_audit(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        clean_dir=Path(args.clean_dir),
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["required_artifacts"]["manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
