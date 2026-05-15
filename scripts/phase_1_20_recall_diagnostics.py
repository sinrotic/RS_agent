from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.config import load_config
from rs_core.common.io import read_jsonl
from rs_core.recsys.candidate_merge import (
    _category_candidates_for_user,
    _itemcf_candidates_for_user,
    _limit_candidate_pool,
    _popular_candidates_for_pool,
    _recovery_pool_size,
    _recovery_popular_candidates,
    category_long_tail_candidates_for_user,
    graph_walk_seed_candidates_for_user,
    item_graph_candidates_for_user,
    load_category_candidates,
    load_graph_walk_seed_recall,
    load_item_graph_recall,
    load_itemcf_by_source,
    load_popular_candidates,
    load_semantic_index,
    load_two_tower_index,
    load_two_tower_seed_recall,
    merge_candidates,
    metadata_neighbor_candidates_for_user,
    semantic_candidates_for_user,
    semantic_title_category_expansion_candidates_for_user,
    two_tower_candidates_for_user,
    two_tower_seed_candidates_for_user,
)
from rs_core.recsys.evaluation import evaluate, heldout_positives
from rs_core.recsys.ranking import rank_candidates
from rs_core.recsys.types import MergedCandidate, RecallCandidate, RankingResult
from rs_core.workflow.hybrid_demo import (
    _ensure_inputs,
    _itemcf_seed_items,
    _leave_one_positive_out_sequences,
    _load_item_category,
    _percentile,
    _required_paths,
    _resolve_graph_walk_seed_artifact_path,
    _resolve_graph_walk_seed_manifest_path,
    _resolve_item_graph_artifact_path,
    _resolve_path,
    _resolve_two_tower_artifact_path,
    _resolve_two_tower_seed_artifact_path,
    _resolve_two_tower_seed_manifest_path,
)

