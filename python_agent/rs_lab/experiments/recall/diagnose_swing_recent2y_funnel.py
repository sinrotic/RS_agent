from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_lab.experiments.recall.run_phase1_itemcf_covisit_representative_merge_eval import _file_signature

SCHEMA_VERSION = "swing_recent2y_funnel_diagnostic_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose train-only Swing recall coverage and hit funnel.")
    parser.add_argument("--train-sequences", required=True)
    parser.add_argument("--source-dir", required=True, help="Directory containing swing_recall_edges.jsonl and dropped_hot_items.json")
    parser.add_argument("--valid-labels", required=True)
    parser.add_argument("--test-labels", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-user-items", type=int, default=50)
    parser.add_argument("--per-seed-top-k", type=int, default=100)
    parser.add_argument("--max-k", type=int, default=500)
    return parser.parse_args()


def build_swing_funnel_diagnostic(
    *,
    train_sequences_path: Path,
    source_dir: Path,
    split_label_paths: dict[str, Path],
    max_user_items: int = 50,
    per_seed_top_k: int = 100,
    max_k: int = 500,
) -> dict[str, Any]:
    if max_user_items <= 0 or per_seed_top_k <= 0 or max_k <= 0:
        raise ValueError("max_user_items, per_seed_top_k and max_k must be positive")

    train_sequences_path = train_sequences_path.resolve()
    source_dir = source_dir.resolve()
    edges_path = source_dir / "swing_recall_edges.jsonl"
    dropped_hot_path = source_dir / "dropped_hot_items.json"
    _validate_paths(train_sequences_path, edges_path, dropped_hot_path, split_label_paths)

    sequences_by_user = _load_train_sequences(train_sequences_path, max_user_items)
    edge_index, dst_items, edge_count = _load_edge_index(edges_path, per_seed_top_k)
    dropped_hot_items = _load_dropped_hot_items(dropped_hot_path)

    split_reports = {
        split: _diagnose_split(
            label_path=path,
            sequences_by_user=sequences_by_user,
            edge_index=edge_index,
            dst_items=dst_items,
            dropped_hot_items=dropped_hot_items,
            max_user_items=max_user_items,
            max_k=max_k,
        )
        for split, path in split_label_paths.items()
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "source": "swing_recall",
        "train_only": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "pool1000_allowed": False,
        "governance": {
            "candidate_generation_inputs": ["train_user_sequences", "train_only_swing_edges", "dropped_hot_items"],
            "evaluation_only_inputs": sorted(split_label_paths),
            "valid_test_holdout_usage": "evaluation_only_metrics_not_candidate_generation",
            "uses_valid_for_training_or_graph": False,
            "uses_test_for_training_or_graph": False,
            "uses_holdout": False,
            "promotion_allowed": False,
        },
        "parameters": {
            "max_user_items": max_user_items,
            "per_seed_top_k": per_seed_top_k,
            "max_k": max_k,
        },
        "input_contract": {
            "train_sequences_path": str(train_sequences_path),
            "source_dir": str(source_dir),
            "edges_path": str(edges_path),
            "dropped_hot_items_path": str(dropped_hot_path),
            "split_label_paths": {split: str(path.resolve()) for split, path in split_label_paths.items()},
        },
        "source_signatures": {
            "train_sequences": _file_signature(train_sequences_path),
            "swing_recall_edges": _file_signature(edges_path),
            "dropped_hot_items": _file_signature(dropped_hot_path),
            **{f"{split}_labels": _file_signature(path.resolve()) for split, path in split_label_paths.items()},
        },
        "source_stats": {
            "train_user_count": len(sequences_by_user),
            "edge_count": edge_count,
            "seed_count": len(edge_index),
            "dst_item_count": len(dst_items),
            "dropped_hot_item_count": len(dropped_hot_items),
        },
        "splits": split_reports,
    }


def _validate_paths(train_sequences_path: Path, edges_path: Path, dropped_hot_path: Path, split_label_paths: dict[str, Path]) -> None:
    if train_sequences_path.name != "user_sequences.train.jsonl":
        raise ValueError(f"Expected train-only user_sequences.train.jsonl, got: {train_sequences_path}")
    missing = [str(path) for path in [train_sequences_path, edges_path, dropped_hot_path, *split_label_paths.values()] if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required diagnostic inputs: " + ", ".join(missing))


def _load_train_sequences(path: Path, max_user_items: int) -> dict[str, list[str]]:
    sequences_by_user: dict[str, list[str]] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        raw_items = [str(item_id) for item_id in row.get("recent_positive_item_sequence", []) or [] if item_id]
        if not raw_items:
            continue
        sequences_by_user[user_id] = list(dict.fromkeys(raw_items[-max_user_items:]))
    return sequences_by_user


def _load_edge_index(path: Path, per_seed_top_k: int) -> tuple[dict[str, list[tuple[str, float]]], set[str], int]:
    raw_edges: dict[str, list[tuple[str, float, int]]] = defaultdict(list)
    dst_items: set[str] = set()
    edge_count = 0
    for row in iter_jsonl(path):
        src_item = str(row.get("src_item", ""))
        dst_item = str(row.get("dst_item", ""))
        if not src_item or not dst_item:
            continue
        score = float(row.get("score", 0.0))
        rank = int(row.get("rank", len(raw_edges[src_item]) + 1))
        raw_edges[src_item].append((dst_item, score, rank))
        dst_items.add(dst_item)
        edge_count += 1
    edge_index = {
        src_item: [(dst_item, score) for dst_item, score, _ in sorted(edges, key=lambda item: (item[2], -item[1], item[0]))[:per_seed_top_k]]
        for src_item, edges in raw_edges.items()
    }
    return edge_index, dst_items, edge_count


def _load_dropped_hot_items(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item.get("item_id", "")) for item in payload.get("items", []) if item.get("item_id")}


def _load_positive_targets(path: Path) -> dict[str, set[str]]:
    targets_by_user: dict[str, set[str]] = defaultdict(set)
    for row in iter_jsonl(path):
        if int(row.get("label", 1)) != 1:
            continue
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if user_id and item_id:
            targets_by_user[user_id].add(item_id)
    return dict(targets_by_user)


def _diagnose_split(
    *,
    label_path: Path,
    sequences_by_user: dict[str, list[str]],
    edge_index: dict[str, list[tuple[str, float]]],
    dst_items: set[str],
    dropped_hot_items: set[str],
    max_user_items: int,
    max_k: int,
) -> dict[str, Any]:
    targets_by_user = _load_positive_targets(label_path)
    records = []
    for user_id, targets in sorted(targets_by_user.items()):
        seq = sequences_by_user.get(user_id)
        if seq is None:
            records.append(_missing_record(user_id, targets, dst_items))
            continue
        seed_window = seq[-max_user_items:]
        has_seed_in_graph = any(seed in edge_index for seed in seed_window)
        has_hot_dropped_seed = any(seed in dropped_hot_items for seed in seed_window)
        candidates = _candidates_for(seed_window, edge_index, max_k)
        candidate_set = set(candidates)
        hit_count = len(targets & candidate_set)
        records.append(
            {
                "user_id": user_id,
                "bucket": _bucket_for_train_len(len(seq)),
                "target_count": len(targets),
                "missing_train_sequence": False,
                "has_train_sequence": True,
                "train_len": len(seq),
                "train_len_ge2": len(seq) >= 2,
                "has_seed_in_graph": has_seed_in_graph,
                "has_hot_dropped_seed": has_hot_dropped_seed,
                "without_graph_seed_but_hot_dropped_seed": not has_seed_in_graph and has_hot_dropped_seed,
                "target_exists_as_any_dst": bool(targets & dst_items),
                "candidate_count": len(candidates),
                "generated_candidate": bool(candidates),
                "hit_count": hit_count,
                "hit_user": hit_count > 0,
                "recall_sum": hit_count / len(targets) if targets else 0.0,
            }
        )
    return _aggregate_records(records, max_k)


def _missing_record(user_id: str, targets: set[str], dst_items: set[str]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "bucket": "missing_train_sequence",
        "target_count": len(targets),
        "missing_train_sequence": True,
        "has_train_sequence": False,
        "train_len": 0,
        "train_len_ge2": False,
        "has_seed_in_graph": False,
        "has_hot_dropped_seed": False,
        "without_graph_seed_but_hot_dropped_seed": False,
        "target_exists_as_any_dst": bool(targets & dst_items),
        "candidate_count": 0,
        "generated_candidate": False,
        "hit_count": 0,
        "hit_user": False,
        "recall_sum": 0.0,
    }


def _bucket_for_train_len(train_len: int) -> str:
    if train_len <= 1:
        return "cold_or_single_seed"
    if train_len <= 3:
        return "light_behavior_2_3"
    if train_len <= 9:
        return "medium_behavior_4_9"
    return "collaborative_rich_10_plus"


def _candidates_for(seed_window: list[str], edge_index: dict[str, list[tuple[str, float]]], max_k: int) -> list[str]:
    seen = set(seed_window)
    scored: dict[str, float] = {}
    for seed in seed_window:
        for item_id, score in edge_index.get(seed, []):
            if item_id in seen:
                continue
            if score > scored.get(item_id, -1.0):
                scored[item_id] = score
    return [item_id for item_id, _ in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:max_k]]


