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

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json, write_jsonl
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    _candidate_row,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _flatten_candidates,
    _load_baseline_candidates,
    _merge_rows,
    _percentile,
)
from rs_lab.experiments.recall.run_phase3_swing_sequence_session_observation import (
    _build_item_users,
    _build_session_transition_index,
    _build_swing_index,
)

SCHEMA_VERSION = "pool500_sequence_session_custom_index_v1"
DEFAULT_CUSTOM_INDEX_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative" / "custom_index"
DEFAULT_SOURCE_POOL500_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "contract_precheck_or_p0_p2"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative" / "sequence_session_methods"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_PATH_PARTS = ("amazon_2023_recall_clean_10000", "amazon_2023_recall_views_10000")
FORBIDDEN_CANDIDATE_FILES = (
    "canonical_interactions.valid.jsonl",
    "canonical_interactions.test.jsonl",
    "user_sequences.valid.jsonl",
    "user_sequences.test.jsonl",
    "holdout.jsonl",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run bounded Swing/session observations on representative pool500 custom index.")
    parser.add_argument("--custom-index-dir", default=str(DEFAULT_CUSTOM_INDEX_DIR))
    parser.add_argument("--source-pool500-dir", default=str(DEFAULT_SOURCE_POOL500_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--candidate-pool-size", type=int, default=500)
    parser.add_argument("--seed-window", type=int, default=20)
    parser.add_argument("--per-seed", type=int, default=20)
    parser.add_argument("--per-user", type=int, default=30)
    parser.add_argument("--max-users", type=int, default=500)
    parser.add_argument("--max-items-per-user", type=int, default=50)
    parser.add_argument("--max-item-users", type=int, default=200)
    parser.add_argument("--max-pairs", type=int, default=200000)
    parser.add_argument("--swing-alpha", type=float, default=1.0)
    parser.add_argument("--session-recency-decay", type=float, default=0.9)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def run_pool500_sequence_session_custom_index(
    *,
    custom_index_dir: Path = DEFAULT_CUSTOM_INDEX_DIR,
    source_pool500_dir: Path = DEFAULT_SOURCE_POOL500_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_pool_size: int = 500,
    seed_window: int = 20,
    per_seed: int = 20,
    per_user: int = 30,
    max_users: int = 500,
    max_items_per_user: int = 50,
    max_item_users: int = 200,
    max_pairs: int = 200000,
    swing_alpha: float = 1.0,
    session_recency_decay: float = 0.9,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    started = perf_counter()
    _validate_caps(max_users, max_items_per_user, max_item_users, max_pairs, seed_window, per_seed, per_user, swing_alpha, session_recency_decay)
    if enforce_venv:
        _enforce_project_venv()

    custom_index_dir = custom_index_dir.resolve()
    source_pool500_dir = source_pool500_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck(custom_index_dir, source_pool500_dir, output_dir, min_free_bytes, overwrite)
    if output_dir.exists() and overwrite:
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free

    custom_manifest = _read_json(custom_index_dir / "manifest.json")
    source_manifest = _read_json(source_pool500_dir / "pool500_recall_only" / "manifest.json")
    baseline_path = source_pool500_dir / "pool500_recall_only" / "candidates.jsonl"
    sequence_path = custom_index_dir / "indexed_train_sequences.jsonl"
    baseline_by_user = _load_baseline_candidates(baseline_path)
    user_ids = sorted(baseline_by_user)[:max_users]
    sequences_by_user = _load_custom_sequences(sequence_path, set(user_ids), max_items_per_user)

    item_users, truncated_hot_items = _build_item_users(sequences_by_user, max_item_users)
    swing_index, swing_sidecar = _build_swing_index(sequences_by_user, item_users, per_seed, max_pairs, swing_alpha)
    session_index, session_sidecar = _build_session_transition_index(sequences_by_user, per_seed, max_pairs)

    swing_by_user: dict[str, list[dict[str, Any]]] = {}
    session_by_user: dict[str, list[dict[str, Any]]] = {}
    method_by_user: dict[str, list[dict[str, Any]]] = {}
    merged_by_user: dict[str, list[dict[str, Any]]] = {}
    latencies: list[float] = []
    for user_id in user_ids:
        user_started = perf_counter()
        sequence = sequences_by_user.get(user_id, {"recent_positive_item_sequence": [], "recent_item_sequence": []})
        baseline_rows = baseline_by_user.get(user_id, [])
        existing_items = {row["item_id"] for row in baseline_rows}
        swing_rows = _rows_for_user(
            user_id=user_id,
            sequence=sequence,
            index=swing_index,
            existing_items=existing_items,
            seed_key="recent_positive_item_sequence",
            source="swing_recall",
            score_key="swing_recall",
            reason="bounded_train_swing_item_pair",
            seed_window=seed_window,
            per_seed=per_seed,
            per_user=per_user,
            recency_decay=1.0,
        )
        session_rows = _rows_for_user(
            user_id=user_id,
            sequence=sequence,
            index=session_index,
            existing_items=existing_items,
            seed_key="recent_item_sequence",
            source="session_transition_recall",
            score_key="session_transition_recall",
            reason="bounded_train_adjacent_transition",
            seed_window=seed_window,
            per_seed=per_seed,
            per_user=per_user,
            recency_decay=session_recency_decay,
        )
        method_rows = _merge_rows(swing_rows, session_rows, per_user * 2)
        swing_by_user[user_id] = swing_rows
        session_by_user[user_id] = session_rows
        method_by_user[user_id] = method_rows
        merged_by_user[user_id] = _merge_rows(baseline_rows, method_rows, candidate_pool_size)
        latencies.append(perf_counter() - user_started)

    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only_candidate_generation": True,
        "candidate_generation_uses_holdout": False,
        "candidate_generation_read_files": [str(sequence_path), str(baseline_path)],
        "evaluation_only_read_files": [],
        "forbidden_candidate_generation_inputs": [str(path) for path in _forbidden_paths(custom_index_dir, source_pool500_dir)],
        "no_10k_source": True,
        "no_full_clean_copy": True,
        "ranking_isolation": {
            "ranking_default_input_modified": False,
            "pool500_as_ranking_input": False,
            "pool1000_generated": False,
        },
        "disabled_outputs": {
            "pool1000": True,
            "model_training": True,
            "two_tower_training": True,
            "graph_training": True,
            "mf_training": True,
            "ranking": True,
        },
        "source_signatures": {
            "custom_index_manifest": _file_signature(custom_index_dir / "manifest.json"),
            "indexed_train_sequences": _file_signature(sequence_path),
            "source_pool500_manifest": _file_signature(source_pool500_dir / "pool500_recall_only" / "manifest.json"),
            "source_pool500_candidates": _file_signature(baseline_path),
        },
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "min_free_bytes": min_free_bytes,
        "bounded_user_count": len(sequences_by_user),
        "max_users": max_users,
        "max_items_per_user": max_items_per_user,
        "max_item_users": max_item_users,
        "max_pairs": max_pairs,
        "truncated_hot_items": truncated_hot_items,
        "no_unbounded_global_pair_counter": True,
        "no_unbounded_global_transition_map": True,
        "swing": swing_sidecar,
        "session_transition": session_sidecar,
    }
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "status": _status(swing_by_user, session_by_user),
        "observation_only": True,
        "baseline": _observation_metrics(baseline_by_user),
        "swing_recall": _observation_metrics(swing_by_user),
        "session_transition_recall": _observation_metrics(session_by_user),
        "combined_sequence_session": _observation_metrics(method_by_user),
        "merged_pool500": _observation_metrics(merged_by_user),
        "contribution": _contribution_metrics(baseline_by_user, swing_by_user, session_by_user, method_by_user, merged_by_user),
        "latency_seconds": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "evaluation_only": {"read_files": [], "contract": "valid/test/holdout were not read for this recall-only observation"},
    }
    transition_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "swing_definition": "bounded co-occurrence over representative users' train positive sequences",
        "transition_definition": "adjacent item pairs within each bounded train sequence",
        "session_source": "indexed_train_sequences.jsonl generated from train user_sequences only",
        "candidate_generation_uses_holdout": False,
        "valid_test_usage": "not_read",
        "caps": {
            "max_users": max_users,
            "max_items_per_user": max_items_per_user,
            "max_item_users": max_item_users,
            "max_pairs": max_pairs,
            "seed_window": seed_window,
            "per_seed": per_seed,
            "per_user": per_user,
        },
        "no_unbounded_global_pair_counter": True,
        "no_unbounded_global_transition_map": True,
    }

    write_jsonl(output_dir / "candidates.jsonl", _flatten_candidates(merged_by_user))
    write_jsonl(output_dir / "method_candidates.jsonl", _flatten_candidates(method_by_user))
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)
    write_json(output_dir / "transition_sidecar_manifest.json", transition_audit)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": metrics["status"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "pool500_all_methods_representative_sequence_session_recall_only",
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "custom_index_status": custom_manifest.get("status"),
        "source_pool500_status": source_manifest.get("status", source_manifest.get("summary", {}).get("schema_version")),
        "representative_user_count": len(user_ids),
        "bounded_sequence_user_count": len(sequences_by_user),
        "candidate_row_count": sum(len(rows) for rows in merged_by_user.values()),
        "method_candidate_row_count": sum(len(rows) for rows in method_by_user.values()),
        "train_only_candidate_generation": True,
        "candidate_generation_uses_holdout": False,
        "observation_only": True,
        "disabled_outputs": source_audit["disabled_outputs"],
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "metrics": str(output_dir / "metrics.json"),
            "transition_sidecar_manifest": str(output_dir / "transition_sidecar_manifest.json"),
            "candidates": str(output_dir / "candidates.jsonl"),
            "method_candidates": str(output_dir / "method_candidates.jsonl"),
        },
        "artifact_signatures": {
            "candidates": _file_signature(output_dir / "candidates.jsonl"),
            "method_candidates": _file_signature(output_dir / "method_candidates.jsonl"),
            "metrics": _file_signature(output_dir / "metrics.json"),
            "source_audit": _file_signature(output_dir / "source_audit.json"),
            "resource_audit": _file_signature(output_dir / "resource_audit.json"),
            "transition_sidecar_manifest": _file_signature(output_dir / "transition_sidecar_manifest.json"),
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
    if max_users > 500:
        raise ValueError("max_users must be <= 500 for representative pool500 observation")
    if max_pairs > 200000:
        raise ValueError("max_pairs must be <= 200000 for bounded Swing/session observation")
    if swing_alpha <= 0:
        raise ValueError("swing_alpha must be positive")
    if not 0 < session_recency_decay <= 1:
        raise ValueError("session_recency_decay must be in (0, 1]")


def _precheck(custom_index_dir: Path, source_pool500_dir: Path, output_dir: Path, min_free_bytes: int, overwrite: bool) -> None:
    for path in (custom_index_dir, source_pool500_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden 10k path for pool500 sequence/session observation: {path}")
    required = [
        custom_index_dir / "manifest.json",
        custom_index_dir / "indexed_train_sequences.jsonl",
        source_pool500_dir / "pool500_recall_only" / "manifest.json",
        source_pool500_dir / "pool500_recall_only" / "candidates.jsonl",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input files: " + ", ".join(missing))
    if output_dir.exists() and not overwrite:
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _load_custom_sequences(path: Path, user_ids: set[str], max_items_per_user: int) -> dict[str, dict[str, list[str]]]:
    sequences: dict[str, dict[str, list[str]]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            user_id = str(row.get("user_id", ""))
            if user_id not in user_ids:
                continue
            positive_raw = row.get("strong_positive_item_ids") or row.get("positive_item_ids") or []
            recent_raw = row.get("item_ids") or positive_raw
            sequences[user_id] = {
                "recent_positive_item_sequence": [str(item) for item in positive_raw if item][-max_items_per_user:],
                "recent_item_sequence": [str(item) for item in recent_raw if item][-max_items_per_user:],
            }
            if len(sequences) == len(user_ids):
                break
    return sequences


def _rows_for_user(
    *,
    user_id: str,
    sequence: dict[str, list[str]],
    index: dict[str, list[dict[str, Any]]],
    existing_items: set[str],
    seed_key: str,
    source: str,
    score_key: str,
    reason: str,
    seed_window: int,
    per_seed: int,
    per_user: int,
    recency_decay: float,
) -> list[dict[str, Any]]:
    seen_items = set(sequence.get("recent_item_sequence", []))
    seeds = list(dict.fromkeys(reversed(sequence.get(seed_key, [])[-seed_window:])))
    by_item: dict[str, dict[str, Any]] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in index.get(seed, [])[:per_seed]:
            item_id = str(candidate.get("item_id", ""))
            if not item_id or item_id in seen_items or item_id in existing_items:
                continue
            score = round(float(candidate.get("score", 0.0) or 0.0) * decay, 6)
            current = by_item.get(item_id)
            if current is None or score > float(current["score"]):
                by_item[item_id] = {**candidate, "item_id": item_id, "score": score, "seed_rank": seed_rank}
    rows = sorted(by_item.values(), key=lambda item: (-float(item["score"]), str(item["item_id"])))[:per_user]
    return [
        _candidate_row(
            user_id,
            str(row["item_id"]),
            [source],
            {score_key: round(float(row["score"]), 6)},
            "",
            {"reason": reason, "seed_item_id": row.get("seed_item_id"), "source_rank": row.get("rank"), "seed_rank": row.get("seed_rank")},
        )
        for row in rows
    ]


def _observation_metrics(candidates_by_user: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    users = sorted(candidates_by_user)
    counts = [len(candidates_by_user.get(user, [])) for user in users]
    source_rows: Counter[str] = Counter()
    source_users: dict[str, set[str]] = defaultdict(set)
    source_items: dict[str, set[str]] = defaultdict(set)
    source_pairs: Counter[str] = Counter()
    for user, rows in candidates_by_user.items():
        for row in rows:
            sources = sorted(set(row.get("sources", [])))
            source_rows.update(sources)
            for source in sources:
                source_users[source].add(user)
                source_items[source].add(row["item_id"])
            for left_index, left in enumerate(sources):
                for right in sources[left_index + 1 :]:
                    source_pairs[f"{left}+{right}"] += 1
    return {
        "user_count": len(users),
        "candidate_row_count": sum(counts),
        "empty_candidate_users": sum(1 for count in counts if count == 0),
        "empty_candidate_rate": round(sum(1 for count in counts if count == 0) / len(users), 6) if users else 0.0,
        "candidate_count_distribution": _distribution(counts),
        "source_candidate_rows": dict(sorted(source_rows.items())),
        "source_user_coverage": dict(sorted((source, len(values)) for source, values in source_users.items())),
        "source_item_coverage": dict(sorted((source, len(values)) for source, values in source_items.items())),
        "source_pair_overlap": dict(sorted(source_pairs.items())),
    }


def _contribution_metrics(
    baseline_by_user: dict[str, list[dict[str, Any]]],
    swing_by_user: dict[str, list[dict[str, Any]]],
    session_by_user: dict[str, list[dict[str, Any]]],
    method_by_user: dict[str, list[dict[str, Any]]],
    merged_by_user: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    baseline_items_by_user = {user: {row["item_id"] for row in rows} for user, rows in baseline_by_user.items()}
    merged_items_by_user = {user: {row["item_id"] for row in rows} for user, rows in merged_by_user.items()}
    return {
        "swing_incremental_candidate_rows": _incremental_count(swing_by_user, baseline_items_by_user),
        "session_transition_incremental_candidate_rows": _incremental_count(session_by_user, baseline_items_by_user),
        "combined_incremental_candidate_rows": _incremental_count(method_by_user, baseline_items_by_user),
        "combined_retained_in_merged_rows": sum(
            1
            for user, rows in method_by_user.items()
            for row in rows
            if row["item_id"] in merged_items_by_user.get(user, set())
        ),
        "users_with_swing_candidates": sum(1 for rows in swing_by_user.values() if rows),
        "users_with_session_transition_candidates": sum(1 for rows in session_by_user.values() if rows),
        "users_with_any_sequence_session_candidates": sum(1 for rows in method_by_user.values() if rows),
    }


def _incremental_count(candidates_by_user: dict[str, list[dict[str, Any]]], baseline_items_by_user: dict[str, set[str]]) -> int:
    return sum(1 for user, rows in candidates_by_user.items() for row in rows if row["item_id"] not in baseline_items_by_user.get(user, set()))


def _distribution(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"min": 0, "p50": 0, "p90": 0, "max": 0, "avg": 0.0}
    ordered = sorted(values)
    p50 = ordered[len(ordered) // 2]
    p90 = ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.9)))]
    return {"min": ordered[0], "p50": p50, "p90": p90, "max": ordered[-1], "avg": round(sum(values) / len(values), 6)}


def _status(swing_by_user: dict[str, list[dict[str, Any]]], session_by_user: dict[str, list[dict[str, Any]]]) -> str:
    if not any(swing_by_user.values()) and not any(session_by_user.values()):
        return "blocked"
    return "EXECUTED_PASS_OBSERVATION_ONLY"


def _forbidden_paths(custom_index_dir: Path, source_pool500_dir: Path) -> list[Path]:
    clean_dir = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
    return [clean_dir / name for name in FORBIDDEN_CANDIDATE_FILES] + [custom_index_dir / name for name in FORBIDDEN_CANDIDATE_FILES] + [source_pool500_dir / name for name in FORBIDDEN_CANDIDATE_FILES]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    manifest = run_pool500_sequence_session_custom_index(
        custom_index_dir=Path(args.custom_index_dir),
        source_pool500_dir=Path(args.source_pool500_dir),
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
        overwrite=args.overwrite,
    )
    print(f"Pool500 sequence/session custom-index observation status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