DEFAULT_BASELINE_CONFIG = "configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml"
DEFAULT_OUTPUT_DIR = "outputs/recall/phase_1_20_recall_diagnostics"
POOL_SIZES = [50, 100, 200, 500, 1000]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run isolated Phase 1.20 recall diagnostics.")
    parser.add_argument("--baseline-config", default=DEFAULT_BASELINE_CONFIG)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit-users", type=int, default=None)
    args = parser.parse_args()

    baseline_config_path = _resolve_path(args.baseline_config)
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(baseline_config_path)
    clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    views_dir = _resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
    run_id = _run_id(baseline_config_path, args.limit_users)
    baseline_hash = _sha256_file(baseline_config_path)

    inputs = _load_inputs(config, clean_dir, views_dir, args.limit_users)
    common = _common_fields(
        baseline_config_path=baseline_config_path,
        baseline_config_hash=baseline_hash,
        evaluation_mode=inputs["evaluation_mode"],
        split=inputs["split"],
        users_with_holdout=inputs["users_with_holdout"],
        hit_rate_denominator=inputs["hit_rate_denominator"],
        limit_users=args.limit_users,
        run_id=run_id,
        output_dir=output_dir,
    )

    raw_runs = _build_user_diagnostics(config, inputs)
    pool_size_rows = _pool_size_curve(config, inputs, raw_runs, common)
    baseline_pool_size = int(config.get("candidate_pool_size", 100))
    baseline_runs = _finalize_pool(raw_runs, config, baseline_pool_size)
    raw_oracle_rows = _raw_candidate_oracle_rows(baseline_runs, inputs, common)
    miss_rows = _miss_analysis_rows(baseline_runs, inputs, common)
    source_overlap_rows = _source_overlap_rows(baseline_runs, inputs, common)
    slice_rows = _target_metadata_slice_rows(baseline_runs, inputs, common)
    miss_user_opportunity_rows = _miss_user_opportunity_rows(baseline_runs, inputs, common)
    opportunity_gate_summary = _opportunity_gate_summary(miss_user_opportunity_rows, common)

    _write_table(output_dir / "pool_size_curve" / "pool_size_curve.csv", pool_size_rows)
    _write_json(output_dir / "pool_size_curve" / "pool_size_curve.json", {"rows": pool_size_rows})
    _write_table(output_dir / "raw_candidate_oracle" / "raw_candidate_oracle.csv", raw_oracle_rows)
    _write_json(output_dir / "raw_candidate_oracle" / "raw_candidate_oracle.json", {"rows": raw_oracle_rows})
    _write_table(output_dir / "miss_analysis" / "miss_analysis.csv", miss_rows)
    _write_json(output_dir / "miss_analysis" / "miss_analysis.json", {"rows": miss_rows})
    _write_table(output_dir / "miss_analysis" / "source_overlap.csv", source_overlap_rows)
    _write_json(output_dir / "miss_analysis" / "source_overlap.json", {"rows": source_overlap_rows})
    _write_table(output_dir / "target_metadata_slices" / "target_metadata_slices.csv", slice_rows)
    _write_json(output_dir / "target_metadata_slices" / "target_metadata_slices.json", {"rows": slice_rows})
    _write_table(output_dir / "miss_analysis" / "miss_user_opportunities.csv", miss_user_opportunity_rows)
    _write_json(output_dir / "miss_analysis" / "miss_user_opportunities.json", {"rows": miss_user_opportunity_rows})
    _write_json(output_dir / "miss_analysis" / "opportunity_gate_summary.json", opportunity_gate_summary)

    manifest = {
        **common,
        "baseline_candidate_pool_size": baseline_pool_size,
        "pool_sizes": POOL_SIZES,
        "users_total": len(inputs["sequences"]),
        "artifacts": {
            "pool_size_curve_csv": str(output_dir / "pool_size_curve" / "pool_size_curve.csv"),
            "raw_candidate_oracle_csv": str(output_dir / "raw_candidate_oracle" / "raw_candidate_oracle.csv"),
            "miss_analysis_csv": str(output_dir / "miss_analysis" / "miss_analysis.csv"),
            "source_overlap_csv": str(output_dir / "miss_analysis" / "source_overlap.csv"),
            "target_metadata_slices_csv": str(output_dir / "target_metadata_slices" / "target_metadata_slices.csv"),
            "miss_user_opportunities_csv": str(output_dir / "miss_analysis" / "miss_user_opportunities.csv"),
            "opportunity_gate_summary_json": str(output_dir / "miss_analysis" / "opportunity_gate_summary.json"),
        },
    }
    _write_json(output_dir / "run_manifest.json", manifest)
    print(json.dumps({"run_manifest": str(output_dir / "run_manifest.json"), "run_id": run_id}, ensure_ascii=False, indent=2))