def _aggregate_records(records: list[dict[str, Any]], max_k: int) -> dict[str, Any]:
    overall = _aggregate_subset(records, max_k)
    by_bucket = {
        bucket: _aggregate_subset([record for record in records if record["bucket"] == bucket], max_k)
        for bucket in [
            "missing_train_sequence",
            "cold_or_single_seed",
            "light_behavior_2_3",
            "medium_behavior_4_9",
            "collaborative_rich_10_plus",
        ]
    }
    return {**overall, "user_buckets": by_bucket}


def _aggregate_subset(records: list[dict[str, Any]], max_k: int) -> dict[str, Any]:
    eval_user_count = len(records)
    has_train_records = [record for record in records if record["has_train_sequence"]]
    candidate_counts = [int(record["candidate_count"]) for record in has_train_records]
    generated_candidate_user_count = sum(1 for record in records if record["generated_candidate"])
    hit_user_count = sum(1 for record in records if record["hit_user"])
    recall_sum = sum(float(record["recall_sum"]) for record in records)
    return {
        "eval_user_count": eval_user_count,
        "missing_train_sequence_users": sum(1 for record in records if record["missing_train_sequence"]),
        "has_train_sequence_users": len(has_train_records),
        "train_len_ge2_users": sum(1 for record in records if record["train_len_ge2"]),
        "has_seed_in_graph_users": sum(1 for record in records if record["has_seed_in_graph"]),
        "has_seed_in_graph_rate": _rate(sum(1 for record in records if record["has_seed_in_graph"]), eval_user_count),
        "has_hot_dropped_seed_users": sum(1 for record in records if record["has_hot_dropped_seed"]),
        "users_without_graph_seed_but_hot_dropped_seed": sum(1 for record in records if record["without_graph_seed_but_hot_dropped_seed"]),
        "target_exists_as_any_dst_users": sum(1 for record in records if record["target_exists_as_any_dst"]),
        "target_exists_as_any_dst_rate": _rate(sum(1 for record in records if record["target_exists_as_any_dst"]), eval_user_count),
        "seed_edge_hit_user_count": sum(1 for record in records if record["has_seed_in_graph"]),
        "seed_edge_hit_user_rate": _rate(sum(1 for record in records if record["has_seed_in_graph"]), eval_user_count),
        "generated_candidate_user_count": generated_candidate_user_count,
        "generated_candidate_user_rate": _rate(generated_candidate_user_count, eval_user_count),
        "candidate_user_coverage_count": generated_candidate_user_count,
        "candidate_user_coverage_rate": _rate(generated_candidate_user_count, eval_user_count),
        f"hit_user_count_at_{max_k}": hit_user_count,
        f"hit_rate_at_{max_k}": _rate(hit_user_count, eval_user_count),
        f"recall_at_{max_k}": round(recall_sum / eval_user_count, 6) if eval_user_count else 0.0,
        "candidate_count": _candidate_count_stats(candidate_counts),
    }


def _candidate_count_stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"avg": 0.0, "p50": 0, "p90": 0, "p99": 0, "max": 0}
    return {
        "avg": round(sum(values) / len(values), 6),
        "p50": _percentile(values, 0.50),
        "p90": _percentile(values, 0.90),
        "p99": _percentile(values, 0.99),
        "max": max(values),
    }


def _percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = max(0, min(len(ordered) - 1, math.ceil(pct * len(ordered)) - 1))
    return ordered[index]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def main() -> None:
    args = parse_args()
    report = build_swing_funnel_diagnostic(
        train_sequences_path=Path(args.train_sequences),
        source_dir=Path(args.source_dir),
        split_label_paths={"valid": Path(args.valid_labels), "test": Path(args.test_labels)},
        max_user_items=args.max_user_items,
        per_seed_top_k=args.per_seed_top_k,
        max_k=args.max_k,
    )
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, report)
    print(f"Swing funnel diagnostic status: {report['status']}")
    print(f"Report written to: {output_path}")


if __name__ == "__main__":
    main()
