from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json, write_jsonl
from scripts.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    DEFAULT_PHASE0_DIR,
    _candidate_metrics,
    _candidate_row,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _flatten_candidates,
    _load_baseline_candidates,
    _load_evaluation_positives,
    _merge_rows,
    _percentile,
    _read_json,
)

SCHEMA_VERSION = "phase2_usercf_bounded_observation_v1"
DEFAULT_PHASE1_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "itemcf_covisit_representative_merge_eval"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "usercf_bounded_observation"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
EVALUATION_ONLY_FILES = ("canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl")
FORBIDDEN_CANDIDATE_FILES = (*EVALUATION_ONLY_FILES, "user_sequences.valid.jsonl", "user_sequences.test.jsonl", "holdout.jsonl")
ALLOWED_STATES = {"promotion_candidate", "rejected", "blocked", "deferred"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded UserCF observation after Phase 1.")
    parser.add_argument("--phase0-dir", default=str(DEFAULT_PHASE0_DIR))
    parser.add_argument("--phase1-dir", default=str(DEFAULT_PHASE1_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--candidate-pool-size", type=int, default=200)
    parser.add_argument("--usercf-per-user", type=int, default=30)
    parser.add_argument("--seed-window", type=int, default=20)
    parser.add_argument("--similar-users", type=int, default=30)
    parser.add_argument("--max-users", type=int, default=1000)
    parser.add_argument("--max-items-per-user", type=int, default=50)
    parser.add_argument("--max-item-users", type=int, default=200)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_phase2_usercf_bounded_observation(
    *,
    phase0_dir: Path = DEFAULT_PHASE0_DIR,
    phase1_dir: Path = DEFAULT_PHASE1_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_pool_size: int = 200,
    usercf_per_user: int = 30,
    seed_window: int = 20,
    similar_users: int = 30,
    max_users: int = 1000,
    max_items_per_user: int = 50,
    max_item_users: int = 200,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    start = perf_counter()
    _validate_caps(max_users, max_items_per_user, max_item_users, similar_users, usercf_per_user)
    if enforce_venv:
        _enforce_project_venv()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if disk_free_start < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below threshold: {disk_free_start} < {min_free_bytes}")

    phase0_dir = phase0_dir.resolve()
    phase1_dir = phase1_dir.resolve()
    phase0_manifest = _read_json(phase0_dir / "manifest.json")
    phase1_manifest = _read_json(phase1_dir / "manifest.json")
    if phase0_manifest.get("status") != "PASS":
        raise RuntimeError(f"Phase 0 must PASS before Phase 2, got {phase0_manifest.get('status')}")
    if phase1_manifest.get("status") != "EXECUTED_PASS_OBSERVATION_ONLY":
        raise RuntimeError(f"Phase 1 evidence must be complete before Phase 2, got {phase1_manifest.get('status')}")

    phase0_resolved = _read_json(phase0_dir / "resolved_inputs.json")
    clean_dir = Path(phase0_resolved["full_clean_dir"]["path"]).resolve()
    baseline_dir = Path(phase0_resolved["lightweight_representative_baseline"]["path"]).resolve()
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    baseline_path = baseline_dir / "candidates.jsonl"
    phase1_candidates_path = phase1_dir / "candidates.jsonl"
    eval_paths = [clean_dir / name for name in EVALUATION_ONLY_FILES]

    baseline_by_user = _load_baseline_candidates(baseline_path)
    representative_users = set(sorted(baseline_by_user)[:max_users])
    sequences_by_user = _load_bounded_sequences(sequence_path, representative_users, seed_window, max_items_per_user)
    item_users, truncated_items = _build_item_users(sequences_by_user, max_item_users)
    phase1_by_user = _load_baseline_candidates(phase1_candidates_path)

    usercf_by_user: dict[str, list[dict[str, Any]]] = {}
    merged_by_user: dict[str, list[dict[str, Any]]] = {}
    latencies: list[float] = []
    for user_id in sorted(baseline_by_user):
        user_start = perf_counter()
        baseline_rows = baseline_by_user[user_id]
        seen_items = set(sequences_by_user.get(user_id, []))
        existing_items = {row["item_id"] for row in baseline_rows}
        rows = _usercf_rows_for_user(
            user_id=user_id,
            sequences_by_user=sequences_by_user,
            item_users=item_users,
            seen_items=seen_items,
            existing_items=existing_items,
            similar_users=similar_users,
            per_user=usercf_per_user,
        )
        usercf_by_user[user_id] = rows
        merged_by_user[user_id] = _merge_rows(baseline_rows, rows, candidate_pool_size)
        latencies.append(perf_counter() - user_start)

    positives_by_user = _load_evaluation_positives(eval_paths, set(baseline_by_user))
    baseline_metrics = _candidate_metrics(baseline_by_user, positives_by_user)
    merged_metrics = _candidate_metrics(merged_by_user, positives_by_user)
    usercf_metrics = _candidate_metrics(usercf_by_user, positives_by_user)
    latency = {"p50_seconds": _percentile(latencies, 0.5), "p95_seconds": _percentile(latencies, 0.95)}
    state = _usercf_state(baseline_metrics, merged_metrics, usercf_metrics)
    ablation = {
        "schema_version": SCHEMA_VERSION,
        "candidate_hit_users_delta": merged_metrics["candidate_hit_users"] - baseline_metrics["candidate_hit_users"],
        "recall_at_pool_delta": round(merged_metrics["recall_at_pool"] - baseline_metrics["recall_at_pool"], 6),
        "empty_candidate_rate_delta": round(merged_metrics["empty_candidate_rate"] - baseline_metrics["empty_candidate_rate"], 6),
        "fallback_rate_delta": round(merged_metrics["fallback_rate"] - baseline_metrics["fallback_rate"], 6),
        "overlap_delta": round(merged_metrics["source_overlap_jaccard"] - baseline_metrics["source_overlap_jaccard"], 6),
        "latency_p50_delta": latency["p50_seconds"],
        "latency_p95_delta": latency["p95_seconds"],
        "source_marginal_hit": usercf_metrics["candidate_hit_users"],
    }
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "status": state["status"],
        "baseline": baseline_metrics,
        "merged": merged_metrics,
        "usercf_bounded": usercf_metrics,
        "latency_seconds": latency,
        "evaluation_only": {"read_files": [str(path) for path in eval_paths], "contract": "valid/test are read only after candidate generation for evaluation metrics"},
    }
    source_overlap_with_itemcf = _source_overlap_with_itemcf(phase1_by_user, usercf_by_user)

    output_dir.mkdir(parents=True)
    write_jsonl(output_dir / "candidates.jsonl", _flatten_candidates(merged_by_user))
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "ablation_vs_lightweight_baseline.json", ablation)
    write_json(output_dir / "source_overlap_with_itemcf.json", source_overlap_with_itemcf)
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only_candidate_generation": True,
        "no_dense_user_user_matrix": True,
        "bounded_user_count": len(sequences_by_user),
        "max_users": max_users,
        "max_items_per_user": max_items_per_user,
        "max_item_users": max_item_users,
        "similar_users": similar_users,
        "truncated_hot_items": truncated_items,
        "candidate_generation_read_files": [str(baseline_path), str(sequence_path), str(phase1_candidates_path)],
        "evaluation_only_read_files": [str(path) for path in eval_paths],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "candidate_generation_uses_holdout": False,
        "disabled_outputs": {"dense_user_user_matrix": True, "pool500": True, "pool1000": True, "ranking_default_input": True},
        "source_signatures": {
            "baseline_candidates": _file_signature(baseline_path),
            "phase1_candidates": _file_signature(phase1_candidates_path),
            "train_sequences": _file_signature(sequence_path),
        },
    }
    write_json(output_dir / "source_audit.json", source_audit)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": state["status"],
        "failure_reason": state["failure_reason"],
        "downgrade_action": state["downgrade_action"],
        "phase0_status": phase0_manifest.get("status"),
        "phase1_status": phase1_manifest.get("status"),
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - start, 6),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "user_count": len(baseline_by_user),
        "candidate_row_count": sum(len(rows) for rows in merged_by_user.values()),
        "empty_user_count": merged_metrics["empty_candidate_users"],
        "no_dense_user_user_matrix": True,
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "metrics": str(output_dir / "metrics.json"),
            "ablation_vs_lightweight_baseline": str(output_dir / "ablation_vs_lightweight_baseline.json"),
            "source_overlap_with_itemcf": str(output_dir / "source_overlap_with_itemcf.json"),
            "candidates": str(output_dir / "candidates.jsonl"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _validate_caps(max_users: int, max_items_per_user: int, max_item_users: int, similar_users: int, usercf_per_user: int) -> None:
    for label, value in {
        "max_users": max_users,
        "max_items_per_user": max_items_per_user,
        "max_item_users": max_item_users,
        "similar_users": similar_users,
        "usercf_per_user": usercf_per_user,
    }.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if max_users > 1000:
        raise ValueError("max_users must be <= 1000 for bounded UserCF observation")


def _load_bounded_sequences(path: Path, user_ids: set[str], seed_window: int, max_items_per_user: int) -> dict[str, list[str]]:
    sequences: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            user_id = str(row.get("user_id", ""))
            if user_id not in user_ids:
                continue
            raw = row.get("recent_strong_positive_item_sequence") or row.get("recent_positive_item_sequence") or row.get("recent_item_sequence") or []
            deduped = list(dict.fromkeys(str(item) for item in raw if item))[-max_items_per_user:]
            sequences[user_id] = deduped[-seed_window:]
            if len(sequences) == len(user_ids):
                break
    return sequences


def _build_item_users(sequences_by_user: dict[str, list[str]], max_item_users: int) -> tuple[dict[str, set[str]], list[str]]:
    item_users: dict[str, set[str]] = defaultdict(set)
    truncated: list[str] = []
    for user_id, items in sequences_by_user.items():
        for item_id in items:
            users = item_users[item_id]
            if len(users) < max_item_users:
                users.add(user_id)
            elif item_id not in truncated:
                truncated.append(item_id)
    return dict(item_users), sorted(truncated)


def _usercf_rows_for_user(
    *,
    user_id: str,
    sequences_by_user: dict[str, list[str]],
    item_users: dict[str, set[str]],
    seen_items: set[str],
    existing_items: set[str],
    similar_users: int,
    per_user: int,
) -> list[dict[str, Any]]:
    seeds = sequences_by_user.get(user_id, [])
    if not seeds:
        return []
    overlap_scores: Counter[str] = Counter()
    seed_set = set(seeds)
    for item_id in seed_set:
        for other_user in item_users.get(item_id, set()):
            if other_user != user_id:
                overlap_scores[other_user] += 1
    top_users = [other for other, _ in overlap_scores.most_common(similar_users)]
    candidate_scores: Counter[str] = Counter()
    source_users: dict[str, set[str]] = defaultdict(set)
    for other_user in top_users:
        user_score = overlap_scores[other_user]
        for item_id in sequences_by_user.get(other_user, []):
            if item_id in seen_items or item_id in existing_items:
                continue
            candidate_scores[item_id] += user_score
            source_users[item_id].add(other_user)
    ranked = sorted(candidate_scores, key=lambda item: (-candidate_scores[item], item))[:per_user]
    return [
        _candidate_row(
            user_id,
            item_id,
            ["usercf_bounded"],
            {"usercf_bounded": round(float(candidate_scores[item_id]), 6)},
            "",
            {"similar_user_count": len(source_users[item_id]), "reason": "bounded_train_user_overlap"},
        )
        for item_id in ranked
    ]


def _source_overlap_with_itemcf(phase1_by_user: dict[str, list[dict[str, Any]]], usercf_by_user: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    itemcf_items: set[str] = set()
    usercf_items: set[str] = set()
    overlapping_users = 0
    for user_id, rows in usercf_by_user.items():
        user_usercf = {row["item_id"] for row in rows}
        user_itemcf = {
            row["item_id"]
            for row in phase1_by_user.get(user_id, [])
            if "bounded_itemcf_covisit" in set(row.get("sources", []))
        }
        if user_usercf & user_itemcf:
            overlapping_users += 1
        itemcf_items.update(user_itemcf)
        usercf_items.update(user_usercf)
    union = itemcf_items | usercf_items
    return {
        "schema_version": SCHEMA_VERSION,
        "itemcf_item_count": len(itemcf_items),
        "usercf_item_count": len(usercf_items),
        "intersection_item_count": len(itemcf_items & usercf_items),
        "jaccard": round(len(itemcf_items & usercf_items) / len(union), 6) if union else 0.0,
        "overlapping_users": overlapping_users,
    }


def _usercf_state(baseline_metrics: dict[str, Any], merged_metrics: dict[str, Any], usercf_metrics: dict[str, Any]) -> dict[str, str | None]:
    if usercf_metrics["candidate_row_count"] == 0:
        return {"status": "blocked", "failure_reason": "no_usercf_candidates_generated", "downgrade_action": "keep_baseline_without_usercf"}
    if merged_metrics["candidate_hit_users"] > baseline_metrics["candidate_hit_users"] or merged_metrics["recall_at_pool"] > baseline_metrics["recall_at_pool"]:
        return {"status": "promotion_candidate", "failure_reason": None, "downgrade_action": None}
    return {"status": "rejected", "failure_reason": "no_positive_observation_lift", "downgrade_action": "record_observation_do_not_promote"}


def main() -> None:
    args = parse_args()
    manifest = run_phase2_usercf_bounded_observation(
        phase0_dir=Path(args.phase0_dir),
        phase1_dir=Path(args.phase1_dir),
        output_dir=Path(args.output_dir),
        candidate_pool_size=args.candidate_pool_size,
        usercf_per_user=args.usercf_per_user,
        seed_window=args.seed_window,
        similar_users=args.similar_users,
        max_users=args.max_users,
        max_items_per_user=args.max_items_per_user,
        max_item_users=args.max_item_users,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    if manifest["status"] not in ALLOWED_STATES:
        raise RuntimeError(f"Unexpected UserCF state: {manifest['status']}")
    print(f"Phase 2 UserCF bounded observation status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