def _load_inputs(config: dict[str, Any], clean_dir: Path, views_dir: Path, limit_users: int | None) -> dict[str, Any]:
    paths = _required_paths(clean_dir, views_dir)
    if config.get("semantic_enabled") or config.get("metadata_neighbor_enabled"):
        paths["semantic"] = views_dir / "semantic_recall_inputs.jsonl"
    if config.get("two_tower_enabled"):
        paths["two_tower"] = _resolve_two_tower_artifact_path(config, views_dir)
    if config.get("two_tower_seed_enabled"):
        paths["two_tower_seed"] = _resolve_two_tower_seed_artifact_path(config, views_dir)
        if config.get("fail_on_missing_sidecar"):
            paths["two_tower_seed_manifest"] = _resolve_two_tower_seed_manifest_path(config, views_dir)
    if config.get("item_graph_enabled"):
        paths["item_graph"] = _resolve_item_graph_artifact_path(config, views_dir)
    if config.get("graph_walk_seed_enabled"):
        paths["graph_walk_seed"] = _resolve_graph_walk_seed_artifact_path(config, views_dir)
        paths["graph_walk_seed_manifest"] = _resolve_graph_walk_seed_manifest_path(config, views_dir)
    _ensure_inputs(paths)

    sequences = read_jsonl(paths["sequences"])
    if limit_users is not None:
        sequences = sequences[:limit_users]
    evaluation_mode = str(config.get("evaluation_mode", "valid_test"))
    if evaluation_mode not in {"valid_test", "leave_one_positive_out"}:
        raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode}")

    holdout: list[dict[str, Any]] = []
    if evaluation_mode == "leave_one_positive_out":
        sequences, holdout, _ = _leave_one_positive_out_sequences(sequences)
        split = "leave_one_positive_out"
    else:
        split = "valid_test"
        for split_name in ("valid", "test"):
            path = clean_dir / f"canonical_interactions.{split_name}.jsonl"
            if path.exists():
                holdout.extend(read_jsonl(path))

    positives = heldout_positives(holdout)
    users_with_holdout = sum(1 for sequence in sequences if positives.get(sequence.get("user_id", "")))
    itemcf_seed_items = _itemcf_seed_items(sequences)
    popular = load_popular_candidates(paths["popular"], limit=int(config.get("popular_fallback_count", 50)))
    inputs = {
        "paths": paths,
        "sequences": sequences,
        "holdout": holdout,
        "positives": positives,
        "evaluation_mode": evaluation_mode,
        "split": split,
        "users_with_holdout": users_with_holdout,
        "hit_rate_denominator": "users_with_holdout" if users_with_holdout else "all_demo_users_placeholder",
        "popular": popular,
        "category_top": load_category_candidates(paths["category_top"]),
        "item_category": _load_item_category(paths["category_items"]),
        "itemcf_weak": load_itemcf_by_source(paths["itemcf_weak"], "itemcf_weak", itemcf_seed_items),
        "itemcf_strong": load_itemcf_by_source(paths["itemcf_strong"], "itemcf_strong", itemcf_seed_items),
        "semantic_index": load_semantic_index(paths["semantic"], config.get("semantic_text_fields")) if config.get("semantic_enabled") or config.get("metadata_neighbor_enabled") else {},
        "two_tower_index": load_two_tower_index(paths["two_tower"], config.get("two_tower_text_fields")) if config.get("two_tower_enabled") else {},
        "item_graph": load_item_graph_recall(paths["item_graph"], itemcf_seed_items) if config.get("item_graph_enabled") else {},
        "two_tower_seed": load_two_tower_seed_recall(
            paths["two_tower_seed"],
            itemcf_seed_items,
            paths.get("two_tower_seed_manifest") if config.get("fail_on_missing_sidecar") else None,
        ) if config.get("two_tower_seed_enabled") else {},
        "graph_walk_seed": load_graph_walk_seed_recall(
            paths["graph_walk_seed"],
            itemcf_seed_items,
            paths["graph_walk_seed_manifest"],
        ) if config.get("graph_walk_seed_enabled") else {},
    }
    inputs["target_metadata"] = _target_metadata(inputs)
    return inputs


