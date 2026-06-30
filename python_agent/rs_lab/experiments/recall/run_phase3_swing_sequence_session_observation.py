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
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
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
from rs_lab.experiments.recall.run_phase2_usercf_bounded_observation import DEFAULT_PHASE1_DIR

SCHEMA_VERSION = "phase3_swing_sequence_session_observation_v1"
DEFAULT_PHASE2_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "usercf_bounded_observation"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "swing_sequence_session_observation"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
EVALUATION_ONLY_FILES = ("canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl")
FORBIDDEN_CANDIDATE_FILES = (*EVALUATION_ONLY_FILES, "user_sequences.valid.jsonl", "user_sequences.test.jsonl", "holdout.jsonl")
ALLOWED_STATES = {"EXECUTED_PASS_OBSERVATION_ONLY", "blocked", "deferred"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded Swing and sequence/session transition observation after Phase 2.")
    parser.add_argument("--phase0-dir", default=str(DEFAULT_PHASE0_DIR))
    parser.add_argument("--phase1-dir", default=str(DEFAULT_PHASE1_DIR))
    parser.add_argument("--phase2-dir", default=str(DEFAULT_PHASE2_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--candidate-pool-size", type=int, default=200)
    parser.add_argument("--seed-window", type=int, default=20)
    parser.add_argument("--per-seed", type=int, default=20)
    parser.add_argument("--per-user", type=int, default=30)
    parser.add_argument("--max-users", type=int, default=1000)
    parser.add_argument("--max-items-per-user", type=int, default=50)
    parser.add_argument("--max-item-users", type=int, default=200)
    parser.add_argument("--max-pairs", type=int, default=200000)
    parser.add_argument("--swing-alpha", type=float, default=1.0)
    parser.add_argument("--session-recency-decay", type=float, default=0.9)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_phase3_swing_sequence_session_observation(
    *,
    phase0_dir: Path = DEFAULT_PHASE0_DIR,
    phase1_dir: Path = DEFAULT_PHASE1_DIR,
    phase2_dir: Path = DEFAULT_PHASE2_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_pool_size: int = 200,
    seed_window: int = 20,
    per_seed: int = 20,
    per_user: int = 30,
    max_users: int = 1000,
    max_items_per_user: int = 50,
    max_item_users: int = 200,
    max_pairs: int = 200000,
    swing_alpha: float = 1.0,
    session_recency_decay: float = 0.9,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    start = perf_counter()
    _validate_caps(max_users, max_items_per_user, max_item_users, max_pairs, seed_window, per_seed, per_user, swing_alpha, session_recency_decay)
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
    phase2_dir = phase2_dir.resolve()
    phase0_manifest = _read_json(phase0_dir / "manifest.json")
    phase1_manifest = _read_json(phase1_dir / "manifest.json")
    phase2_manifest = _read_json(phase2_dir / "manifest.json")
    if phase0_manifest.get("status") != "PASS":
        raise RuntimeError(f"Phase 0 must PASS before Phase 3, got {phase0_manifest.get('status')}")
    if phase1_manifest.get("status") != "EXECUTED_PASS_OBSERVATION_ONLY":
        raise RuntimeError(f"Phase 1 evidence must be complete before Phase 3, got {phase1_manifest.get('status')}")
    if phase2_manifest.get("status") not in {"promotion_candidate", "rejected", "blocked", "deferred"}:
        raise RuntimeError(f"Phase 2 evidence must be complete before Phase 3, got {phase2_manifest.get('status')}")

    phase0_resolved = _read_json(phase0_dir / "resolved_inputs.json")
    clean_dir = Path(phase0_resolved["full_clean_dir"]["path"]).resolve()
    baseline_dir = Path(phase0_resolved["lightweight_representative_baseline"]["path"]).resolve()
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    baseline_path = baseline_dir / "candidates.jsonl"
    phase1_candidates_path = phase1_dir / "candidates.jsonl"
    phase2_candidates_path = phase2_dir / "candidates.jsonl"
    eval_paths = [clean_dir / name for name in EVALUATION_ONLY_FILES]

    baseline_by_user = _load_baseline_candidates(baseline_path)
    representative_users = set(sorted(baseline_by_user)[:max_users])
    sequences_by_user = _load_bounded_sequences(sequence_path, representative_users, max_items_per_user)
    item_users, truncated_hot_items = _build_item_users(sequences_by_user, max_item_users)
    swing_index, swing_sidecar = _build_swing_index(sequences_by_user, item_users, per_seed, max_pairs, swing_alpha)
    session_index, session_sidecar = _build_session_transition_index(sequences_by_user, per_seed, max_pairs)

    swing_by_user: dict[str, list[dict[str, Any]]] = {}
    session_by_user: dict[str, list[dict[str, Any]]] = {}
    method_by_user: dict[str, list[dict[str, Any]]] = {}
    merged_by_user: dict[str, list[dict[str, Any]]] = {}
    latencies: list[float] = []
    for user_id in sorted(baseline_by_user):
        user_start = perf_counter()
        sequence = sequences_by_user.get(user_id, {"recent_positive_item_sequence": [], "recent_item_sequence": []})
        baseline_rows = baseline_by_user[user_id]
        existing_items = {row["item_id"] for row in baseline_rows}
        swing_rows = _swing_rows_for_user(user_id, sequence, swing_index, existing_items, seed_window, per_seed, per_user)
        session_rows = _session_rows_for_user(user_id, sequence, session_index, existing_items, seed_window, per_seed, per_user, session_recency_decay)
        method_rows = _merge_rows(swing_rows, session_rows, per_user * 2)
        swing_by_user[user_id] = swing_rows
        session_by_user[user_id] = session_rows
        method_by_user[user_id] = method_rows
        merged_by_user[user_id] = _merge_rows(baseline_rows, method_rows, candidate_pool_size)
        latencies.append(perf_counter() - user_start)

    positives_by_user = _load_evaluation_positives(eval_paths, set(baseline_by_user))
    baseline_metrics = _candidate_metrics(baseline_by_user, positives_by_user)
    merged_metrics = _candidate_metrics(merged_by_user, positives_by_user)
    swing_metrics = _candidate_metrics(swing_by_user, positives_by_user)
    session_metrics = _candidate_metrics(session_by_user, positives_by_user)
    method_metrics = _candidate_metrics(method_by_user, positives_by_user)
    latency = {"p50_seconds": _percentile(latencies, 0.5), "p95_seconds": _percentile(latencies, 0.95)}
    state = _phase3_state(swing_metrics, session_metrics)
    ablation = {
        "schema_version": SCHEMA_VERSION,
        "candidate_hit_users_delta": merged_metrics["candidate_hit_users"] - baseline_metrics["candidate_hit_users"],
        "recall_at_pool_delta": round(merged_metrics["recall_at_pool"] - baseline_metrics["recall_at_pool"], 6),
        "empty_candidate_rate_delta": round(merged_metrics["empty_candidate_rate"] - baseline_metrics["empty_candidate_rate"], 6),
        "fallback_rate_delta": round(merged_metrics["fallback_rate"] - baseline_metrics["fallback_rate"], 6),
        "overlap_delta": round(merged_metrics["source_overlap_jaccard"] - baseline_metrics["source_overlap_jaccard"], 6),
        "latency_p50_delta": latency["p50_seconds"],
        "latency_p95_delta": latency["p95_seconds"],
        "source_marginal_hit": method_metrics["candidate_hit_users"],
        "swing_marginal_hit": swing_metrics["candidate_hit_users"],
        "session_transition_marginal_hit": session_metrics["candidate_hit_users"],
    }
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "status": state["status"],
        "baseline": baseline_metrics,
        "merged": merged_metrics,
        "swing_bounded": swing_metrics,
        "session_transition_bounded": session_metrics,
        "combined_observation_sources": method_metrics,
        "latency_seconds": latency,
        "evaluation_only": {"read_files": [str(path) for path in eval_paths], "contract": "valid/test are read only after candidate generation for evaluation metrics"},
    }
    session_definition_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "session_source": "recent_item_sequence from train user_sequences only",
        "transition_definition": "adjacent item pairs within each bounded train sequence",
        "positive_sequence_source": "recent_positive_item_sequence from train user_sequences only",
        "candidate_generation_uses_holdout": False,
        "valid_test_usage": "evaluation_only_after_candidate_generation",
        "bounded_user_count": len(sequences_by_user),
        "max_items_per_user": max_items_per_user,
        "seed_window": seed_window,
    }
    transition_sidecar_manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "swing": swing_sidecar,
        "session_transition": session_sidecar,
        "caps": {
            "max_users": max_users,
            "max_items_per_user": max_items_per_user,
            "max_item_users": max_item_users,
            "max_pairs": max_pairs,
            "per_seed": per_seed,
            "per_user": per_user,
        },
        "no_unbounded_global_pair_counter": True,
    }

    output_dir.mkdir(parents=True)
    write_jsonl(output_dir / "candidates.jsonl", _flatten_candidates(merged_by_user))
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "ablation_vs_lightweight_baseline.json", ablation)
    write_json(output_dir / "session_definition_audit.json", session_definition_audit)
    write_json(output_dir / "transition_sidecar_manifest.json", transition_sidecar_manifest)
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only_candidate_generation": True,
        "bounded_user_count": len(sequences_by_user),
        "max_users": max_users,
        "max_items_per_user": max_items_per_user,
        "max_item_users": max_item_users,
        "max_pairs": max_pairs,
        "truncated_hot_items": truncated_hot_items,
        "candidate_generation_read_files": [str(baseline_path), str(sequence_path), str(phase1_candidates_path), str(phase2_candidates_path)],
        "evaluation_only_read_files": [str(path) for path in eval_paths],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "candidate_generation_uses_holdout": False,
        "disabled_outputs": {"pool500": True, "pool1000": True, "ranking_default_input": True},
        "source_signatures": {
            "baseline_candidates": _file_signature(baseline_path),
            "phase1_candidates": _file_signature(phase1_candidates_path),
            "phase2_candidates": _file_signature(phase2_candidates_path),
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
        "phase2_status": phase2_manifest.get("status"),
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - start, 6),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "user_count": len(baseline_by_user),
        "candidate_row_count": sum(len(rows) for rows in merged_by_user.values()),
        "empty_user_count": merged_metrics["empty_candidate_users"],
        "observation_only": True,
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "metrics": str(output_dir / "metrics.json"),
            "ablation_vs_lightweight_baseline": str(output_dir / "ablation_vs_lightweight_baseline.json"),
            "session_definition_audit": str(output_dir / "session_definition_audit.json"),
            "transition_sidecar_manifest": str(output_dir / "transition_sidecar_manifest.json"),
            "candidates": str(output_dir / "candidates.jsonl"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _validate_caps(max_users: int, max_items_per_user: int, max_item_users: int, max_pairs: int, seed_window: int, per_seed: int, per_user: int, swing_alpha: float, session_recency_decay: float) -> None:
    for label, value in {
        "max_users": max_users,
        "max_items_per_user": max_items_per_user,
        "max_item_users": max_item_users,
        "max_pairs": max_pairs,
        "seed_window": seed_window,
        "per_seed": per_seed,
        "per_user": per_user,
    }.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if max_users > 1000:
        raise ValueError("max_users must be <= 1000 for bounded Swing/session observation")
    if max_pairs > 200000:
        raise ValueError("max_pairs must be <= 200000 for bounded Swing/session observation")
    if swing_alpha <= 0:
        raise ValueError("swing_alpha must be positive")
    if not 0 < session_recency_decay <= 1:
        raise ValueError("session_recency_decay must be in (0, 1]")


def _load_bounded_sequences(path: Path, user_ids: set[str], max_items_per_user: int) -> dict[str, dict[str, list[str]]]:
    sequences: dict[str, dict[str, list[str]]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            user_id = str(row.get("user_id", ""))
            if user_id not in user_ids:
                continue
            positive_raw = row.get("recent_strong_positive_item_sequence") or row.get("recent_positive_item_sequence") or []
            recent_raw = row.get("recent_item_sequence") or positive_raw
            positive_items = [str(item) for item in positive_raw if item][-max_items_per_user:]
            recent_items = [str(item) for item in recent_raw if item][-max_items_per_user:]
            sequences[user_id] = {"recent_positive_item_sequence": positive_items, "recent_item_sequence": recent_items}
            if len(sequences) == len(user_ids):
                break
    return sequences


def _build_item_users(sequences_by_user: dict[str, dict[str, list[str]]], max_item_users: int) -> tuple[dict[str, set[str]], list[str]]:
    item_users: dict[str, set[str]] = defaultdict(set)
    truncated: list[str] = []
    for user_id, sequence in sequences_by_user.items():
        for item_id in dict.fromkeys(sequence["recent_positive_item_sequence"]):
            users = item_users[item_id]
            if len(users) < max_item_users:
                users.add(user_id)
            elif item_id not in truncated:
                truncated.append(item_id)
    return dict(item_users), sorted(truncated)


def _build_swing_index(
    sequences_by_user: dict[str, dict[str, list[str]]],
    item_users: dict[str, set[str]],
    per_seed: int,
    max_pairs: int,
    alpha: float,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    pair_updates = 0
    truncated = False
    user_item_sets = {user_id: set(sequence["recent_positive_item_sequence"]) for user_id, sequence in sequences_by_user.items()}
    for left_item in sorted(item_users):
        related: Counter[str] = Counter()
        for user_id in sorted(item_users[left_item]):
            for right_item in user_item_sets.get(user_id, set()):
                if right_item != left_item:
                    related[right_item] += 1
                    pair_updates += 1
                    if pair_updates >= max_pairs:
                        truncated = True
                        break
            if truncated:
                break
        for right_item, co_count in related.items():
            common_users = item_users[left_item] & item_users.get(right_item, set())
            denom = alpha + sum(1.0 / max(1, len(user_item_sets[user_id])) for user_id in common_users)
            score = float(co_count) / denom if denom else 0.0
            if score:
                pair_scores[left_item][right_item] += score
        if truncated:
            break
    index = {
        seed: [
            {"item_id": item_id, "score": round(float(score), 6), "rank": rank, "seed_item_id": seed}
            for rank, (item_id, score) in enumerate(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:per_seed], start=1)
        ]
        for seed, scores in pair_scores.items()
    }
    index = {seed: rows for seed, rows in index.items() if rows}
    return index, {"seed_count": len(index), "pair_update_count": pair_updates, "truncated_by_max_pairs": truncated, "source": "bounded_train_positive_sequences"}


def _build_session_transition_index(sequences_by_user: dict[str, dict[str, list[str]]], per_seed: int, max_pairs: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    pair_updates = 0
    truncated = False
    for sequence in sequences_by_user.values():
        items = sequence["recent_item_sequence"]
        for left, right in zip(items, items[1:]):
            if left == right:
                continue
            pair_scores[left][right] += 1
            pair_updates += 1
            if pair_updates >= max_pairs:
                truncated = True
                break
        if truncated:
            break
    index = {
        seed: [
            {"item_id": item_id, "score": float(score), "rank": rank, "seed_item_id": seed}
            for rank, (item_id, score) in enumerate(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:per_seed], start=1)
        ]
        for seed, scores in pair_scores.items()
    }
    index = {seed: rows for seed, rows in index.items() if rows}
    return index, {"seed_count": len(index), "pair_update_count": pair_updates, "truncated_by_max_pairs": truncated, "source": "bounded_train_recent_sequence_adjacent_pairs"}


def _swing_rows_for_user(
    user_id: str,
    sequence: dict[str, list[str]],
    index: dict[str, list[dict[str, Any]]],
    existing_items: set[str],
    seed_window: int,
    per_seed: int,
    per_user: int,
) -> list[dict[str, Any]]:
    seen_items = set(sequence.get("recent_item_sequence", []))
    seeds = list(dict.fromkeys(reversed(sequence.get("recent_positive_item_sequence", [])[-seed_window:])))
    by_item: dict[str, dict[str, Any]] = {}
    for seed_rank, seed in enumerate(seeds):
        for candidate in index.get(seed, [])[:per_seed]:
            item_id = candidate["item_id"]
            if item_id in seen_items or item_id in existing_items:
                continue
            score = float(candidate["score"])
            current = by_item.get(item_id)
            if current is None or score > float(current["score"]):
                by_item[item_id] = {**candidate, "score": score, "seed_rank": seed_rank}
    rows = sorted(by_item.values(), key=lambda item: (-float(item["score"]), str(item["item_id"])))[:per_user]
    return [
        _candidate_row(
            user_id,
            str(row["item_id"]),
            ["swing_bounded"],
            {"swing_bounded": round(float(row["score"]), 6)},
            "",
            {"reason": "bounded_train_swing_item_pair", "seed_item_id": row["seed_item_id"], "source_rank": row["rank"], "seed_rank": row["seed_rank"]},
        )
        for row in rows
    ]


def _session_rows_for_user(
    user_id: str,
    sequence: dict[str, list[str]],
    index: dict[str, list[dict[str, Any]]],
    existing_items: set[str],
    seed_window: int,
    per_seed: int,
    per_user: int,
    recency_decay: float,
) -> list[dict[str, Any]]:
    seen_items = set(sequence.get("recent_item_sequence", []))
    seeds = list(dict.fromkeys(reversed(sequence.get("recent_item_sequence", [])[-seed_window:])))
    by_item: dict[str, dict[str, Any]] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in index.get(seed, [])[:per_seed]:
            item_id = candidate["item_id"]
            if item_id in seen_items or item_id in existing_items:
                continue
            score = round(float(candidate["score"]) * decay, 6)
            current = by_item.get(item_id)
            if current is None or score > float(current["score"]):
                by_item[item_id] = {**candidate, "score": score, "seed_rank": seed_rank}
    rows = sorted(by_item.values(), key=lambda item: (-float(item["score"]), str(item["item_id"])))[:per_user]
    return [
        _candidate_row(
            user_id,
            str(row["item_id"]),
            ["session_transition_bounded"],
            {"session_transition_bounded": round(float(row["score"]), 6)},
            "",
            {"reason": "bounded_train_adjacent_transition", "seed_item_id": row["seed_item_id"], "source_rank": row["rank"], "seed_rank": row["seed_rank"]},
        )
        for row in rows
    ]


def _phase3_state(swing_metrics: dict[str, Any], session_metrics: dict[str, Any]) -> dict[str, str | None]:
    if swing_metrics["candidate_row_count"] == 0 and session_metrics["candidate_row_count"] == 0:
        return {"status": "blocked", "failure_reason": "no_swing_or_session_candidates_generated", "downgrade_action": "keep_baseline_without_phase3_sources"}
    return {"status": "EXECUTED_PASS_OBSERVATION_ONLY", "failure_reason": None, "downgrade_action": "record_observation_do_not_promote"}


def main() -> None:
    args = parse_args()
    manifest = run_phase3_swing_sequence_session_observation(
        phase0_dir=Path(args.phase0_dir),
        phase1_dir=Path(args.phase1_dir),
        phase2_dir=Path(args.phase2_dir),
        output_dir=Path(args.output_dir),
        candidate_pool_size=args.candidate_pool_size,
        seed_window=args.seed_window,
        per_seed=args.per_seed,
        per_user=args.per_user,
        max_users=args.max_users,
        max_items_per_user=args.max_items_per_user,
        max_item_users=args.max_item_users,
        max_pairs=args.max_pairs,
        swing_alpha=args.swing_alpha,
        session_recency_decay=args.session_recency_decay,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    if manifest["status"] not in ALLOWED_STATES:
        raise RuntimeError(f"Unexpected Phase 3 state: {manifest['status']}")
    print(f"Phase 3 Swing/session bounded observation status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
