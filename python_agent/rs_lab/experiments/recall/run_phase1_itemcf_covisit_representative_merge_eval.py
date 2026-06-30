from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json, write_jsonl

SCHEMA_VERSION = "phase1_itemcf_covisit_representative_merge_eval_v1"
DEFAULT_PHASE0_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "phase0_contract_precheck"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "full_main_route_other_methods" / "itemcf_covisit_representative_merge_eval"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_OUTPUT_NAMES = {"pool500", "pool1000"}
EVALUATION_ONLY_FILES = ("canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl")
FORBIDDEN_CANDIDATE_FILES = (*EVALUATION_ONLY_FILES, "user_sequences.valid.jsonl", "user_sequences.test.jsonl", "holdout.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge bounded ItemCF/co-visit sidecar into representative baseline and evaluate deltas.")
    parser.add_argument("--phase0-dir", default=str(DEFAULT_PHASE0_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--candidate-pool-size", type=int, default=200)
    parser.add_argument("--itemcf-per-user", type=int, default=40)
    parser.add_argument("--seed-window", type=int, default=20)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_phase1_itemcf_covisit_representative_merge_eval(
    *,
    phase0_dir: Path = DEFAULT_PHASE0_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_pool_size: int = 200,
    itemcf_per_user: int = 40,
    seed_window: int = 20,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    start = perf_counter()
    if enforce_venv:
        _enforce_project_venv()
    output_dir = output_dir.resolve()
    _validate_output_dir(output_dir)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if disk_free_start < min_free_bytes:
        raise RuntimeError(f"Free disk bytes below threshold: {disk_free_start} < {min_free_bytes}")

    phase0_dir = phase0_dir.resolve()
    phase0_manifest = _read_json(phase0_dir / "manifest.json")
    if phase0_manifest.get("status") != "PASS":
        raise RuntimeError(f"Phase 0 must PASS before Phase 1, got {phase0_manifest.get('status')}")
    phase0_resolved = _read_json(phase0_dir / "resolved_inputs.json")
    clean_dir = Path(phase0_resolved["full_clean_dir"]["path"]).resolve()
    baseline_dir = Path(phase0_resolved["lightweight_representative_baseline"]["path"]).resolve()
    sidecar_dir = Path(phase0_resolved["bounded_itemcf_covisit_sidecar"]["path"]).resolve()

    baseline_path = baseline_dir / "candidates.jsonl"
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    eval_paths = [clean_dir / name for name in EVALUATION_ONLY_FILES]
    _reject_forbidden_candidate_inputs([baseline_path, sequence_path, sidecar_dir])

    baseline_by_user = _load_baseline_candidates(baseline_path)
    user_ids = set(baseline_by_user)
    sequences_by_user = _load_train_sequences(sequence_path, user_ids, seed_window)
    neighbors_by_item, shard_paths = _load_sidecar_neighbors(sidecar_dir)

    user_latencies: list[float] = []
    itemcf_rows_by_user: dict[str, list[dict[str, Any]]] = {}
    merged_by_user: dict[str, list[dict[str, Any]]] = {}
    for user_id in sorted(baseline_by_user):
        user_start = perf_counter()
        baseline_rows = baseline_by_user[user_id]
        seen_items = set(sequences_by_user.get(user_id, []))
        itemcf_rows = _itemcf_rows_for_user(
            user_id=user_id,
            seeds=sequences_by_user.get(user_id, [])[-seed_window:],
            neighbors_by_item=neighbors_by_item,
            seen_items=seen_items,
            existing_items={row["item_id"] for row in baseline_rows},
            limit=itemcf_per_user,
        )
        itemcf_rows_by_user[user_id] = itemcf_rows
        merged_by_user[user_id] = _merge_rows(baseline_rows, itemcf_rows, candidate_pool_size)
        user_latencies.append(perf_counter() - user_start)

    positives_by_user = _load_evaluation_positives(eval_paths, user_ids)
    baseline_metrics = _candidate_metrics(baseline_by_user, positives_by_user)
    merged_metrics = _candidate_metrics(merged_by_user, positives_by_user)
    itemcf_metrics = _candidate_metrics(itemcf_rows_by_user, positives_by_user)
    latency = {"p50_seconds": _percentile(user_latencies, 0.5), "p95_seconds": _percentile(user_latencies, 0.95)}
    baseline_latency = {"p50_seconds": 0.0, "p95_seconds": 0.0}
    ablation = {
        "schema_version": SCHEMA_VERSION,
        "candidate_hit_users_delta": merged_metrics["candidate_hit_users"] - baseline_metrics["candidate_hit_users"],
        "recall_at_pool_delta": round(merged_metrics["recall_at_pool"] - baseline_metrics["recall_at_pool"], 6),
        "empty_candidate_rate_delta": round(merged_metrics["empty_candidate_rate"] - baseline_metrics["empty_candidate_rate"], 6),
        "fallback_rate_delta": round(merged_metrics["fallback_rate"] - baseline_metrics["fallback_rate"], 6),
        "overlap_delta": round(merged_metrics["source_overlap_jaccard"] - baseline_metrics["source_overlap_jaccard"], 6),
        "latency_p50_delta": round(latency["p50_seconds"] - baseline_latency["p50_seconds"], 6),
        "latency_p95_delta": round(latency["p95_seconds"] - baseline_latency["p95_seconds"], 6),
        "source_marginal_hit": itemcf_metrics["candidate_hit_users"],
    }
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "status": "EXECUTED_PASS_OBSERVATION_ONLY",
        "baseline": baseline_metrics,
        "merged": merged_metrics,
        "bounded_itemcf_covisit": itemcf_metrics,
        "latency_seconds": latency,
        "evaluation_only": {
            "read_files": [str(path) for path in eval_paths],
            "contract": "valid/test are read only after candidate generation for evaluation metrics",
        },
    }
    output_dir.mkdir(parents=True)
    write_jsonl(output_dir / "candidates.jsonl", _flatten_candidates(merged_by_user))
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "ablation_vs_lightweight_baseline.json", ablation)

    candidate_generation_read_files = [str(baseline_path), str(sequence_path), *[str(path) for path in shard_paths]]
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only_candidate_generation": True,
        "candidate_generation_read_files": candidate_generation_read_files,
        "evaluation_only_read_files": [str(path) for path in eval_paths],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "candidate_generation_uses_holdout": False,
        "evaluation_only_contract": "valid/test positives are used only for metrics and never to construct candidates",
        "disabled_outputs": {"pool500": True, "pool1000": True, "ranking_default_input": True},
        "source_signatures": {
            "baseline_candidates": _file_signature(baseline_path),
            "train_sequences": _file_signature(sequence_path),
            "sidecar_manifest": _file_signature(sidecar_dir / "manifest.json"),
            "sidecar_source_audit": _file_signature(sidecar_dir / "source_audit.json"),
        },
    }
    write_json(output_dir / "source_audit.json", source_audit)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "EXECUTED_PASS_OBSERVATION_ONLY",
        "phase0_status": phase0_manifest.get("status"),
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - start, 6),
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "candidate_pool_size": candidate_pool_size,
        "itemcf_per_user": itemcf_per_user,
        "seed_window": seed_window,
        "user_count": len(baseline_by_user),
        "candidate_row_count": sum(len(rows) for rows in merged_by_user.values()),
        "empty_user_count": merged_metrics["empty_candidate_users"],
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "metrics": str(output_dir / "metrics.json"),
            "ablation_vs_lightweight_baseline": str(output_dir / "ablation_vs_lightweight_baseline.json"),
            "candidates": str(output_dir / "candidates.jsonl"),
        },
        "disabled_outputs": {"pool500": True, "pool1000": True, "ranking_default_input": True},
        "source_audit_signature": _file_signature(output_dir / "source_audit.json"),
        "metrics_signature": _file_signature(output_dir / "metrics.json"),
        "ablation_signature": _file_signature(output_dir / "ablation_vs_lightweight_baseline.json"),
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _validate_output_dir(output_dir: Path) -> None:
    lowered = str(output_dir).replace("\\", "/").lower()
    if any(name in lowered for name in FORBIDDEN_OUTPUT_NAMES):
        raise ValueError(f"Phase 1 must not output pool500/pool1000 artifacts: {output_dir}")
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")


