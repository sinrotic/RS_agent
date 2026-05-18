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

from rs_core.common.io import iter_jsonl, write_json, write_jsonl
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import (
    _candidate_metrics,
    _candidate_row,
    _enforce_project_venv,
    _existing_ancestor,
    _file_signature,
    _flatten_candidates,
    _load_evaluation_positives,
    _merge_rows,
    _percentile,
)

SCHEMA_VERSION = "pool500_all_methods_lightweight_cf_v1"
DEFAULT_CUSTOM_INDEX_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative" / "custom_index"
DEFAULT_SOURCE_POOL500_DIR = ROOT / "outputs" / "recall" / "pool500_representative" / "contract_precheck_or_p0_p2"
DEFAULT_CLEAN_DIR = ROOT / "data" / "processed" / "amazon_2023_recall_clean_full"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "recall" / "pool500_all_methods_representative" / "lightweight_cf_methods"
DEFAULT_MIN_FREE_BYTES = 50 * 1024**3
FORBIDDEN_PATH_PARTS = ("amazon_2023_recall_clean_10000", "amazon_2023_recall_views_10000")
EVALUATION_ONLY_FILES = ("canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl")
FORBIDDEN_CANDIDATE_FILES = (*EVALUATION_ONLY_FILES, "user_sequences.valid.jsonl", "user_sequences.test.jsonl", "holdout.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pool500 representative lightweight + bounded CF recall-only observations.")
    parser.add_argument("--custom-index-dir", default=str(DEFAULT_CUSTOM_INDEX_DIR))
    parser.add_argument("--source-pool500-dir", default=str(DEFAULT_SOURCE_POOL500_DIR))
    parser.add_argument("--clean-dir", default=str(DEFAULT_CLEAN_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--candidate-pool-size", type=int, default=500)
    parser.add_argument("--itemcf-per-user", type=int, default=40)
    parser.add_argument("--usercf-per-user", type=int, default=30)
    parser.add_argument("--seed-window", type=int, default=20)
    parser.add_argument("--similar-users", type=int, default=30)
    parser.add_argument("--max-users", type=int, default=500)
    parser.add_argument("--max-items-per-user", type=int, default=50)
    parser.add_argument("--max-item-users", type=int, default=100)
    parser.add_argument("--max-neighbors-per-item", type=int, default=80)
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--skip-venv-check", action="store_true")
    return parser.parse_args()


def run_pool500_all_methods_lightweight_cf(
    *,
    custom_index_dir: Path = DEFAULT_CUSTOM_INDEX_DIR,
    source_pool500_dir: Path = DEFAULT_SOURCE_POOL500_DIR,
    clean_dir: Path = DEFAULT_CLEAN_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    candidate_pool_size: int = 500,
    itemcf_per_user: int = 40,
    usercf_per_user: int = 30,
    seed_window: int = 20,
    similar_users: int = 30,
    max_users: int = 500,
    max_items_per_user: int = 50,
    max_item_users: int = 100,
    max_neighbors_per_item: int = 80,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    enforce_venv: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    if enforce_venv:
        _enforce_project_venv()
    _validate_caps(candidate_pool_size, itemcf_per_user, usercf_per_user, seed_window, similar_users, max_users, max_items_per_user, max_item_users, max_neighbors_per_item)

    custom_index_dir = custom_index_dir.resolve()
    source_pool500_dir = source_pool500_dir.resolve()
    clean_dir = clean_dir.resolve()
    output_dir = output_dir.resolve()
    _precheck(custom_index_dir, source_pool500_dir, clean_dir, output_dir, min_free_bytes)
    disk_free_start = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free

    custom_manifest = _read_json(custom_index_dir / "manifest.json")
    source_manifest = _read_json(source_pool500_dir / "manifest.json")
    if custom_manifest.get("status") != "PASS":
        raise RuntimeError(f"Custom index must PASS, got {custom_manifest.get('status')}")
    if source_manifest.get("status") != "PASS":
        raise RuntimeError(f"Source pool500 must PASS, got {source_manifest.get('status')}")

    custom_item_ids = _load_custom_item_ids(custom_index_dir / "custom_item_index.json")
    sequences_by_user = _load_indexed_sequences(custom_index_dir / "indexed_train_sequences.jsonl", max_users, max_items_per_user)
    user_ids = set(sequences_by_user)
    baseline_by_user = _load_lightweight_candidates(source_pool500_dir / "pool500_recall_only" / "candidates.jsonl", user_ids, custom_item_ids)
    missing_baseline_users = sorted(user_ids.difference(baseline_by_user))
    if missing_baseline_users:
        raise ValueError(f"Missing lightweight candidates for representative users: {missing_baseline_users[:5]}")

    neighbor_index, co_visit_stats = _build_bounded_itemcf_neighbors(sequences_by_user, custom_item_ids, max_neighbors_per_item)
    item_users, item_user_stats = _build_bounded_item_users(sequences_by_user, max_item_users)

    itemcf_by_user: dict[str, list[dict[str, Any]]] = {}
    usercf_by_user: dict[str, list[dict[str, Any]]] = {}
    merged_by_user: dict[str, list[dict[str, Any]]] = {}
    itemcf_latencies: list[float] = []
    usercf_latencies: list[float] = []
    for user_id in sorted(baseline_by_user):
        baseline_rows = baseline_by_user[user_id]
        seeds = sequences_by_user.get(user_id, [])[-seed_window:]
        seen_items = set(sequences_by_user.get(user_id, []))
        existing_items = {row["item_id"] for row in baseline_rows}

        itemcf_start = perf_counter()
        itemcf_rows = _itemcf_rows_for_user(user_id, seeds, neighbor_index, seen_items, existing_items, itemcf_per_user)
        itemcf_latencies.append(perf_counter() - itemcf_start)

        usercf_start = perf_counter()
        usercf_rows = _usercf_rows_for_user(user_id, sequences_by_user, item_users, seen_items, existing_items | {row["item_id"] for row in itemcf_rows}, similar_users, usercf_per_user)
        usercf_latencies.append(perf_counter() - usercf_start)

        itemcf_by_user[user_id] = itemcf_rows
        usercf_by_user[user_id] = usercf_rows
        merged_by_user[user_id] = _merge_rows(baseline_rows, [*itemcf_rows, *usercf_rows], candidate_pool_size)

    eval_paths = [clean_dir / name for name in EVALUATION_ONLY_FILES]
    positives_by_user = _load_evaluation_positives(eval_paths, set(baseline_by_user))
    lightweight_metrics = _candidate_metrics(baseline_by_user, positives_by_user)
    merged_metrics = _candidate_metrics(merged_by_user, positives_by_user)
    itemcf_metrics = _candidate_metrics(itemcf_by_user, positives_by_user)
    usercf_metrics = _candidate_metrics(usercf_by_user, positives_by_user)
    by_source_metrics = {
        source: _candidate_metrics(_filter_by_source(baseline_by_user, source), positives_by_user)
        for source in ("popular", "category", "semantic")
    }

    output_dir.mkdir(parents=True, exist_ok=False)
    write_jsonl(output_dir / "candidates.jsonl", _flatten_candidates(merged_by_user))
    write_jsonl(output_dir / "itemcf_candidates.jsonl", _flatten_candidates(itemcf_by_user))
    write_jsonl(output_dir / "usercf_candidates.jsonl", _flatten_candidates(usercf_by_user))

    method_metrics = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "lightweight_pool500": lightweight_metrics,
        "lightweight_by_source": by_source_metrics,
        "bounded_itemcf_covisit": itemcf_metrics,
        "bounded_usercf": usercf_metrics,
        "merged_lightweight_cf": merged_metrics,
        "latency_seconds": {
            "itemcf": {"p50_seconds": _percentile(itemcf_latencies, 0.5), "p95_seconds": _percentile(itemcf_latencies, 0.95)},
            "usercf": {"p50_seconds": _percentile(usercf_latencies, 0.5), "p95_seconds": _percentile(usercf_latencies, 0.95)},
        },
        "evaluation_only": {"read_files": [str(path) for path in eval_paths], "contract": "valid/test are read only after candidate generation for metrics"},
    }
    contribution = _method_contribution(lightweight_metrics, merged_metrics, itemcf_metrics, usercf_metrics)
    source_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "train_only_candidate_generation": True,
        "candidate_generation_uses_holdout": False,
        "candidate_generation_read_files": [
            str(source_pool500_dir / "pool500_recall_only" / "candidates.jsonl"),
            str(custom_index_dir / "indexed_train_sequences.jsonl"),
            str(custom_index_dir / "custom_item_index.json"),
        ],
        "evaluation_only_read_files": [str(path) for path in eval_paths],
        "forbidden_candidate_generation_inputs": [str(clean_dir / name) for name in FORBIDDEN_CANDIDATE_FILES],
        "no_10k_source": True,
        "no_full_clean_copy": True,
        "custom_index_scope_only": True,
        "bounded_itemcf_covisit": {"representative_user_count": len(sequences_by_user), "custom_item_count": len(custom_item_ids), "full_global_cooccurrence_counter": False, **co_visit_stats},
        "bounded_usercf": {"no_dense_user_user_matrix": True, "max_users": max_users, "max_items_per_user": max_items_per_user, "max_item_users": max_item_users, "similar_users": similar_users, **item_user_stats},
        "disabled_outputs": {"pool1000": True, "ranking": True, "ranking_default_input_modified": False, "two_tower_training": True, "graph_training": True, "mf_training": True},
        "source_signatures": {
            "custom_index_manifest": _file_signature(custom_index_dir / "manifest.json"),
            "indexed_train_sequences": _file_signature(custom_index_dir / "indexed_train_sequences.jsonl"),
            "custom_item_index": _file_signature(custom_index_dir / "custom_item_index.json"),
            "source_pool500_candidates": _file_signature(source_pool500_dir / "pool500_recall_only" / "candidates.jsonl"),
        },
    }
    resource_audit = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "disk_free_bytes_start": disk_free_start,
        "disk_free_bytes_end": shutil.disk_usage(_existing_ancestor(output_dir.parent)).free,
        "min_free_bytes": min_free_bytes,
        "bounded_user_count": len(sequences_by_user),
        "custom_item_count": len(custom_item_ids),
        "candidate_pool_size": candidate_pool_size,
        "lightweight_candidate_rows": lightweight_metrics["candidate_row_count"],
        "itemcf_candidate_rows": itemcf_metrics["candidate_row_count"],
        "usercf_candidate_rows": usercf_metrics["candidate_row_count"],
        "merged_candidate_rows": merged_metrics["candidate_row_count"],
    }
    write_json(output_dir / "method_metrics.json", method_metrics)
    write_json(output_dir / "method_contribution.json", contribution)
    write_json(output_dir / "source_audit.json", source_audit)
    write_json(output_dir / "resource_audit.json", resource_audit)

    status = "PASS" if itemcf_metrics["candidate_row_count"] > 0 or usercf_metrics["candidate_row_count"] > 0 else "BLOCKED_NO_CF_CANDIDATES"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "pool500_all_methods_representative_lightweight_cf_recall_only",
        "output_dir": str(output_dir),
        "runtime_seconds": round(perf_counter() - started, 6),
        "project_venv_required": enforce_venv,
        "custom_index_status": custom_manifest.get("status"),
        "source_pool500_status": source_manifest.get("status"),
        "representative_user_count": len(sequences_by_user),
        "custom_item_count": len(custom_item_ids),
        "candidate_pool_size": candidate_pool_size,
        "candidate_row_count": merged_metrics["candidate_row_count"],
        "candidate_generation_uses_holdout": False,
        "no_dense_user_user_matrix": True,
        "full_global_cooccurrence_counter": False,
        "required_artifacts": {
            "manifest": str(output_dir / "manifest.json"),
            "source_audit": str(output_dir / "source_audit.json"),
            "resource_audit": str(output_dir / "resource_audit.json"),
            "method_metrics": str(output_dir / "method_metrics.json"),
            "method_contribution": str(output_dir / "method_contribution.json"),
            "candidates": str(output_dir / "candidates.jsonl"),
            "itemcf_candidates": str(output_dir / "itemcf_candidates.jsonl"),
            "usercf_candidates": str(output_dir / "usercf_candidates.jsonl"),
        },
        "artifact_signatures": {
            "candidates": _file_signature(output_dir / "candidates.jsonl"),
            "itemcf_candidates": _file_signature(output_dir / "itemcf_candidates.jsonl"),
            "usercf_candidates": _file_signature(output_dir / "usercf_candidates.jsonl"),
            "method_metrics": _file_signature(output_dir / "method_metrics.json"),
            "source_audit": _file_signature(output_dir / "source_audit.json"),
            "resource_audit": _file_signature(output_dir / "resource_audit.json"),
        },
    }
    write_json(output_dir / "manifest.json", manifest)
    return manifest