def _build_user_diagnostics(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for sequence in inputs["sequences"]:
        user_id = sequence.get("user_id", "")
        started_at = perf_counter()
        raw_non_popular = _raw_non_popular_candidates(sequence, config, inputs)
        raw_with_fallback = [*raw_non_popular, *_popular_candidates_for_pool(inputs["popular"], raw_non_popular, config)]
        merged_before_limit = merge_candidates(raw_with_fallback, seen_items=set(sequence.get("recent_item_sequence", [])))
        fallback_used = not raw_non_popular
        if not merged_before_limit and len(raw_with_fallback) > len(raw_non_popular):
            recovered = merge_candidates(_recovery_popular_candidates(raw_with_fallback[len(raw_non_popular):]), seen_items=set())
            merged_before_limit = _limit_candidate_pool(recovered, _recovery_pool_size(config), config)
            fallback_used = True
        has_non_popular = any(source != "popular" for candidate in merged_before_limit for source in candidate.sources)
        fallback_used = fallback_used or not has_non_popular
        rows[user_id] = {
            "sequence": sequence,
            "raw_non_popular_before_fallback": raw_non_popular,
            "raw_with_fallback_before_merge": raw_with_fallback,
            "merged_before_pool_limit": merged_before_limit,
            "fallback_used": fallback_used,
            "candidate_generation_seconds": round(perf_counter() - started_at, 6),
        }
    return rows


def _raw_non_popular_candidates(sequence: dict[str, Any], config: dict[str, Any], inputs: dict[str, Any]) -> list[RecallCandidate]:
    raw: list[RecallCandidate] = []
    raw.extend(_itemcf_candidates_for_user(sequence, inputs["itemcf_weak"], "recent_positive_item_sequence", "itemcf_weak", config, "itemcf_recent_positive_window", "itemcf_weak_per_seed"))
    raw.extend(_itemcf_candidates_for_user(sequence, inputs["itemcf_strong"], "recent_strong_positive_item_sequence", "itemcf_strong", config, "itemcf_recent_strong_window", "itemcf_strong_per_seed"))
    raw.extend(_category_candidates_for_user(sequence, inputs["category_top"], inputs["item_category"], config))
    raw.extend(category_long_tail_candidates_for_user(sequence, inputs["item_category"], inputs["popular"], config))
    raw.extend(semantic_candidates_for_user(sequence, inputs["semantic_index"], config))
    raw.extend(semantic_title_category_expansion_candidates_for_user(sequence, inputs["semantic_index"], config))
    raw.extend(metadata_neighbor_candidates_for_user(sequence, inputs["semantic_index"], config))
    raw.extend(two_tower_candidates_for_user(sequence, inputs["two_tower_index"], config))
    raw.extend(item_graph_candidates_for_user(sequence, inputs["item_graph"], config))
    raw.extend(two_tower_seed_candidates_for_user(sequence, inputs["two_tower_seed"], config))
    raw.extend(graph_walk_seed_candidates_for_user(sequence, inputs["graph_walk_seed"], config))
    return raw


def _finalize_pool(raw_runs: dict[str, dict[str, Any]], config: dict[str, Any], pool_size: int) -> dict[str, dict[str, Any]]:
    pool_config = dict(config)
    pool_config["candidate_pool_size"] = pool_size
    rows = {}
    for user_id, run in raw_runs.items():
        pool = _limit_candidate_pool(run["merged_before_pool_limit"], pool_size, pool_config)
        ranking = rank_candidates(user_id, pool, pool_config)
        rows[user_id] = {**run, "pool_after_limit": pool, "ranking": ranking}
    return rows


def _pool_size_curve(config: dict[str, Any], inputs: dict[str, Any], raw_runs: dict[str, dict[str, Any]], common: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for pool_size in POOL_SIZES:
        pool_config = dict(config)
        pool_config["candidate_pool_size"] = pool_size
        runs = _finalize_pool(raw_runs, config, pool_size)
        candidates_by_user = {user_id: run["pool_after_limit"] for user_id, run in runs.items()}
        rankings_by_user = {user_id: run["ranking"] for user_id, run in runs.items()}
        fallback_users = {user_id for user_id, run in runs.items() if run["fallback_used"]}
        metrics = evaluate(candidates_by_user, rankings_by_user, inputs["holdout"], pool_config, fallback_users).to_dict()
        latencies = [run["candidate_generation_seconds"] for run in runs.values()]
        rows.append({
            **common,
            "pool_size": pool_size,
            "candidate_hit_users": metrics["candidate_hit_users"],
            "candidate_hit_rate_at_pool": metrics["candidate_hit_rate_at_pool"],
            "recall_at_pool": metrics["recall_at_pool"],
            "fallback_rate": metrics["fallback_rate"],
            "candidate_generation_p95_seconds": _percentile(latencies, 0.95),
            "candidate_count_avg": metrics["candidate_count_avg"],
        })
    return rows


def _raw_candidate_oracle_rows(runs: dict[str, dict[str, Any]], inputs: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    stages = ["raw_non_popular_before_fallback", "raw_with_fallback_before_merge", "merged_before_pool_limit", "pool_after_limit"]
    positives = inputs["positives"]
    rows = []
    for stage in stages:
        hit_users = 0
        total_recall = 0.0
        counted = 0
        source_hits: Counter[str] = Counter()
        candidate_counts = []
        for user_id, run in runs.items():
            targets = positives.get(user_id, set())
            if not targets:
                continue
            counted += 1
            ids = _candidate_ids(run[stage])
            hits = ids & targets
            candidate_counts.append(len(ids))
            total_recall += len(hits) / len(targets)
            if hits:
                hit_users += 1
                source_hits.update(_hit_sources(run[stage], hits))
        rows.append({
            **common,
            "stage": stage,
            "hit_users": hit_users,
            "hit_rate": round(hit_users / counted, 6) if counted else 0.0,
            "recall": round(total_recall / counted, 6) if counted else 0.0,
            "candidate_count_avg": round(sum(candidate_counts) / len(candidate_counts), 6) if candidate_counts else 0.0,
            "hit_sources_json": json.dumps(dict(sorted(source_hits.items())), ensure_ascii=False),
        })
    return rows


def _miss_analysis_rows(runs: dict[str, dict[str, Any]], inputs: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    positives = inputs["positives"]
    counters: Counter[str] = Counter()
    users_by_stage: dict[str, list[str]] = defaultdict(list)
    for user_id, run in runs.items():
        targets = positives.get(user_id, set())
        if not targets:
            continue
        raw_non_popular = _candidate_ids(run["raw_non_popular_before_fallback"])
        raw_with_fallback = _candidate_ids(run["raw_with_fallback_before_merge"])
        merged = _candidate_ids(run["merged_before_pool_limit"])
        pool = _candidate_ids(run["pool_after_limit"])
        topk = {item.get("parent_asin") for item in run["ranking"].items if item.get("parent_asin")}
        if targets & pool & topk:
            stage = "topk_hit"
        elif targets & pool:
            stage = "pool_has_target_topk_miss"
        elif targets & merged:
            stage = "raw_has_target_pool_truncated"
        elif targets & raw_with_fallback:
            stage = "raw_with_fallback_has_target_merge_filtered"
        elif targets & raw_non_popular:
            stage = "raw_non_popular_has_target_fallback_or_merge_filtered"
        else:
            stage = "raw_stage_miss"
        counters[stage] += 1
        users_by_stage[stage].append(user_id)
    return [
        {
            **common,
            "miss_stage": stage,
            "user_count": count,
            "user_rate": round(count / common["users_with_holdout"], 6) if common["users_with_holdout"] else 0.0,
            "sample_users_json": json.dumps(users_by_stage[stage][:20], ensure_ascii=False),
        }
        for stage, count in sorted(counters.items())
    ]


def _miss_user_opportunity_rows(runs: dict[str, dict[str, Any]], inputs: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    positives = inputs["positives"]
    rows: list[dict[str, Any]] = []
    for user_id, run in sorted(runs.items()):
        targets = positives.get(user_id, set())
        if not targets:
            continue
        pool = _candidate_ids(run["pool_after_limit"])
        if targets & pool:
            continue
        sequence = run["sequence"]
        metadata_flags = [_metadata_opportunity_flags(inputs["target_metadata"].get(target, {})) for target in targets]
        has_behavior_seed = bool(sequence.get("recent_positive_item_sequence") or sequence.get("recent_strong_positive_item_sequence"))
        rows.append({
            **common,
            "user_id": user_id,
            "target_count": len(targets),
            "targets_json": json.dumps(sorted(targets), ensure_ascii=False),
            "has_metadata_opportunity": any(flags["has_metadata_opportunity"] for flags in metadata_flags),
            "has_co_visit_opportunity": has_behavior_seed,
            "metadata_opportunity_targets": sum(int(flags["has_metadata_opportunity"]) for flags in metadata_flags),
            "co_visit_seed_count": len(set(sequence.get("recent_positive_item_sequence", []) + sequence.get("recent_strong_positive_item_sequence", []))),
            "no_leakage_scope": "diagnostic_only_targets_not_used_for_candidate_generation",
        })
    return rows


def _opportunity_gate_summary(rows: list[dict[str, Any]], common: dict[str, Any]) -> dict[str, Any]:
    miss_users = len(rows)
    metadata_users = sum(int(bool(row["has_metadata_opportunity"])) for row in rows)
    covisit_users = sum(int(bool(row["has_co_visit_opportunity"])) for row in rows)
    thresholds = {
        "min_miss_users": int(common.get("metadata_opportunity_min_miss_users", 1)),
        "min_user_rate": float(common.get("metadata_opportunity_min_user_rate", 0.01)),
    }
    denominator = int(common["users_with_holdout"] or 0)
    metadata_rate = round(metadata_users / denominator, 6) if denominator else 0.0
    covisit_rate = round(covisit_users / denominator, 6) if denominator else 0.0
    return {
        **common,
        "decision_scope": "recall_only_opportunity_gate",
        "miss_users_without_pool_hit": miss_users,
        "metadata_opportunity_users": metadata_users,
        "metadata_opportunity_user_rate": metadata_rate,
        "co_visit_opportunity_users": covisit_users,
        "co_visit_opportunity_user_rate": covisit_rate,
        "thresholds": thresholds,
        "metadata_gate_pass": metadata_users >= thresholds["min_miss_users"] and metadata_rate >= thresholds["min_user_rate"],
        "co_visit_gate_pass": covisit_users >= thresholds["min_miss_users"] and covisit_rate >= thresholds["min_user_rate"],
        "forbidden_promotion_metrics": [
            "hit_rate_at_k",
            "ndcg",
            "mrr",
            "map",
            "topk_hit_rate",
            "topk_hit_users",
            "ranking_gap_pool_has_target",
            "ltr_score",
            "rerank_score",
            "ctr",
            "cvr",
            "gmv",
        ],
        "no_leakage_scope": "holdout targets diagnose opportunity only; candidate generation uses training-visible sequence and item metadata only",
    }


def _metadata_opportunity_flags(metadata: dict[str, Any]) -> dict[str, bool]:
    has_title = bool(metadata.get("has_title"))
    has_category = bool(metadata.get("category"))
    return {"has_metadata_opportunity": has_title or has_category}


def _source_overlap_rows(runs: dict[str, dict[str, Any]], inputs: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    source_candidate_counts: Counter[str] = Counter()
    source_hit_users: Counter[str] = Counter()
    exclusive_hit_users: Counter[str] = Counter()
    pair_counts: Counter[str] = Counter()
    positives = inputs["positives"]
    for user_id, run in runs.items():
        targets = positives.get(user_id, set())
        user_hit_sources: set[str] = set()
        for candidate in run["pool_after_limit"]:
            unique_sources = sorted(set(candidate.sources))
            source_candidate_counts.update(unique_sources)
            for left_index, left in enumerate(unique_sources):
                for right in unique_sources[left_index + 1:]:
                    pair_counts[f"{left}+{right}"] += 1
            if candidate.item_id in targets:
                user_hit_sources.update(unique_sources)
        source_hit_users.update(user_hit_sources)
        if len(user_hit_sources) == 1:
            exclusive_hit_users.update(user_hit_sources)
    sources = sorted(set(source_candidate_counts) | set(source_hit_users) | set(exclusive_hit_users))
    rows = [
        {
            **common,
            "row_type": "source",
            "source": source,
            "candidate_count": source_candidate_counts[source],
            "hit_users": source_hit_users[source],
            "exclusive_hit_users": exclusive_hit_users[source],
            "pair": "",
            "pair_count": "",
        }
        for source in sources
    ]
    rows.extend(
        {
            **common,
            "row_type": "source_pair",
            "source": "",
            "candidate_count": "",
            "hit_users": "",
            "exclusive_hit_users": "",
            "pair": pair,
            "pair_count": count,
        }
        for pair, count in sorted(pair_counts.items())
    )
    return rows


def _target_metadata_slice_rows(runs: dict[str, dict[str, Any]], inputs: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    aggregates: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    positives = inputs["positives"]
    for user_id, run in runs.items():
        targets = positives.get(user_id, set())
        if not targets:
            continue
        raw = _candidate_ids(run["raw_non_popular_before_fallback"])
        pool = _candidate_ids(run["pool_after_limit"])
        topk = {item.get("parent_asin") for item in run["ranking"].items if item.get("parent_asin")}
        sequence_len_bucket = _bucket_sequence_len(run["sequence"].get("sequence_len", len(run["sequence"].get("recent_item_sequence", []))))
        for target in targets:
            metadata = inputs["target_metadata"].get(target, {})
            slices = {
                "category": str(metadata.get("category") or "unknown"),
                "title_coverage": "has_title" if metadata.get("has_title") else "missing_title",
                "popularity_bucket": _bucket_popularity(metadata.get("popular_rank")),
                "user_history_len": sequence_len_bucket,
            }
            for key, value in slices.items():
                aggregate = aggregates[(key, value)]
                aggregate["target_count"] += 1
                aggregate["raw_non_popular_hit"] += int(target in raw)
                aggregate["pool_hit"] += int(target in pool)
                aggregate["topk_hit"] += int(target in topk)
    rows = []
    for (slice_type, slice_value), aggregate in sorted(aggregates.items()):
        target_count = aggregate["target_count"]
        rows.append({
            **common,
            "slice_type": slice_type,
            "slice_value": slice_value,
            "target_count": target_count,
            "raw_non_popular_hit_count": aggregate["raw_non_popular_hit"],
            "raw_non_popular_hit_rate": round(aggregate["raw_non_popular_hit"] / target_count, 6) if target_count else 0.0,
            "pool_hit_count": aggregate["pool_hit"],
            "pool_hit_rate": round(aggregate["pool_hit"] / target_count, 6) if target_count else 0.0,
            "topk_hit_count": aggregate["topk_hit"],
            "topk_hit_rate": round(aggregate["topk_hit"] / target_count, 6) if target_count else 0.0,
        })
    return rows


def _target_metadata(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for item_id, category in inputs["item_category"].items():
        metadata.setdefault(item_id, {})["category"] = category
    semantic_index = inputs.get("semantic_index", {})
    if isinstance(semantic_index, dict):
        for item_id, row in semantic_index.items():
            metadata.setdefault(item_id, {}).update({
                "category": row.get("main_category") or row.get("category") or metadata.get(item_id, {}).get("category", ""),
                "has_title": bool(row.get("title") or row.get("title_clean")),
            })
    for rank, candidate in enumerate(inputs["popular"], start=1):
        metadata.setdefault(candidate.item_id, {})["popular_rank"] = rank
    return metadata


def _candidate_ids(candidates: list[RecallCandidate] | list[MergedCandidate]) -> set[str]:
    return {candidate.item_id for candidate in candidates if candidate.item_id}


def _hit_sources(candidates: list[RecallCandidate] | list[MergedCandidate], hits: set[str]) -> Counter[str]:
    sources: Counter[str] = Counter()
    for candidate in candidates:
        if candidate.item_id not in hits:
            continue
        if isinstance(candidate, MergedCandidate):
            sources.update(candidate.sources)
        else:
            sources.update([candidate.source])
    return sources


def _common_fields(
    baseline_config_path: Path,
    baseline_config_hash: str,
    evaluation_mode: str,
    split: str,
    users_with_holdout: int,
    hit_rate_denominator: str,
    limit_users: int | None,
    run_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "baseline_config_path": str(baseline_config_path),
        "baseline_config_hash": baseline_config_hash,
        "evaluation_mode": evaluation_mode,
        "split": split,
        "users_with_holdout": users_with_holdout,
        "hit_rate_denominator": hit_rate_denominator,
        "limit_users": limit_users,
        "run_id": run_id,
        "output_dir": str(output_dir),
    }


def _write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_id(config_path: Path, limit_users: int | None) -> str:
    payload = f"{config_path}|{_sha256_file(config_path)}|{limit_users}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _bucket_sequence_len(value: Any) -> str:
    try:
        length = int(value)
    except (TypeError, ValueError):
        length = 0
    if length < 5:
        return "lt_5"
    if length < 20:
        return "5_19"
    if length < 50:
        return "20_49"
    return "gte_50"


def _bucket_popularity(rank: Any) -> str:
    if rank is None:
        return "not_in_popular_topn"
    rank_int = int(rank)
    if rank_int <= 10:
        return "top_10"
    if rank_int <= 50:
        return "top_50"
    return "beyond_50"


if __name__ == "__main__":
    main()