def _reject_forbidden_candidate_inputs(paths: list[Path]) -> None:
    for path in paths:
        lowered = str(path).replace("\\", "/").lower()
        if any(name in lowered for name in FORBIDDEN_CANDIDATE_FILES):
            raise ValueError(f"Forbidden candidate-generation input: {path}")


def _load_baseline_candidates(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            user_id = str(row.get("user_id", ""))
            item_id = str(row.get("item_id", ""))
            if user_id and item_id:
                by_user[user_id].append(_candidate_row(user_id, item_id, row.get("sources", []), row.get("source_scores", {}), row.get("category", "")))
    return dict(by_user)


def _load_train_sequences(path: Path, user_ids: set[str], seed_window: int) -> dict[str, list[str]]:
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
            sequences[user_id] = [str(item) for item in raw if item][-seed_window:]
            if len(sequences) == len(user_ids):
                break
    return sequences


def _load_sidecar_neighbors(sidecar_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], list[Path]]:
    neighbors: dict[str, list[dict[str, Any]]] = {}
    shard_paths = sorted(sidecar_dir.glob("neighbors_shard_*.jsonl"))
    for path in shard_paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                src_item = str(row.get("src_item", ""))
                if src_item:
                    neighbors[src_item] = list(row.get("neighbors", []))
    return neighbors, shard_paths