def _validate_caps(candidate_pool_size: int, itemcf_per_user: int, usercf_per_user: int, seed_window: int, similar_users: int, max_users: int, max_items_per_user: int, max_item_users: int, max_neighbors_per_item: int) -> None:
    for label, value in {
        "candidate_pool_size": candidate_pool_size,
        "itemcf_per_user": itemcf_per_user,
        "usercf_per_user": usercf_per_user,
        "seed_window": seed_window,
        "similar_users": similar_users,
        "max_users": max_users,
        "max_items_per_user": max_items_per_user,
        "max_item_users": max_item_users,
        "max_neighbors_per_item": max_neighbors_per_item,
    }.items():
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if candidate_pool_size != 500:
        raise ValueError("This task must remain representative pool500 recall-only")
    if max_users > 500:
        raise ValueError("max_users must be <= 500 for representative custom-index scope")


def _precheck(custom_index_dir: Path, source_pool500_dir: Path, clean_dir: Path, output_dir: Path, min_free_bytes: int) -> None:
    for path in (custom_index_dir, source_pool500_dir, clean_dir, output_dir):
        lowered = str(path).replace("\\", "/").lower()
        if any(part in lowered for part in FORBIDDEN_PATH_PARTS):
            raise ValueError(f"Forbidden 10k path for pool500 all-methods task: {path}")
    required = [
        custom_index_dir / "manifest.json",
        custom_index_dir / "custom_item_index.json",
        custom_index_dir / "indexed_train_sequences.jsonl",
        source_pool500_dir / "manifest.json",
        source_pool500_dir / "pool500_recall_only" / "candidates.jsonl",
        *(clean_dir / name for name in EVALUATION_ONLY_FILES),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required input files: " + ", ".join(missing))
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    free_bytes = shutil.disk_usage(_existing_ancestor(output_dir.parent)).free
    if free_bytes < min_free_bytes:
        raise RuntimeError(f"D drive free bytes below threshold: {free_bytes} < {min_free_bytes}")


def _load_custom_item_ids(path: Path) -> set[str]:
    payload = _read_json(path)
    return {str(row["item_id"]) for row in payload.get("items", []) if row.get("item_id")}


def _load_indexed_sequences(path: Path, max_users: int, max_items_per_user: int) -> dict[str, list[str]]:
    sequences: dict[str, list[str]] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        raw = row.get("strong_positive_item_ids") or row.get("positive_item_ids") or row.get("item_ids") or []
        sequences[user_id] = list(dict.fromkeys(str(item) for item in raw if item))[-max_items_per_user:]
        if len(sequences) >= max_users:
            break
    return sequences


def _load_lightweight_candidates(path: Path, user_ids: set[str], custom_item_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if user_id in user_ids and item_id in custom_item_ids:
            by_user[user_id].append(_candidate_row(user_id, item_id, [str(source) for source in row.get("sources", [])], row.get("source_scores", {}), str(row.get("category", ""))))
    return dict(by_user)


def _build_bounded_itemcf_neighbors(sequences_by_user: dict[str, list[str]], custom_item_ids: set[str], max_neighbors_per_item: int) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    co_counts: dict[str, Counter[str]] = defaultdict(Counter)
    pair_updates = 0
    for items in sequences_by_user.values():
        scoped_items = [item for item in dict.fromkeys(items) if item in custom_item_ids]
        for left_index, left in enumerate(scoped_items):
            for right in scoped_items[left_index + 1 :]:
                if left == right:
                    continue
                co_counts[left][right] += 1
                co_counts[right][left] += 1
                pair_updates += 2
    neighbors = {
        item: [{"item_id": neighbor, "score": float(count)} for neighbor, count in counter.most_common(max_neighbors_per_item)]
        for item, counter in co_counts.items()
    }
    return neighbors, {"co_visit_source": "custom_index_representative_train_sequences", "co_visit_item_count": len(co_counts), "co_visit_pair_updates": pair_updates, "max_neighbors_per_item": max_neighbors_per_item}


def _build_bounded_item_users(sequences_by_user: dict[str, list[str]], max_item_users: int) -> tuple[dict[str, set[str]], dict[str, Any]]:
    item_users: dict[str, set[str]] = defaultdict(set)
    truncated_items: set[str] = set()
    for user_id, items in sequences_by_user.items():
        for item_id in items:
            users = item_users[item_id]
            if len(users) < max_item_users:
                users.add(user_id)
            else:
                truncated_items.add(item_id)
    return dict(item_users), {"item_user_index_item_count": len(item_users), "truncated_hot_item_count": len(truncated_items)}


def _itemcf_rows_for_user(user_id: str, seeds: list[str], neighbors_by_item: dict[str, list[dict[str, Any]]], seen_items: set[str], existing_items: set[str], limit: int) -> list[dict[str, Any]]:
    scores: Counter[str] = Counter()
    seed_by_item: dict[str, str] = {}
    for seed in reversed(seeds):
        for neighbor in neighbors_by_item.get(seed, []):
            item_id = str(neighbor.get("item_id", ""))
            if not item_id or item_id in seen_items or item_id in existing_items:
                continue
            scores[item_id] += float(neighbor.get("score", 0.0) or 0.0)
            seed_by_item.setdefault(item_id, seed)
    ranked = sorted(scores, key=lambda item: (-scores[item], item))[:limit]
    return [_candidate_row(user_id, item_id, ["bounded_itemcf_covisit"], {"bounded_itemcf_covisit": round(float(scores[item_id]), 6)}, "", {"seed_item_id": seed_by_item.get(item_id), "scope": "custom_index_train"}) for item_id in ranked]


def _usercf_rows_for_user(user_id: str, sequences_by_user: dict[str, list[str]], item_users: dict[str, set[str]], seen_items: set[str], existing_items: set[str], similar_users: int, limit: int) -> list[dict[str, Any]]:
    seeds = sequences_by_user.get(user_id, [])
    if not seeds:
        return []
    overlap_scores: Counter[str] = Counter()
    for item_id in set(seeds):
        for other_user in item_users.get(item_id, set()):
            if other_user != user_id:
                overlap_scores[other_user] += 1
    top_users = [other_user for other_user, _ in overlap_scores.most_common(similar_users)]
    candidate_scores: Counter[str] = Counter()
    source_users: dict[str, set[str]] = defaultdict(set)
    for other_user in top_users:
        for item_id in sequences_by_user.get(other_user, []):
            if item_id in seen_items or item_id in existing_items:
                continue
            candidate_scores[item_id] += overlap_scores[other_user]
            source_users[item_id].add(other_user)
    ranked = sorted(candidate_scores, key=lambda item: (-candidate_scores[item], item))[:limit]
    return [_candidate_row(user_id, item_id, ["usercf_bounded"], {"usercf_bounded": round(float(candidate_scores[item_id]), 6)}, "", {"similar_user_count": len(source_users[item_id]), "scope": "custom_index_train_no_dense_matrix"}) for item_id in ranked]


def _filter_by_source(candidates_by_user: dict[str, list[dict[str, Any]]], source: str) -> dict[str, list[dict[str, Any]]]:
    return {user_id: [row for row in rows if source in set(row.get("sources", []))] for user_id, rows in candidates_by_user.items()}


def _method_contribution(lightweight_metrics: dict[str, Any], merged_metrics: dict[str, Any], itemcf_metrics: dict[str, Any], usercf_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_hit_users_delta_vs_lightweight": merged_metrics["candidate_hit_users"] - lightweight_metrics["candidate_hit_users"],
        "recall_at_pool_delta_vs_lightweight": round(merged_metrics["recall_at_pool"] - lightweight_metrics["recall_at_pool"], 6),
        "itemcf_candidate_rows": itemcf_metrics["candidate_row_count"],
        "itemcf_candidate_hit_users": itemcf_metrics["candidate_hit_users"],
        "usercf_candidate_rows": usercf_metrics["candidate_row_count"],
        "usercf_candidate_hit_users": usercf_metrics["candidate_hit_users"],
        "decision": "observation_only_recall_method_evidence",
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    manifest = run_pool500_all_methods_lightweight_cf(
        custom_index_dir=Path(args.custom_index_dir),
        source_pool500_dir=Path(args.source_pool500_dir),
        clean_dir=Path(args.clean_dir),
        output_dir=Path(args.output_dir),
        candidate_pool_size=args.candidate_pool_size,
        itemcf_per_user=args.itemcf_per_user,
        usercf_per_user=args.usercf_per_user,
        seed_window=args.seed_window,
        similar_users=args.similar_users,
        max_users=args.max_users,
        max_items_per_user=args.max_items_per_user,
        max_item_users=args.max_item_users,
        max_neighbors_per_item=args.max_neighbors_per_item,
        min_free_bytes=args.min_free_bytes,
        enforce_venv=not args.skip_venv_check,
    )
    if manifest["status"] != "PASS":
        raise RuntimeError(f"Pool500 lightweight+CF did not pass: {manifest['status']}")
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["required_artifacts"]["manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