def _itemcf_rows_for_user(
    *,
    user_id: str,
    seeds: list[str],
    neighbors_by_item: dict[str, list[dict[str, Any]]],
    seen_items: set[str],
    existing_items: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    scores: Counter[str] = Counter()
    max_score: dict[str, float] = {}
    seed_by_item: dict[str, str] = {}
    for seed in reversed(seeds):
        for neighbor in neighbors_by_item.get(seed, []):
            item_id = str(neighbor.get("item_id", ""))
            if not item_id or item_id in seen_items or item_id in existing_items:
                continue
            score = float(neighbor.get("score", 0.0) or 0.0)
            scores[item_id] += score
            max_score[item_id] = max(max_score.get(item_id, 0.0), score)
            seed_by_item.setdefault(item_id, seed)
    ranked = sorted(scores, key=lambda item: (-scores[item], item))[:limit]
    return [
        _candidate_row(
            user_id,
            item_id,
            ["bounded_itemcf_covisit"],
            {"bounded_itemcf_covisit": round(float(scores[item_id]), 6)},
            "",
            {"seed_item_id": seed_by_item.get(item_id), "max_neighbor_score": round(max_score.get(item_id, 0.0), 6)},
        )
        for item_id in ranked
    ]


def _merge_rows(baseline_rows: list[dict[str, Any]], itemcf_rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in [*baseline_rows, *itemcf_rows]:
        item_id = row["item_id"]
        current = merged.get(item_id)
        if current is None:
            merged[item_id] = dict(row)
            merged[item_id]["sources"] = list(row.get("sources", []))
            merged[item_id]["source_scores"] = dict(row.get("source_scores", {}))
            continue
        for source in row.get("sources", []):
            if source not in current["sources"]:
                current["sources"].append(source)
        for source, score in row.get("source_scores", {}).items():
            current["source_scores"][source] = max(float(current["source_scores"].get(source, 0.0)), float(score))
    rows = list(merged.values())
    rows.sort(key=lambda item: (-sum(float(v) for v in item.get("source_scores", {}).values()), item["item_id"]))
    for rank, row in enumerate(rows[:limit], start=1):
        row["rank"] = rank
    return rows[:limit]


def _load_evaluation_positives(paths: list[Path], user_ids: set[str]) -> dict[str, set[str]]:
    positives: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                user_id = str(row.get("user_id", ""))
                if user_id in user_ids and row.get("label_binary"):
                    item_id = str(row.get("parent_asin", ""))
                    if item_id:
                        positives[user_id].add(item_id)
    return dict(positives)


def _candidate_metrics(candidates_by_user: dict[str, list[dict[str, Any]]], positives_by_user: dict[str, set[str]]) -> dict[str, Any]:
    users = sorted(candidates_by_user)
    users_with_holdout = [user for user in users if positives_by_user.get(user)]
    eval_users = users_with_holdout or users
    candidate_counts = [len(candidates_by_user.get(user, [])) for user in users]
    hit_users = 0
    recalls: list[float] = []
    source_hits: Counter[str] = Counter()
    source_users: dict[str, set[str]] = defaultdict(set)
    source_items: dict[str, set[str]] = defaultdict(set)
    source_pairs: Counter[str] = Counter()
    for user in users:
        rows = candidates_by_user.get(user, [])
        targets = positives_by_user.get(user, set())
        candidate_items = [row["item_id"] for row in rows]
        if user in eval_users and targets:
            hits = set(candidate_items) & targets
            if hits:
                hit_users += 1
            recalls.append(round(len(hits) / len(targets), 6) if targets else 0.0)
            for row in rows:
                if row["item_id"] in hits:
                    source_hits.update(row.get("sources", []))
        for row in rows:
            sources = sorted(set(row.get("sources", [])))
            for source in sources:
                source_users[source].add(user)
                source_items[source].add(row["item_id"])
            for left_index, left in enumerate(sources):
                for right in sources[left_index + 1 :]:
                    source_pairs[f"{left}+{right}"] += 1
    empty_users = sum(1 for count in candidate_counts if count == 0)
    return {
        "users_total": len(users),
        "users_with_holdout": len(users_with_holdout),
        "candidate_row_count": sum(candidate_counts),
        "candidate_count_avg": round(sum(candidate_counts) / len(candidate_counts), 6) if candidate_counts else 0.0,
        "empty_candidate_users": empty_users,
        "empty_candidate_rate": round(empty_users / len(users), 6) if users else 0.0,
        "fallback_rate": round(empty_users / len(users), 6) if users else 0.0,
        "candidate_hit_users": hit_users,
        "candidate_hit_rate_at_pool": round(hit_users / len(eval_users), 6) if eval_users and positives_by_user else 0.0,
        "recall_at_pool": round(sum(recalls) / len(recalls), 6) if recalls else 0.0,
        "source_marginal_hit": dict(sorted(source_hits.items())),
        "source_user_coverage": dict(sorted((source, len(items)) for source, items in source_users.items())),
        "source_item_coverage": dict(sorted((source, len(items)) for source, items in source_items.items())),
        "source_overlap": dict(sorted(source_pairs.items())),
        "source_overlap_jaccard": _source_overlap_jaccard(source_items),
    }


def _source_overlap_jaccard(source_items: dict[str, set[str]]) -> float:
    sources = sorted(source_items)
    if len(sources) < 2:
        return 0.0
    values = []
    for index, left in enumerate(sources):
        for right in sources[index + 1 :]:
            union = source_items[left] | source_items[right]
            values.append(len(source_items[left] & source_items[right]) / len(union) if union else 0.0)
    return round(sum(values) / len(values), 6) if values else 0.0


def _flatten_candidates(candidates_by_user: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [row for user in sorted(candidates_by_user) for row in candidates_by_user[user]]


def _candidate_row(
    user_id: str,
    item_id: str,
    sources: list[str],
    source_scores: dict[str, Any],
    category: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "rank": 0,
        "item_id": item_id,
        "sources": [str(source) for source in sources],
        "source_scores": {str(source): float(score) for source, score in source_scores.items()},
        "category": category or "",
        "metadata": metadata or {},
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if fraction == 0.5:
        return round(float(median(ordered)), 6)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(float(ordered[index]), 6)


def _file_signature(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            rows += chunk.count(b"\n")
    return {"path": str(path), "size_bytes": path.stat().st_size, "row_count": rows if path.suffix == ".jsonl" else None, "sha256": digest.hexdigest()}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            return current
        current = current.parent
    return current


def _enforce_project_venv() -> None:
    executable = Path(sys.executable).resolve()
    expected = (ROOT / ".venv").resolve()
    try:
        executable.relative_to(expected)
    except ValueError as exc:
        raise RuntimeError(f"Project .venv Python is required, got {sys.executable}") from exc


def main() -> None:
    args = parse_args()
    manifest = run_phase1_itemcf_covisit_representative_merge_eval(
        phase0_dir=Path(args.phase0_dir),
        output_dir=Path(args.output_dir),
        candidate_pool_size=args.candidate_pool_size,
        itemcf_per_user=args.itemcf_per_user,
        seed_window=args.seed_window,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    print(f"Phase 1 ItemCF/co-visit representative merge/eval status: {manifest['status']}")
    print(f"Manifest written to: {manifest['required_artifacts']['manifest']}")


if __name__ == "__main__":
    main()
