from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict

import numpy as np
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.config import load_config
from rs_core.common.io import write_jsonl
from rs_core.online.recall.candidate_merge import (
    _category_candidates_for_user,
    _itemcf_candidates_for_user,
    _limit_candidate_pool,
    _popular_candidates_for_pool,
    _recovery_pool_size,
    _recovery_popular_candidates,
    category_long_tail_candidates_for_user,
    graph_walk_seed_candidates_for_user,
    item_graph_candidates_for_user,
    load_graph_walk_seed_recall,
    load_item_graph_recall,
    merge_candidates,
    metadata_neighbor_candidates_for_user,
    semantic_candidates_for_user,
    semantic_title_category_expansion_candidates_for_user,
    two_tower_candidates_for_user,
    two_tower_seed_candidates_for_user,
)
from rs_core.offline.evaluation.ranking import evaluate, frozen_candidate_artifact
from rs_core.online.ranking import rank_candidates
from rs_core.common.recsys_types import RecallCandidate
from rs_lab.experiments.recall import phase_1_20_recall_diagnostics as diagnostics

DEFAULT_CONFIG = "configs/recall/phase_1_21/phase_1_21_recall_coverage_baseline.yaml"
DEFAULT_OUTPUT_ROOT = "outputs/recall/phase_1_21_recall_coverage"
HASH_RULE = "sha256 of sorted holdout user_id list joined by newline"
REQUIRED_LIMIT_USERS = 500
REQUIRED_USERS_WITH_HOLDOUT = 138
REQUIRED_EVALUATION_MODE = "valid_test"
REQUIRED_DENOMINATOR = "users_with_holdout"
SOURCE_CONTRACT_VERSION = "phase_1_21_source_contract_v1"
METRICS_CONTRACT_VERSION = "phase_1_21_metrics_contract_v1"
SOURCE_FAMILY_BENCHMARK_CONTRACT_VERSION = "source_family_observation_benchmark_v1"
DEDICATED_ABLATION_CONTRACT_VERSION = "dedicated_recall_ablation_evidence_v1"
FROZEN_PROMOTION_EVIDENCE_CONTRACT_VERSION = "frozen_recall_promotion_evidence_v1"
NO_LEAKAGE_CONTRACT = (
    "miss_targets.csv and holdout targets are diagnostics/evaluation only; never use target ids for "
    "candidate generation, query construction, target-driven source index construction/filtering, "
    "candidate whitelist construction, or parameter selection. Static catalog item metadata may be "
    "indexed as train-visible item features when it is not derived from holdout labels."
)
SOURCE_CONTRACT = {
    "schema_version": SOURCE_CONTRACT_VERSION,
    "source_tag": "lower_snake_case stable tag, unique per recall source, never reused for ranking/rerank routes",
    "candidate_fields": ["item_id", "source", "score", "metadata"],
    "metadata_fields": ["reason", "seed_item_id", "source_score", "source_rank"],
    "merged_fields": ["sources", "source_scores", "metadata"],
    "dedup_rule": "merge_candidates keeps all source tags in sources and max per-source score in source_scores",
    "allowed_new_source_tags": [
        "semantic_title_category_expansion",
        "co_visit_fallback_repair",
        "category_long_tail_recall",
        "metadata_neighbor_recall",
        "usercf_recall",
        "swing_recall",
        "session_transition_recall",
        "implicit_svd_recall",
        "als_mf_recall",
        "bpr_mf_recall",
        "lightfm_recall",
        "multi_interest_recall",
    ],
}
REGISTRY_ALLOWED_OBSERVATION_METRICS = [
    "empty_candidate_rate",
    "empty_user_count",
    "candidate_count_p50",
    "candidate_count_p90",
    "candidate_count_max",
    "candidate_hit_users",
    "candidate_hit_rate",
    "candidate_recall_at_candidate_k",
    "candidate_hit_at_candidate_k",
    "catalog_coverage",
    "source_coverage",
    "source_marginal_candidate_hit",
    "source_overlap_jaccard",
    "source_pair_overlap",
    "fallback_trigger_rate",
    "artifact_completeness",
    "reproducibility",
    "leakage_risk",
]
FORBIDDEN_RECALL_REGISTRY_METRICS = [
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
]
METRICS_CONTRACT = {
    "schema_version": METRICS_CONTRACT_VERSION,
    "required_fields": [
        "raw_coverage_hit_users",
        "raw_coverage_hit_rate",
        "candidate_hit_users",
        "candidate_hit_rate",
        "topk_hit_users",
        "topk_hit_rate",
        "exclusive_hit_users",
        "source_overlap",
        "baseline_displacement_users",
        "candidate_volume_avg",
        "runtime_seconds",
        "fallback_error_count",
        "holdout_user_ids_hash",
    ],
    "denominator": REQUIRED_DENOMINATOR,
    "limit_users": REQUIRED_LIMIT_USERS,
    "evaluation_mode": REQUIRED_EVALUATION_MODE,
}
SOURCE_FAMILY_BENCHMARKS = [
    {
        "benchmark_id": "popular_category_observation",
        "display_name": "popular/category",
        "method_family": "popular_rule",
        "source_group": "popular_rule",
        "source_names": ["popular", "category"],
        "config_patch": {},
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "itemcf_covisit_observation",
        "display_name": "ItemCF/co-visit",
        "method_family": "collaborative_filtering",
        "source_group": "cf_behavior",
        "source_names": ["itemcf_weak", "itemcf_strong", "co_visit_fallback_repair"],
        "config_patch": lambda: _co_visit_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "semantic_title_category_observation",
        "display_name": "semantic/title-category",
        "method_family": "content_semantic",
        "source_group": "content_semantic",
        "source_names": ["semantic", "semantic_title_category_expansion", "category_long_tail_recall"],
        "config_patch": lambda: _semantic_patch() | _category_long_tail_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "graph_observation",
        "display_name": "graph",
        "method_family": "graph_recall",
        "source_group": "graph",
        "source_names": ["item_graph", "graph_walk_seed"],
        "config_patch": lambda: _graph_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "vector_two_tower_observation",
        "display_name": "vector/two-tower",
        "method_family": "vector_tower",
        "source_group": "vector_tower",
        "source_names": ["two_tower", "youtube_dnn"],
        "config_patch": lambda: _vector_two_tower_patch(),
        "artifact_source": "offline_vector_two_tower_registry_artifact",
    },
    {
        "benchmark_id": "usercf_observation",
        "display_name": "UserCF",
        "method_family": "collaborative_filtering",
        "source_group": "cf_behavior",
        "source_names": ["usercf_recall"],
        "config_patch": lambda: _usercf_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "swing_observation",
        "display_name": "Swing",
        "method_family": "collaborative_filtering",
        "source_group": "cf_behavior",
        "source_names": ["swing_recall"],
        "config_patch": lambda: _swing_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "sequence_transition_observation",
        "display_name": "session/transition",
        "method_family": "sequence_interest",
        "source_group": "sequence_interest",
        "source_names": ["session_transition_recall"],
        "config_patch": lambda: _session_transition_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "implicit_svd_observation",
        "display_name": "implicit SVD MF",
        "method_family": "matrix_factorization",
        "source_group": "cf_behavior",
        "source_names": ["implicit_svd_recall"],
        "config_patch": lambda: _implicit_svd_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
    {
        "benchmark_id": "als_mf_observation",
        "display_name": "ALS MF",
        "method_family": "matrix_factorization",
        "source_group": "cf_behavior",
        "source_names": ["als_mf_recall"],
        "config_patch": lambda: _als_mf_dependency_gate_patch(),
        "artifact_source": "dependency_gate_registry_artifact",
        "dependency_gate": {"required_modules": ["scipy", "implicit"], "deferred_method": "implicit_als"},
    },
    {
        "benchmark_id": "bpr_mf_observation",
        "display_name": "BPR MF",
        "method_family": "matrix_factorization",
        "source_group": "cf_behavior",
        "source_names": ["bpr_mf_recall"],
        "config_patch": lambda: _bpr_mf_dependency_gate_patch(),
        "artifact_source": "dependency_gate_registry_artifact",
        "dependency_gate": {"required_modules": ["scipy", "implicit"], "deferred_method": "implicit_bpr"},
    },
    {
        "benchmark_id": "lightfm_mf_observation",
        "display_name": "LightFM MF",
        "method_family": "matrix_factorization",
        "source_group": "cf_behavior",
        "source_names": ["lightfm_recall"],
        "config_patch": lambda: _lightfm_mf_dependency_gate_patch(),
        "artifact_source": "dependency_gate_registry_artifact",
        "dependency_gate": {"required_modules": ["scipy", "lightfm"], "deferred_method": "lightfm_warp_bpr"},
    },
    {
        "benchmark_id": "sequence_multi_interest_observation",
        "display_name": "sequence/multi-interest",
        "method_family": "sequence_interest",
        "source_group": "sequence_interest",
        "source_names": ["multi_interest_recall"],
        "config_patch": lambda: _multi_interest_patch(),
        "artifact_source": "run_hybrid_demo_valid_test_recall_registry_artifact",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run isolated Phase 1.21 recall coverage baseline/audit experiments.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--mode", choices=["baseline", "audit", "ablation", "pool-curve", "source-aware"], required=True)
    parser.add_argument("--limit-users", type=int, required=True)
    parser.add_argument("--holdout-user-ids", default=None)
    args = parser.parse_args()

    config_path = _resolve_path(args.config)
    phase_config = load_config(config_path)
    baseline_config_path = _resolve_path(phase_config.get("baseline_config_path", "configs/ranking/phase_1_15/phase_1_15_frozen_youtubednn_pool100.yaml"))
    output_dir = _resolve_path(args.output_dir or f"{DEFAULT_OUTPUT_ROOT}/{args.mode}")
    _assert_phase_output_dir(output_dir)
    _assert_limit_users(args.limit_users, phase_config)

    config = load_config(baseline_config_path)
    _assert_disabled_ranking_routes(config)
    _assert_phase_source_features_safe(phase_config)

    clean_dir = diagnostics._resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    views_dir = diagnostics._resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
    inputs = diagnostics._load_inputs(config, clean_dir, views_dir, args.limit_users)
    _attach_phase_sources(inputs, phase_config)
    _assert_denominator(inputs, phase_config)

    baseline_hash = diagnostics._sha256_file(baseline_config_path)
    run_id = _run_id(args.mode, baseline_config_path, baseline_hash, args.limit_users)
    holdout_user_ids = _holdout_user_ids(inputs)
    holdout_hash = _holdout_user_ids_hash(holdout_user_ids)
    holdout_payload = {"hash_rule": HASH_RULE, "holdout_user_ids_hash": holdout_hash, "holdout_user_ids": holdout_user_ids}

    common = diagnostics._common_fields(
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
    common["phase_config_path"] = str(config_path)
    common["phase_source_features"] = _phase_source_config(phase_config)
    common["holdout_user_ids_hash"] = holdout_hash
    common["holdout_user_ids_hash_rule"] = HASH_RULE
    common["source_contract"] = SOURCE_CONTRACT
    common["metrics_contract"] = METRICS_CONTRACT
    common["no_leakage_contract"] = NO_LEAKAGE_CONTRACT
    common["ranking_rerank_disabled_checks"] = _ranking_rerank_disabled_checks()

    experiment_config = _experiment_config(config, phase_config)
    raw_runs = _build_user_diagnostics(experiment_config, inputs)
    baseline_pool_size = int(experiment_config.get("candidate_pool_size", config.get("candidate_pool_size", 100)))
    baseline_runs = _finalize_pool(raw_runs, experiment_config, baseline_pool_size)

    if args.mode == "baseline":
        _run_baseline(output_dir, common, experiment_config, baseline_pool_size, raw_runs, baseline_runs, inputs, holdout_payload)
        return

    if not args.holdout_user_ids:
        raise ValueError(f"--holdout-user-ids is required in {args.mode} mode")
    loaded_holdout_path, loaded_hash = _validate_loaded_holdout(args.holdout_user_ids, holdout_user_ids, holdout_hash)
    if args.mode == "audit":
        _run_audit(output_dir, common, experiment_config, baseline_pool_size, baseline_runs, inputs, loaded_holdout_path, loaded_hash)
    elif args.mode == "ablation":
        _run_ablation(output_dir, common, config, phase_config, inputs, loaded_holdout_path, loaded_hash)
    elif args.mode == "source-aware":
        _run_source_aware(output_dir, common, config, phase_config, inputs, loaded_holdout_path, loaded_hash)
    else:
        _run_pool_curve(output_dir, common, config, phase_config, inputs, loaded_holdout_path, loaded_hash)


def _run_baseline(
    output_dir: Path,
    common: dict[str, Any],
    config: dict[str, Any],
    baseline_pool_size: int,
    raw_runs: dict[str, dict[str, Any]],
    baseline_runs: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
    holdout_payload: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pool_rows = diagnostics._pool_size_curve(config, inputs, raw_runs, common)
    metrics = _metrics_for_runs(config, baseline_runs, inputs)
    raw_oracle_rows = diagnostics._raw_candidate_oracle_rows(baseline_runs, inputs, common)
    source_coverage_rows = _source_overlap_rows(baseline_runs, inputs, common)
    miss_summary_rows = diagnostics._miss_analysis_rows(baseline_runs, inputs, common)
    frozen_candidate_rows = _frozen_candidate_export_rows(baseline_runs)

    _write_json(output_dir / "holdout_user_ids.json", holdout_payload)
    metrics_path = output_dir / "metrics.json"
    frozen_candidates_path = output_dir / "frozen_candidates.jsonl"
    frozen_candidate_artifact_path = output_dir / "frozen_candidate_artifact.json"
    _write_json(metrics_path, metrics)
    write_jsonl(frozen_candidates_path, frozen_candidate_rows)
    _write_json(frozen_candidate_artifact_path, frozen_candidate_artifact(frozen_candidate_rows))
    _write_csv(output_dir / "pool_curve.csv", pool_rows)
    _write_csv(output_dir / "source_coverage.csv", source_coverage_rows)
    _write_csv(output_dir / "raw_candidate_oracle.csv", raw_oracle_rows)
    _write_csv(output_dir / "miss_stage_summary.csv", miss_summary_rows)
    source_family_benchmarks_path = output_dir / "source_family_observation_benchmarks.json"
    _write_json(
        source_family_benchmarks_path,
        _source_family_observation_benchmark_artifact(common, config, baseline_pool_size, metrics_path),
    )

    manifest_path = output_dir / "manifest.json"
    promotion_evidence_manifest_path = output_dir / "frozen_promotion_evidence_manifest.json"
    manifest = {
        **common,
        "mode": "baseline",
        "baseline_candidate_pool_size": baseline_pool_size,
        "users_total": len(inputs["sequences"]),
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "metrics_contract_version": METRICS_CONTRACT_VERSION,
        "raw_stage_miss": _miss_stage_count(miss_summary_rows, "raw_stage_miss"),
        "raw_pre_pool_hit_users": _stage_hit_users(raw_oracle_rows, "merged_before_pool_limit"),
        "metrics_path": str(metrics_path),
        "holdout_user_ids_path": str(output_dir / "holdout_user_ids.json"),
        "source_family_benchmark_contract_version": SOURCE_FAMILY_BENCHMARK_CONTRACT_VERSION,
        "source_family_observation_benchmarks_path": str(source_family_benchmarks_path),
        "frozen_candidates_path": str(frozen_candidates_path),
        "frozen_candidate_artifact_path": str(frozen_candidate_artifact_path),
        "frozen_promotion_evidence_manifest_path": str(promotion_evidence_manifest_path),
        "artifacts": {
            "pool_curve_csv": str(output_dir / "pool_curve.csv"),
            "source_coverage_csv": str(output_dir / "source_coverage.csv"),
            "raw_candidate_oracle_csv": str(output_dir / "raw_candidate_oracle.csv"),
            "miss_stage_summary_csv": str(output_dir / "miss_stage_summary.csv"),
            "source_family_observation_benchmarks_json": str(source_family_benchmarks_path),
            "frozen_candidates_jsonl": str(frozen_candidates_path),
            "frozen_candidate_artifact_json": str(frozen_candidate_artifact_path),
            "frozen_promotion_evidence_manifest_json": str(promotion_evidence_manifest_path),
        },
    }
    _write_json(manifest_path, manifest)
    _write_json(
        promotion_evidence_manifest_path,
        _frozen_observation_evidence_manifest(common, manifest, metrics_path, frozen_candidates_path, frozen_candidate_artifact_path),
    )
    print(json.dumps({"manifest": str(output_dir / "manifest.json"), "holdout_user_ids_hash": common["holdout_user_ids_hash"]}, ensure_ascii=False, indent=2))


def _frozen_candidate_export_rows(runs: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for user_id in sorted(runs):
        for rank, candidate in enumerate(runs[user_id]["pool_after_limit"], start=1):
            rows.append({
                "user_id": user_id,
                "candidate_rank": rank,
                "item_id": candidate.item_id,
                "sources": list(candidate.sources),
                "source_scores": {source: float(score) for source, score in sorted(candidate.source_scores.items())},
                "category": candidate.category,
                "metadata": candidate.metadata,
            })
    return rows



def _frozen_observation_evidence_manifest(
    common: dict[str, Any],
    manifest: dict[str, Any],
    metrics_path: Path,
    frozen_candidates_path: Path,
    frozen_candidate_artifact_path: Path,
) -> dict[str, Any]:
    required_paths = {
        "frozen_candidates_path": frozen_candidates_path,
        "metrics_path": metrics_path,
        "source_coverage_path": Path(manifest["artifacts"]["source_coverage_csv"]),
        "pool_curve_path": Path(manifest["artifacts"]["pool_curve_csv"]),
        "ablation_report_path": None,
        "overlap_report_path": None,
        "latency_report_path": None,
        "fallback_report_path": None,
    }
    checks = {name: _evidence_artifact_check(path) for name, path in required_paths.items()}
    missing = [name for name, check in checks.items() if not check["available"]]
    return {
        "schema_version": FROZEN_PROMOTION_EVIDENCE_CONTRACT_VERSION,
        "decision_scope": "recall_only",
        "gate_status": "INCONCLUSIVE_MISSING_ARTIFACT" if missing else "READY_FOR_PROMOTION_REVIEW",
        "missing_required_artifacts": missing,
        "next_action": "Attach ablation, overlap, latency, and fallback evidence before promotion review." if missing else "Review complete recall-only promotion evidence.",
        "baseline_candidate_pool_size": manifest["baseline_candidate_pool_size"],
        "loaded_baseline_holdout_user_ids_hash": common["holdout_user_ids_hash"],
        "holdout_user_ids_hash_rule": HASH_RULE,
        "evaluation_contract": {
            "evaluation_mode": common["evaluation_mode"],
            "split": common["split"],
            "limit_users": common["limit_users"],
            "users_with_holdout": common["users_with_holdout"],
            "hit_rate_denominator": common["hit_rate_denominator"],
        },
        "source_artifact_paths": {name: (str(path) if path is not None else None) for name, path in required_paths.items()},
        "frozen_candidate_artifact_path": str(frozen_candidate_artifact_path),
        "frozen_candidate_artifact_sha256": diagnostics._sha256_file(frozen_candidate_artifact_path),
        "required_artifacts": checks,
        "forbidden_metrics": FORBIDDEN_RECALL_REGISTRY_METRICS,
        "no_leakage_contract": NO_LEAKAGE_CONTRACT,
    }



def _source_family_observation_benchmark_artifact(
    common: dict[str, Any],
    config: dict[str, Any],
    baseline_pool_size: int,
    metrics_path: Path,
) -> dict[str, Any]:
    benchmarks = []
    for family in SOURCE_FAMILY_BENCHMARKS:
        patch = family["config_patch"]() if callable(family["config_patch"]) else dict(family["config_patch"])
        execution_state = _source_family_execution_state(family, common, baseline_pool_size, metrics_path)
        benchmarks.append({
            "benchmark_id": family["benchmark_id"],
            "display_name": family["display_name"],
            "method_family": family["method_family"],
            "source_group": family["source_group"],
            "source_names": family["source_names"],
            "lane": "observation",
            "scope_contract": "recall_only",
            "evaluation_contract": f"valid_test_users_with_holdout_pool{baseline_pool_size}",
            "candidate_pool_size": baseline_pool_size,
            "input_signature": {
                "evaluation_mode": common["evaluation_mode"],
                "split": common["split"],
                "users_total": common["limit_users"],
                "users_with_holdout": common["users_with_holdout"],
                "hit_rate_denominator": common["hit_rate_denominator"],
                "baseline_config_hash": common["baseline_config_hash"],
                "holdout_user_ids_hash": common["holdout_user_ids_hash"],
            },
            "config_patch": patch,
            "registration_template": {
                "experiment_id": family["benchmark_id"],
                "method_family": family["method_family"],
                "source_group": family["source_group"],
                "source_name": family["source_names"][0],
                "lane": "observation",
                "scope_contract": "recall_only",
                "candidate_pool_size": baseline_pool_size,
                "gate_status": "PASS_OBSERVATION_ONLY" if execution_state["execution_status"] == "EXECUTED_PASS" else "INCONCLUSIVE_MISSING_ARTIFACT",
                "rollback_baseline": False,
                "owner_agent": "worker-benchmark",
                "allowed_metrics": REGISTRY_ALLOWED_OBSERVATION_METRICS,
                "forbidden_metrics": FORBIDDEN_RECALL_REGISTRY_METRICS,
            },
            "artifact_source": family["artifact_source"],
            **execution_state,
        })
    return {
        "schema_version": SOURCE_FAMILY_BENCHMARK_CONTRACT_VERSION,
        "source_registry_path": ".omc/recall/registry/source_group_registry.yaml",
        "recall_registry_schema_path": ".omc/recall/schema/recall_experiment_registry.schema.yaml",
        "baseline_metrics_path": str(metrics_path),
        "baseline_strategy_name": config.get("strategy_name", "phase_1_21_recall_coverage_baseline"),
        "allowed_metrics": REGISTRY_ALLOWED_OBSERVATION_METRICS,
        "forbidden_metrics": FORBIDDEN_RECALL_REGISTRY_METRICS,
        "benchmarks": benchmarks,
    }


def _source_family_execution_state(
    family: dict[str, Any],
    common: dict[str, Any],
    baseline_pool_size: int,
    metrics_path: Path,
) -> dict[str, Any]:
    output_dir = metrics_path.parent
    benchmark_id = family["benchmark_id"]
    execution_command = _source_family_execution_command(benchmark_id, baseline_pool_size)
    if benchmark_id in _executed_source_family_benchmark_ids(common):
        return {
            "execution_status": "EXECUTED_PASS",
            "evidence_level": "same_contract_verified",
            "execution_command": execution_command,
            "output_dir": str(output_dir),
            "metrics_path": str(metrics_path),
            "metrics_sha256": diagnostics._sha256_file(metrics_path),
            "failure_reason": "",
            "invalidation_reason": "",
            "next_action": "eligible_for_registry_observation_review",
        }
    dependency_gate = family.get("dependency_gate")
    if dependency_gate:
        return _blocked_missing_dependency_state(dependency_gate, output_dir / benchmark_id, execution_command)
    if benchmark_id in {"popular_category_observation", "itemcf_covisit_observation", "semantic_title_category_observation", "vector_two_tower_observation", "usercf_observation", "swing_observation", "sequence_transition_observation", "implicit_svd_observation", "sequence_multi_interest_observation", "graph_observation"}:
        return {
            "execution_status": "READY_TO_RUN",
            "evidence_level": "needs_rerun",
            "execution_command": execution_command,
            "output_dir": str(output_dir / benchmark_id),
            "metrics_path": "",
            "metrics_sha256": "",
            "failure_reason": "",
            "invalidation_reason": "not_executed_no_metrics_artifact",
            "next_action": "run_observation_benchmark_and_attach_metrics_artifact",
        }
    return {
        "execution_status": "TEMPLATE_ONLY",
        "evidence_level": "needs_rerun",
        "execution_command": execution_command,
        "output_dir": str(output_dir / benchmark_id),
        "metrics_path": "",
        "metrics_sha256": "",
        "failure_reason": "missing_source_family_artifact",
        "invalidation_reason": "not_executed_no_metrics_artifact",
        "next_action": "create_required_source_artifact_before_execution",
    }


def _executed_source_family_benchmark_ids(common: dict[str, Any]) -> set[str]:
    phase_source_features = common.get("phase_source_features") or {}
    if not phase_source_features:
        return {"popular_category_observation"}
    executed = set()
    if phase_source_features.get("co_visit_fallback_repair_enabled"):
        executed.add("itemcf_covisit_observation")
    semantic_config = phase_source_features.get("semantic_title_category_expansion")
    if isinstance(semantic_config, dict) and semantic_config.get("enabled"):
        executed.add("semantic_title_category_observation")
    if phase_source_features.get("category_long_tail_enabled"):
        executed.add("semantic_title_category_observation")
    if phase_source_features.get("usercf_enabled"):
        executed.add("usercf_observation")
    if phase_source_features.get("swing_enabled"):
        executed.add("swing_observation")
    if phase_source_features.get("session_transition_enabled"):
        executed.add("sequence_transition_observation")
    if phase_source_features.get("implicit_svd_enabled"):
        executed.add("implicit_svd_observation")
    if phase_source_features.get("als_mf_enabled"):
        executed.add("als_mf_observation")
    if phase_source_features.get("bpr_mf_enabled"):
        executed.add("bpr_mf_observation")
    if phase_source_features.get("lightfm_enabled"):
        executed.add("lightfm_mf_observation")
    if phase_source_features.get("two_tower_enabled"):
        executed.add("vector_two_tower_observation")
    if phase_source_features.get("item_graph_enabled") or phase_source_features.get("graph_walk_seed_enabled"):
        executed.add("graph_observation")
    if phase_source_features.get("multi_interest_enabled"):
        executed.add("sequence_multi_interest_observation")
    return executed


def _blocked_missing_dependency_state(dependency_gate: dict[str, Any], output_dir: Path, execution_command: str) -> dict[str, Any]:
    required_modules = list(dependency_gate.get("required_modules", []))
    missing_modules = [module for module in required_modules if importlib.util.find_spec(module) is None]
    if not missing_modules:
        return {
            "execution_status": "READY_TO_RUN",
            "evidence_level": "dependency_gate_passed_needs_rerun",
            "execution_command": execution_command,
            "output_dir": str(output_dir),
            "metrics_path": "",
            "metrics_sha256": "",
            "failure_reason": "",
            "invalidation_reason": "not_executed_no_metrics_artifact",
            "next_action": "run_observation_benchmark_and_attach_metrics_artifact",
            "dependency_gate": {**dependency_gate, "gate_status": "dependency_available", "missing_modules": []},
        }
    return {
        "execution_status": "blocked_missing_dependency",
        "evidence_level": "dependency_gate",
        "execution_command": execution_command,
        "output_dir": str(output_dir),
        "metrics_path": "",
        "metrics_sha256": "",
        "failure_reason": "missing_dependency:" + ",".join(missing_modules),
        "invalidation_reason": "not_executed_missing_dependency",
        "next_action": "defer_until_dependency_available",
        "dependency_gate": {**dependency_gate, "gate_status": "blocked_missing_dependency", "missing_modules": missing_modules},
    }


def _source_family_execution_command(benchmark_id: str, baseline_pool_size: int) -> str:
    config_by_benchmark = {
        "popular_category_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_baseline.yaml",
        "itemcf_covisit_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml",
        "semantic_title_category_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_semantic_title_category.yaml",
        "graph_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_graph.yaml",
        "usercf_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml",
        "swing_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml",
        "sequence_transition_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml",
        "implicit_svd_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_behavior_untried.yaml",
        "als_mf_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml",
        "bpr_mf_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml",
        "lightfm_mf_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_mf.yaml",
        "vector_two_tower_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_vector.yaml",
        "sequence_multi_interest_observation": "configs/recall/phase_1_21/phase_1_21_recall_coverage_sequence.yaml",
    }
    config_path = config_by_benchmark.get(benchmark_id, "configs/recall/phase_1_21/phase_1_21_recall_coverage_baseline.yaml")
    return (
        "python rs_lab/experiments/recall/phase_1_21_recall_coverage_experiments.py "
        f"--config {config_path} "
        f"--output-dir outputs/recall/phase_1_21_recall_coverage/source_family/{benchmark_id}_pool{baseline_pool_size} "
        "--mode baseline --limit-users 500"
    )


def _run_ablation(
    output_dir: Path,
    common: dict[str, Any],
    config: dict[str, Any],
    phase_config: dict[str, Any],
    inputs: dict[str, Any],
    loaded_holdout_path: Path,
    loaded_hash: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    ablation_base_phase_config = _ablation_base_phase_config(phase_config)
    baseline_config = _experiment_config(config, ablation_base_phase_config)
    baseline_raw = _build_user_diagnostics(baseline_config, inputs)
    baseline_runs = _finalize_pool(baseline_raw, baseline_config, int(baseline_config.get("candidate_pool_size", 100)))
    baseline_state = _run_state(baseline_runs, inputs)
    summary_rows: list[dict[str, Any]] = []
    exclusive_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    displacement_rows: list[dict[str, Any]] = []
    fallback_rows: list[dict[str, Any]] = []
    latency_rows: list[dict[str, Any]] = []
    experiments = _ablation_matrix(phase_config)
    for experiment_name, patch in experiments:
        experiment_phase_config = {**ablation_base_phase_config, **patch}
        experiment_inputs = dict(inputs)
        _attach_phase_sources(experiment_inputs, experiment_phase_config)
        experiment_config = _experiment_config(config, experiment_phase_config)
        raw_runs = _build_user_diagnostics(experiment_config, experiment_inputs)
        runs = _finalize_pool(raw_runs, experiment_config, int(experiment_config.get("candidate_pool_size", 100)))
        state = _run_state(runs, experiment_inputs)
        experiment_common = {**common, "experiment_name": experiment_name, "phase_source_features": _phase_source_config(experiment_phase_config)}
        experiment_dir = output_dir / experiment_name
        experiment_dir.mkdir(parents=True, exist_ok=True)
        metrics = _metrics_for_runs(experiment_config, runs, experiment_inputs)
        source_rows = _source_overlap_rows(runs, experiment_inputs, experiment_common)
        raw_rows = diagnostics._raw_candidate_oracle_rows(runs, experiment_inputs, experiment_common)
        _write_json(experiment_dir / "metrics.json", metrics)
        _write_csv(experiment_dir / "source_coverage.csv", source_rows)
        _write_csv(experiment_dir / "raw_candidate_oracle.csv", raw_rows)
        _write_json(experiment_dir / "manifest.json", {
            **experiment_common,
            "mode": "ablation",
            "loaded_baseline_holdout_user_ids_path": str(loaded_holdout_path),
            "loaded_baseline_holdout_user_ids_hash": loaded_hash,
            "same_holdout_user_ids_verified": True,
            "metrics_path": str(experiment_dir / "metrics.json"),
            "artifacts": {
                "source_coverage_csv": str(experiment_dir / "source_coverage.csv"),
                "raw_candidate_oracle_csv": str(experiment_dir / "raw_candidate_oracle.csv"),
            },
        })
        summary_rows.append(_summary_metrics_row(experiment_name, common, metrics, state, baseline_state))
        exclusive_rows.extend(_exclusive_hit_rows(experiment_name, runs, experiment_inputs, baseline_state))
        overlap_rows.extend(_overlap_matrix_rows(experiment_name, source_rows))
        displacement_rows.extend(_baseline_displacement_rows(experiment_name, state, baseline_state))
        fallback_rows.append({"experiment_name": experiment_name, "fallback_users": len(state["fallback_users"]), "fallback_rate": metrics.get("fallback_rate", 0.0)})
        latencies = [run["candidate_generation_seconds"] for run in runs.values()]
        latency_rows.append({
            "experiment_name": experiment_name,
            "candidate_generation_avg_seconds": round(sum(latencies) / len(latencies), 6) if latencies else 0.0,
            "candidate_generation_p50_seconds": diagnostics._percentile(latencies, 0.5),
            "candidate_generation_p95_seconds": diagnostics._percentile(latencies, 0.95),
            "candidate_generation_max_seconds": max(latencies) if latencies else 0.0,
        })
    _write_csv(output_dir / "summary_metrics.csv", summary_rows)
    _write_csv(output_dir / "exclusive_hits.csv", exclusive_rows)
    _write_csv(output_dir / "source_overlap_matrix.csv", overlap_rows)
    _write_csv(output_dir / "baseline_displacement_report.csv", displacement_rows)
    _write_csv(output_dir / "latency_report.csv", latency_rows)
    _write_json(output_dir / "fallback_stability_report.json", {"rows": fallback_rows, "holdout_user_ids_hash": loaded_hash})
    ablation_evidence_path = output_dir / "dedicated_ablation_evidence_manifest.json"
    frozen_evidence_checklist_path = output_dir / "frozen_promotion_evidence_checklist.json"
    ablation_manifest = _dedicated_ablation_evidence_manifest(output_dir, common, loaded_holdout_path, loaded_hash, experiments)
    _write_json(ablation_evidence_path, ablation_manifest)
    _write_json(frozen_evidence_checklist_path, _frozen_promotion_evidence_checklist(common, loaded_hash, loaded_holdout_path.parent, output_dir, ablation_evidence_path))
    _write_json(output_dir / "manifest.json", {
        **common,
        "mode": "ablation",
        "loaded_baseline_holdout_user_ids_path": str(loaded_holdout_path),
        "loaded_baseline_holdout_user_ids_hash": loaded_hash,
        "same_holdout_user_ids_verified": True,
        "experiments": [name for name, _ in experiments],
        "dedicated_ablation_contract_version": DEDICATED_ABLATION_CONTRACT_VERSION,
        "dedicated_ablation_evidence_manifest_path": str(ablation_evidence_path),
        "frozen_promotion_evidence_contract_version": FROZEN_PROMOTION_EVIDENCE_CONTRACT_VERSION,
        "frozen_promotion_evidence_checklist_path": str(frozen_evidence_checklist_path),
        "artifacts": {
            "summary_metrics_csv": str(output_dir / "summary_metrics.csv"),
            "exclusive_hits_csv": str(output_dir / "exclusive_hits.csv"),
            "source_overlap_matrix_csv": str(output_dir / "source_overlap_matrix.csv"),
            "baseline_displacement_report_csv": str(output_dir / "baseline_displacement_report.csv"),
            "latency_report_csv": str(output_dir / "latency_report.csv"),
            "fallback_stability_report_json": str(output_dir / "fallback_stability_report.json"),
            "dedicated_ablation_evidence_manifest_json": str(ablation_evidence_path),
            "frozen_promotion_evidence_checklist_json": str(frozen_evidence_checklist_path),
        },
    })
    print(json.dumps({"manifest": str(output_dir / "manifest.json"), "holdout_user_ids_hash": loaded_hash}, ensure_ascii=False, indent=2))


def _run_source_aware(
    output_dir: Path,
    common: dict[str, Any],
    config: dict[str, Any],
    phase_config: dict[str, Any],
    inputs: dict[str, Any],
    loaded_holdout_path: Path,
    loaded_hash: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    variants = _source_aware_matrix(phase_config)
    baseline_phase_config = {**phase_config, **_source_aware_source_patch()}
    baseline_inputs = dict(inputs)
    _attach_phase_sources(baseline_inputs, baseline_phase_config)
    baseline_config = _experiment_config(config, baseline_phase_config)
    baseline_raw = _build_user_diagnostics(baseline_config, baseline_inputs)
    baseline_runs = _finalize_pool(baseline_raw, baseline_config, int(baseline_config.get("candidate_pool_size", 100)))
    baseline_state = _run_state(baseline_runs, baseline_inputs)
    summary_rows: list[dict[str, Any]] = []
    displacement_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    for experiment_name, patch in variants:
        experiment_phase_config = {**baseline_phase_config, **patch}
        experiment_config = _experiment_config(config, experiment_phase_config)
        runs = _finalize_pool(baseline_raw, experiment_config, int(experiment_config.get("candidate_pool_size", 100)))
        state = _run_state(runs, baseline_inputs)
        metrics = _metrics_for_runs(experiment_config, runs, baseline_inputs)
        experiment_common = {**common, "experiment_name": experiment_name, "phase_source_features": _phase_source_config(experiment_phase_config)}
        experiment_dir = output_dir / experiment_name
        source_rows = _source_overlap_rows(runs, baseline_inputs, experiment_common)
        _write_json(experiment_dir / "metrics.json", metrics)
        _write_csv(experiment_dir / "source_coverage.csv", source_rows)
        _write_json(experiment_dir / "manifest.json", {
            **experiment_common,
            "mode": "source-aware",
            "loaded_baseline_holdout_user_ids_path": str(loaded_holdout_path),
            "loaded_baseline_holdout_user_ids_hash": loaded_hash,
            "same_holdout_user_ids_verified": True,
            "metrics_path": str(experiment_dir / "metrics.json"),
            "artifacts": {"source_coverage_csv": str(experiment_dir / "source_coverage.csv")},
        })
        summary_rows.append(_summary_metrics_row(experiment_name, common, metrics, state, baseline_state))
        displacement_rows.extend(_baseline_displacement_rows(experiment_name, state, baseline_state))
        overlap_rows.extend(_overlap_matrix_rows(experiment_name, source_rows))
    _write_csv(output_dir / "summary_metrics.csv", summary_rows)
    _write_csv(output_dir / "baseline_displacement_report.csv", displacement_rows)
    _write_csv(output_dir / "source_overlap_matrix.csv", overlap_rows)
    _write_json(output_dir / "manifest.json", {
        **common,
        "mode": "source-aware",
        "loaded_baseline_holdout_user_ids_path": str(loaded_holdout_path),
        "loaded_baseline_holdout_user_ids_hash": loaded_hash,
        "same_holdout_user_ids_verified": True,
        "experiments": [name for name, _ in variants],
        "decision_scope": "recall_only_observation",
        "artifacts": {
            "summary_metrics_csv": str(output_dir / "summary_metrics.csv"),
            "baseline_displacement_report_csv": str(output_dir / "baseline_displacement_report.csv"),
            "source_overlap_matrix_csv": str(output_dir / "source_overlap_matrix.csv"),
        },
    })
    print(json.dumps({"manifest": str(output_dir / "manifest.json"), "holdout_user_ids_hash": loaded_hash}, ensure_ascii=False, indent=2))



def _dedicated_ablation_evidence_manifest(
    output_dir: Path,
    common: dict[str, Any],
    loaded_holdout_path: Path,
    loaded_hash: str,
    experiments: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    required_artifacts = {
        "summary_metrics": output_dir / "summary_metrics.csv",
        "exclusive_hits": output_dir / "exclusive_hits.csv",
        "source_overlap_matrix": output_dir / "source_overlap_matrix.csv",
        "baseline_displacement_report": output_dir / "baseline_displacement_report.csv",
        "fallback_stability_report": output_dir / "fallback_stability_report.json",
    }
    checks = {
        name: _evidence_artifact_check(path)
        for name, path in required_artifacts.items()
    }
    missing = [name for name, check in checks.items() if not check["available"]]
    return {
        "schema_version": DEDICATED_ABLATION_CONTRACT_VERSION,
        "decision_scope": "recall_only",
        "promotion_evidence_status": "INCONCLUSIVE_MISSING_ARTIFACT" if missing else "READY_FOR_PROMOTION_REVIEW",
        "missing_required_artifacts": missing,
        "next_action": "Produce missing ablation artifacts before promotion." if missing else "Attach this manifest to frozen promotion evidence review.",
        "loaded_baseline_holdout_user_ids_path": str(loaded_holdout_path),
        "loaded_baseline_holdout_user_ids_hash": loaded_hash,
        "same_holdout_user_ids_verified": True,
        "holdout_user_ids_hash_rule": HASH_RULE,
        "evaluation_contract": {
            "evaluation_mode": common["evaluation_mode"],
            "split": common["split"],
            "limit_users": common["limit_users"],
            "users_with_holdout": common["users_with_holdout"],
            "hit_rate_denominator": common["hit_rate_denominator"],
            "holdout_user_ids_hash": loaded_hash,
        },
        "forbidden_metrics": FORBIDDEN_RECALL_REGISTRY_METRICS,
        "no_leakage_contract": NO_LEAKAGE_CONTRACT,
        "experiments": [
            {
                "experiment_name": name,
                "mode": "ablation",
                "config_patch": patch,
                "manifest_path": str(output_dir / name / "manifest.json"),
                "metrics_path": str(output_dir / name / "metrics.json"),
            }
            for name, patch in experiments
        ],
        "required_artifacts": checks,
    }


def _frozen_promotion_evidence_checklist(
    common: dict[str, Any],
    loaded_hash: str,
    baseline_output_dir: Path,
    ablation_output_dir: Path,
    ablation_evidence_path: Path,
) -> dict[str, Any]:
    required_artifacts = {
        "frozen_candidates": baseline_output_dir / "frozen_candidates.jsonl",
        "source_coverage": baseline_output_dir / "source_coverage.csv",
        "pool_curve": baseline_output_dir / "pool_curve.csv",
        "ablation_report": ablation_evidence_path,
        "overlap_report": ablation_output_dir / "source_overlap_matrix.csv",
        "latency_report": ablation_output_dir / "latency_report.csv",
        "fallback_report": ablation_output_dir / "fallback_stability_report.json",
    }
    checks = {name: _evidence_artifact_check(path) for name, path in required_artifacts.items()}
    missing = [name for name, check in checks.items() if not check["available"]]
    return {
        "schema_version": FROZEN_PROMOTION_EVIDENCE_CONTRACT_VERSION,
        "decision_scope": "recall_only",
        "gate_status": "INCONCLUSIVE_MISSING_ARTIFACT" if missing else "READY_FOR_PROMOTION_REVIEW",
        "missing_required_artifacts": missing,
        "next_action": "Attach real frozen recall artifacts; do not promote while any required artifact is missing." if missing else "Review complete recall-only promotion evidence.",
        "loaded_baseline_holdout_user_ids_hash": loaded_hash,
        "holdout_user_ids_hash_rule": HASH_RULE,
        "evaluation_contract": {
            "evaluation_mode": common["evaluation_mode"],
            "split": common["split"],
            "limit_users": common["limit_users"],
            "users_with_holdout": common["users_with_holdout"],
            "hit_rate_denominator": common["hit_rate_denominator"],
        },
        "forbidden_metrics": FORBIDDEN_RECALL_REGISTRY_METRICS,
        "required_artifacts": checks,
    }


def _evidence_artifact_check(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "available": False,
            "path": None,
            "sha256": None,
            "status": "INCONCLUSIVE_MISSING_ARTIFACT",
            "next_action": "Produce and attach this required recall promotion artifact.",
        }
    return {
        "available": path.exists(),
        "path": str(path),
        "sha256": diagnostics._sha256_file(path) if path.exists() else None,
        "status": "READY_FOR_PROMOTION_REVIEW" if path.exists() else "INCONCLUSIVE_MISSING_ARTIFACT",
        "next_action": "ready_for_review" if path.exists() else "Produce and attach this required recall promotion artifact.",
    }


def _run_pool_curve(
    output_dir: Path,
    common: dict[str, Any],
    config: dict[str, Any],
    phase_config: dict[str, Any],
    inputs: dict[str, Any],
    loaded_holdout_path: Path,
    loaded_hash: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pool_phase_config = {**phase_config, **_all_source_patch()}
    pool_inputs = dict(inputs)
    _attach_phase_sources(pool_inputs, pool_phase_config)
    experiment_config = _experiment_config(config, pool_phase_config)
    raw_runs = _build_user_diagnostics(experiment_config, pool_inputs)
    rows = []
    volume_rows = []
    for pool_size in [50, 100, 200, 500, 1000]:
        runs = _finalize_pool(raw_runs, experiment_config, pool_size)
        metrics = _metrics_for_runs({**experiment_config, "candidate_pool_size": pool_size}, runs, pool_inputs)
        latencies = [run["candidate_generation_seconds"] for run in runs.values()]
        row = {
            **common,
            "pool_size": pool_size,
            "candidate_hit_users": metrics.get("candidate_hit_users", 0),
            "candidate_hit_rate_at_pool": metrics.get("candidate_hit_rate_at_pool", 0.0),
            "recall_at_pool": metrics.get("recall_at_pool", 0.0),
            "hit_rate_at_k": metrics.get("hit_rate_at_k", 0.0),
            "fallback_rate": metrics.get("fallback_rate", 0.0),
            "candidate_count_avg": metrics.get("candidate_count_avg", 0.0),
            "candidate_generation_p95_seconds": diagnostics._percentile(latencies, 0.95),
        }
        rows.append(row)
        volume_rows.append({"pool_size": pool_size, "candidate_count_avg": metrics.get("candidate_count_avg", 0.0), "candidate_generation_p95_seconds": row["candidate_generation_p95_seconds"]})
    pool100 = next(row for row in rows if row["pool_size"] == 100)
    pool200 = next(row for row in rows if row["pool_size"] == 200)
    _write_csv(output_dir / "pool_curve.csv", rows)
    _write_csv(output_dir / "candidate_volume_latency.csv", volume_rows)
    _write_json(output_dir / "pool100_vs_pool200_report.json", {
        "holdout_user_ids_hash": loaded_hash,
        "pool100": pool100,
        "pool200": pool200,
        "candidate_hit_users_delta": pool200["candidate_hit_users"] - pool100["candidate_hit_users"],
        "recall_at_pool_delta": round(pool200["recall_at_pool"] - pool100["recall_at_pool"], 6),
        "recommendation": "diagnostic_only_pool200_not_default",
    })
    _write_json(output_dir / "manifest.json", {
        **common,
        "mode": "pool-curve",
        "phase_source_features": _phase_source_config(pool_phase_config),
        "loaded_baseline_holdout_user_ids_path": str(loaded_holdout_path),
        "loaded_baseline_holdout_user_ids_hash": loaded_hash,
        "same_holdout_user_ids_verified": True,
        "pool_sizes": [50, 100, 200, 500, 1000],
        "artifacts": {
            "pool_curve_csv": str(output_dir / "pool_curve.csv"),
            "pool100_vs_pool200_report_json": str(output_dir / "pool100_vs_pool200_report.json"),
            "candidate_volume_latency_csv": str(output_dir / "candidate_volume_latency.csv"),
        },
    })
    print(json.dumps({"manifest": str(output_dir / "manifest.json"), "holdout_user_ids_hash": loaded_hash}, ensure_ascii=False, indent=2))


def _run_audit(
    output_dir: Path,
    common: dict[str, Any],
    config: dict[str, Any],
    baseline_pool_size: int,
    runs: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
    loaded_holdout_path: Path,
    loaded_hash: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    miss_rows = _miss_target_rows(runs, inputs, config)
    source_gap_rows = _source_gap_rows(miss_rows)
    category_rows = _summary_rows(miss_rows, "category")
    popularity_rows = _summary_rows(miss_rows, "popularity_bucket")
    opportunity_summary = _opportunity_summary(miss_rows)

    _write_csv(output_dir / "miss_targets.csv", miss_rows)
    _write_csv(output_dir / "source_gap_audit.csv", source_gap_rows)
    _write_csv(output_dir / "category_gap_summary.csv", category_rows)
    _write_csv(output_dir / "popularity_gap_summary.csv", popularity_rows)
    _write_json(output_dir / "source_opportunity_summary.json", opportunity_summary)

    manifest = {
        **common,
        "mode": "audit",
        "baseline_candidate_pool_size": baseline_pool_size,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "metrics_contract_version": METRICS_CONTRACT_VERSION,
        "loaded_baseline_holdout_user_ids_path": str(loaded_holdout_path),
        "loaded_baseline_holdout_user_ids_hash": loaded_hash,
        "no_leakage_contract": NO_LEAKAGE_CONTRACT,
        "miss_targets_count": len(miss_rows),
        "artifacts": {
            "miss_targets_csv": str(output_dir / "miss_targets.csv"),
            "source_gap_audit_csv": str(output_dir / "source_gap_audit.csv"),
            "category_gap_summary_csv": str(output_dir / "category_gap_summary.csv"),
            "popularity_gap_summary_csv": str(output_dir / "popularity_gap_summary.csv"),
            "source_opportunity_summary_json": str(output_dir / "source_opportunity_summary.json"),
        },
    }
    _write_json(output_dir / "manifest.json", manifest)
    print(json.dumps({"manifest": str(output_dir / "manifest.json"), "holdout_user_ids_hash": common["holdout_user_ids_hash"]}, ensure_ascii=False, indent=2))


def _attach_phase_sources(inputs: dict[str, Any], phase_config: dict[str, Any]) -> None:
    phase_sources = _phase_source_config(phase_config)
    train_sequences = diagnostics.read_jsonl(inputs["paths"]["sequences"])
    inputs["co_visit_fallback_repair"] = _build_co_visit_neighbors(train_sequences, phase_sources)
    inputs["usercf_recall"] = _build_usercf_index(train_sequences, phase_sources)
    inputs["swing_recall"] = _build_swing_index(train_sequences, phase_sources)
    inputs["session_transition_recall"] = _build_session_transition_index(train_sequences, phase_sources)
    inputs["implicit_svd_recall"] = _build_implicit_svd_index(train_sequences, phase_sources)
    inputs["als_mf_recall"] = _build_implicit_mf_index(train_sequences, phase_sources, "als_mf")
    inputs["bpr_mf_recall"] = _build_implicit_mf_index(train_sequences, phase_sources, "bpr_mf")
    inputs["lightfm_recall"] = _build_lightfm_index(train_sequences, phase_sources)
    inputs["multi_interest_recall"] = _build_multi_interest_index(train_sequences, phase_sources)
    itemcf_seed_items = diagnostics._itemcf_seed_items(inputs["sequences"])
    views_dir = Path(inputs["paths"]["category_items"]).parent
    if phase_sources.get("item_graph_enabled") and not inputs.get("item_graph"):
        item_graph_path = diagnostics._resolve_item_graph_artifact_path(phase_sources, views_dir)
        if item_graph_path.exists():
            inputs["item_graph"] = load_item_graph_recall(item_graph_path, itemcf_seed_items)
    if phase_sources.get("graph_walk_seed_enabled") and not inputs.get("graph_walk_seed"):
        graph_walk_seed_path = diagnostics._resolve_graph_walk_seed_artifact_path(phase_sources, views_dir)
        graph_walk_seed_manifest_path = diagnostics._resolve_graph_walk_seed_manifest_path(phase_sources, views_dir)
        if graph_walk_seed_path.exists() and graph_walk_seed_manifest_path.exists():
            inputs["graph_walk_seed"] = load_graph_walk_seed_recall(graph_walk_seed_path, itemcf_seed_items, graph_walk_seed_manifest_path)
    needs_semantic_index = any(key in phase_sources for key in ["semantic_title_category_expansion", "metadata_neighbor_enabled"])
    if needs_semantic_index and not inputs.get("semantic_index"):
        semantic_path = Path(inputs["paths"]["category_items"]).parent / "semantic_recall_inputs.jsonl"
        if semantic_path.exists():
            text_fields = phase_sources.get("semantic_title_category_expansion", {}).get("text_fields", ["title_clean", "main_category", "categories_flat"])
            inputs["semantic_index"] = diagnostics.load_semantic_index(semantic_path, text_fields)


def _experiment_config(config: dict[str, Any], phase_config: dict[str, Any]) -> dict[str, Any]:
    experiment_config = dict(config)
    if "candidate_pool_size" in phase_config:
        experiment_config["candidate_pool_size"] = int(phase_config["candidate_pool_size"])
    phase_sources = _phase_source_config(phase_config)
    experiment_config.update({key: value for key, value in phase_sources.items() if key != "rank_weights"})
    if phase_sources.get("rank_weights"):
        experiment_config["rank_weights"] = dict(config.get("rank_weights", {})) | phase_sources["rank_weights"]
    return experiment_config


def _phase_source_config(phase_config: dict[str, Any]) -> dict[str, Any]:
    config = {
        key: phase_config[key]
        for key in [
            "co_visit_fallback_repair_enabled",
            "co_visit_seed_window",
            "co_visit_per_seed",
            "co_visit_per_user",
            "co_visit_min_score",
            "co_visit_max_item_user_freq",
            "co_visit_recency_decay",
            "category_long_tail_enabled",
            "category_long_tail_start_rank",
            "category_long_tail_per_user",
            "category_long_tail_per_category",
            "category_long_tail_seed_window",
            "metadata_neighbor_enabled",
            "metadata_neighbor_per_user",
            "metadata_neighbor_per_seed",
            "metadata_neighbor_seed_window",
            "metadata_neighbor_min_token_overlap",
            "metadata_neighbor_category_weight",
            "metadata_neighbor_max_bucket_candidates",
            "item_graph_enabled",
            "item_graph_seed_window",
            "item_graph_recent_positive_window",
            "item_graph_recent_strong_window",
            "item_graph_per_seed",
            "item_graph_per_user",
            "graph_walk_seed_enabled",
            "graph_walk_seed_window",
            "graph_walk_seed_recent_positive_window",
            "graph_walk_seed_recent_strong_window",
            "graph_walk_seed_per_seed",
            "graph_walk_seed_per_user",
            "graph_walk_seed_recency_decay",
            "graph_walk_seed_score_floor",
            "usercf_enabled",
            "usercf_seed_window",
            "usercf_similar_users",
            "usercf_per_user",
            "usercf_min_score",
            "swing_enabled",
            "swing_seed_window",
            "swing_per_seed",
            "swing_per_user",
            "swing_alpha",
            "swing_min_score",
            "session_transition_enabled",
            "session_transition_seed_window",
            "session_transition_per_seed",
            "session_transition_per_user",
            "session_transition_recency_decay",
            "session_transition_min_score",
            "implicit_svd_enabled",
            "implicit_svd_factors",
            "implicit_svd_per_user",
            "implicit_svd_min_score",
            "als_mf_enabled",
            "als_mf_factors",
            "als_mf_iterations",
            "als_mf_regularization",
            "als_mf_alpha",
            "als_mf_per_user",
            "als_mf_min_score",
            "bpr_mf_enabled",
            "bpr_mf_factors",
            "bpr_mf_iterations",
            "bpr_mf_regularization",
            "bpr_mf_learning_rate",
            "bpr_mf_per_user",
            "bpr_mf_min_score",
            "lightfm_enabled",
            "lightfm_components",
            "lightfm_epochs",
            "lightfm_loss",
            "lightfm_learning_rate",
            "lightfm_per_user",
            "lightfm_min_score",
            "two_tower_enabled",
            "two_tower_per_user",
            "two_tower_seed_window",
            "two_tower_min_overlap",
            "two_tower_recency_decay",
            "two_tower_text_fields",
            "multi_interest_enabled",
            "multi_interest_seed_window",
            "multi_interest_per_seed",
            "multi_interest_per_user",
            "multi_interest_min_score",
            "multi_interest_recency_decay",
            "multi_interest_session_weight",
            "candidate_pool_strategy",
            "candidate_source_minimums",
            "candidate_source_maximums",
            "candidate_fill_order",
            "candidate_multi_source_boost",
        ]
        if key in phase_config
    }
    semantic_config = _semantic_title_category_config(phase_config)
    if semantic_config:
        config["semantic_title_category_expansion"] = semantic_config
        config["rank_weights"] = {"semantic_title_category_expansion": float(semantic_config.get("rank_weight", 1.0))}
    return config


def _semantic_title_category_config(phase_config: dict[str, Any]) -> dict[str, Any]:
    source_config = phase_config.get("semantic_title_category_expansion", {})
    if not isinstance(source_config, dict) or not source_config.get("enabled"):
        return {}
    return {
        "enabled": True,
        "per_user": int(source_config.get("per_user", 20)),
        "per_seed": int(source_config.get("per_seed", 10)),
        "seed_window": int(source_config.get("seed_window", 20)),
        "min_title_overlap": int(source_config.get("min_title_overlap", 1)),
        "category_weight": float(source_config.get("category_weight", 2.0)),
        "weak_category_boost": float(source_config.get("weak_category_boost", 0.5)),
        "weak_categories": list(source_config.get("weak_categories", [])),
        "text_fields": list(source_config.get("text_fields", ["title_clean", "main_category", "categories_flat"])),
        "require_category_overlap": bool(source_config.get("require_category_overlap", True)),
        "rank_weight": float(source_config.get("rank_weight", 1.0)),
    }


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
    raw.extend(_co_visit_candidates_for_user(sequence, inputs["co_visit_fallback_repair"], config))
    raw.extend(_usercf_candidates_for_user(sequence, inputs["usercf_recall"], config))
    raw.extend(_swing_candidates_for_user(sequence, inputs["swing_recall"], config))
    raw.extend(_session_transition_candidates_for_user(sequence, inputs["session_transition_recall"], config))
    raw.extend(_implicit_svd_candidates_for_user(sequence, inputs["implicit_svd_recall"], config))
    raw.extend(_implicit_mf_candidates_for_user(sequence, inputs["als_mf_recall"], config, "als_mf"))
    raw.extend(_implicit_mf_candidates_for_user(sequence, inputs["bpr_mf_recall"], config, "bpr_mf"))
    raw.extend(_lightfm_candidates_for_user(sequence, inputs["lightfm_recall"], config))
    raw.extend(_multi_interest_candidates_for_user(sequence, inputs["multi_interest_recall"], config))
    return raw


def _build_co_visit_neighbors(sequences: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("co_visit_fallback_repair_enabled"):
        return {}
    max_user_freq = int(config.get("co_visit_max_item_user_freq", 0) or 0)
    item_users: dict[str, set[str]] = defaultdict(set)
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        for item_id in set(sequence.get("recent_item_sequence", [])):
            if item_id:
                item_users[str(item_id)].add(user_id)
    noisy_items = {item_id for item_id, users in item_users.items() if max_user_freq and len(users) > max_user_freq}

    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    for sequence in sequences:
        items = [str(item_id) for item_id in dict.fromkeys(sequence.get("recent_item_sequence", [])) if item_id]
        for seed in items:
            for neighbor in items:
                if seed != neighbor and neighbor not in noisy_items:
                    pair_scores[seed][neighbor] += 1

    min_score = float(config.get("co_visit_min_score", 1.0))
    per_seed = int(config.get("co_visit_per_seed", 20))
    neighbors: dict[str, list[RecallCandidate]] = {}
    for seed, scores in pair_scores.items():
        rows: list[RecallCandidate] = []
        for rank, (neighbor, score) in enumerate(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:per_seed]):
            if float(score) < min_score:
                continue
            rows.append(RecallCandidate(
                item_id=neighbor,
                source="co_visit_fallback_repair",
                score=float(score),
                metadata={
                    "reason": "train_period_co_visit",
                    "seed_item_id": seed,
                    "source_score": float(score),
                    "source_rank": rank + 1,
                    "popular_noise_control": "max_item_user_freq",
                },
            ))
        if rows:
            neighbors[seed] = rows
    return neighbors


def _co_visit_candidates_for_user(sequence: dict[str, Any], neighbors: dict[str, list[RecallCandidate]], config: dict[str, Any]) -> list[RecallCandidate]:
    if not config.get("co_visit_fallback_repair_enabled") or not neighbors:
        return []
    seed_window = int(config.get("co_visit_seed_window", 10))
    per_seed = int(config.get("co_visit_per_seed", 20))
    per_user = int(config.get("co_visit_per_user", per_seed * max(1, seed_window)))
    recency_decay = float(config.get("co_visit_recency_decay", 1.0))
    seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", [])}
    seeds = list(dict.fromkeys(reversed([str(item_id) for item_id in sequence.get("recent_positive_item_sequence", [])[-seed_window:]])))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in neighbors.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            score = round(candidate.score * decay, 6)
            metadata = dict(candidate.metadata)
            metadata.update({"seed_item_id": seed, "seed_rank": seed_rank, "co_visit_score": candidate.score, "co_visit_decayed_score": score})
            row = RecallCandidate(item_id=candidate.item_id, source="co_visit_fallback_repair", score=score, category=candidate.category, metadata=metadata)
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:per_user]


def _build_usercf_index(sequences: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("usercf_enabled"):
        return {}
    similar_users = int(config.get("usercf_similar_users", 20))
    user_items: dict[str, set[str]] = {}
    item_users: dict[str, set[str]] = defaultdict(set)
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        items = {str(item_id) for item_id in sequence.get("recent_positive_item_sequence", []) if item_id}
        if not user_id or not items:
            continue
        user_items[user_id] = items
        for item_id in items:
            item_users[item_id].add(user_id)

    index: dict[str, list[RecallCandidate]] = {}
    for user_id, items in user_items.items():
        neighbor_scores: Counter[str] = Counter()
        for item_id in items:
            for neighbor_user in item_users[item_id]:
                if neighbor_user != user_id:
                    neighbor_scores[neighbor_user] += 1
        candidate_scores: Counter[str] = Counter()
        for neighbor_user, overlap in sorted(neighbor_scores.items(), key=lambda item: (-item[1], item[0]))[:similar_users]:
            norm = math.sqrt(len(items) * max(1, len(user_items.get(neighbor_user, set()))))
            user_score = float(overlap) / norm if norm else 0.0
            for item_id in user_items.get(neighbor_user, set()) - items:
                candidate_scores[item_id] += user_score
        index[user_id] = [
            RecallCandidate(
                item_id=item_id,
                source="usercf_recall",
                score=round(float(score), 6),
                metadata={"reason": "train_user_similarity", "source_score": round(float(score), 6), "source_rank": rank},
            )
            for rank, (item_id, score) in enumerate(sorted(candidate_scores.items(), key=lambda item: (-item[1], item[0])), start=1)
        ]
    return index


def _usercf_candidates_for_user(sequence: dict[str, Any], index: dict[str, list[RecallCandidate]], config: dict[str, Any]) -> list[RecallCandidate]:
    if not config.get("usercf_enabled") or not index:
        return []
    min_score = float(config.get("usercf_min_score", 0.0))
    per_user = int(config.get("usercf_per_user", 30))
    seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", [])}
    rows = [candidate for candidate in index.get(str(sequence.get("user_id", "")), []) if candidate.score >= min_score and candidate.item_id not in seen_items]
    return rows[:per_user]


def _build_swing_index(sequences: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("swing_enabled"):
        return {}
    alpha = float(config.get("swing_alpha", 1.0))
    user_items: dict[str, set[str]] = {}
    item_users: dict[str, set[str]] = defaultdict(set)
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        items = {str(item_id) for item_id in sequence.get("recent_positive_item_sequence", []) if item_id}
        if not user_id or len(items) < 2:
            continue
        user_items[user_id] = items
        for item_id in items:
            item_users[item_id].add(user_id)

    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    for left_item, left_users in item_users.items():
        related_items = Counter()
        for user in left_users:
            for right_item in user_items[user]:
                if right_item != left_item:
                    related_items[right_item] += 1
        for right_item, co_count in related_items.items():
            common_users = left_users & item_users[right_item]
            denom = alpha + sum(1.0 / max(1, len(user_items[user])) for user in common_users)
            score = float(co_count) / denom if denom else 0.0
            if score:
                pair_scores[left_item][right_item] += score

    per_seed = int(config.get("swing_per_seed", 20))
    min_score = float(config.get("swing_min_score", 0.0))
    index: dict[str, list[RecallCandidate]] = {}
    for seed, scores in pair_scores.items():
        rows = []
        for rank, (item_id, score) in enumerate(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:per_seed], start=1):
            if float(score) < min_score:
                continue
            rows.append(RecallCandidate(item_id=item_id, source="swing_recall", score=round(float(score), 6), metadata={"reason": "train_swing_item_pair", "seed_item_id": seed, "source_score": round(float(score), 6), "source_rank": rank}))
        if rows:
            index[seed] = rows
    return index


def _swing_candidates_for_user(sequence: dict[str, Any], index: dict[str, list[RecallCandidate]], config: dict[str, Any]) -> list[RecallCandidate]:
    if not config.get("swing_enabled") or not index:
        return []
    seed_window = int(config.get("swing_seed_window", 20))
    per_seed = int(config.get("swing_per_seed", 20))
    per_user = int(config.get("swing_per_user", 30))
    seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", [])}
    seeds = list(dict.fromkeys(reversed([str(item_id) for item_id in sequence.get("recent_positive_item_sequence", [])[-seed_window:]])))
    by_item: dict[str, RecallCandidate] = {}
    for seed in seeds:
        for candidate in index.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            current = by_item.get(candidate.item_id)
            if current is None or candidate.score > current.score:
                by_item[candidate.item_id] = candidate
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:per_user]


def _build_session_transition_index(sequences: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("session_transition_enabled"):
        return {}
    pair_scores: dict[str, Counter[str]] = defaultdict(Counter)
    for sequence in sequences:
        items = [str(item_id) for item_id in sequence.get("recent_item_sequence", []) if item_id]
        for left, right in zip(items, items[1:]):
            if left != right:
                pair_scores[left][right] += 1
    per_seed = int(config.get("session_transition_per_seed", 20))
    min_score = float(config.get("session_transition_min_score", 1.0))
    index: dict[str, list[RecallCandidate]] = {}
    for seed, scores in pair_scores.items():
        rows = []
        for rank, (item_id, score) in enumerate(sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:per_seed], start=1):
            if float(score) < min_score:
                continue
            rows.append(RecallCandidate(item_id=item_id, source="session_transition_recall", score=float(score), metadata={"reason": "train_adjacent_transition", "seed_item_id": seed, "source_score": float(score), "source_rank": rank}))
        if rows:
            index[seed] = rows
    return index


def _build_multi_interest_index(sequences: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("multi_interest_enabled"):
        return {}
    seed_scores: dict[str, Counter[str]] = defaultdict(Counter)
    seed_sessions: dict[str, Counter[str]] = defaultdict(Counter)
    for sequence in sequences:
        items = [str(item_id) for item_id in sequence.get("recent_positive_item_sequence") or sequence.get("recent_item_sequence", []) if item_id]
        unique_items = list(dict.fromkeys(items))
        if len(unique_items) < 2:
            continue
        session_items = unique_items[-3:]
        for seed in unique_items:
            for candidate in unique_items:
                if seed == candidate:
                    continue
                seed_scores[seed][candidate] += 1
                if seed in session_items and candidate in session_items:
                    seed_sessions[seed][candidate] += 1
    per_seed = int(config.get("multi_interest_per_seed", 20))
    min_score = float(config.get("multi_interest_min_score", 1.0))
    session_weight = float(config.get("multi_interest_session_weight", 0.25))
    index: dict[str, list[RecallCandidate]] = {}
    for seed, scores in seed_scores.items():
        rows = []
        scored_items = {item_id: float(score) + float(seed_sessions[seed].get(item_id, 0)) * session_weight for item_id, score in scores.items()}
        for rank, (item_id, score) in enumerate(sorted(scored_items.items(), key=lambda item: (-item[1], item[0]))[:per_seed], start=1):
            if score < min_score:
                continue
            rows.append(RecallCandidate(
                item_id=item_id,
                source="multi_interest_recall",
                score=round(score, 6),
                metadata={
                    "reason": "train_period_multi_interest",
                    "seed_item_id": seed,
                    "source_score": round(score, 6),
                    "source_rank": rank,
                    "seed_info": {"interest_unit": "train_positive_sequence", "session_neighbor_weight": session_weight},
                },
            ))
        if rows:
            index[seed] = rows
    return index


def _multi_interest_candidates_for_user(sequence: dict[str, Any], index: dict[str, list[RecallCandidate]], config: dict[str, Any]) -> list[RecallCandidate]:
    if not config.get("multi_interest_enabled") or not index:
        return []
    seed_window = int(config.get("multi_interest_seed_window", 20))
    per_seed = int(config.get("multi_interest_per_seed", 20))
    per_user = int(config.get("multi_interest_per_user", 30))
    recency_decay = float(config.get("multi_interest_recency_decay", 0.9))
    seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", [])}
    seeds = list(dict.fromkeys(reversed([str(item_id) for item_id in sequence.get("recent_positive_item_sequence", [])[-seed_window:]])))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in index.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            score = round(candidate.score * decay, 6)
            metadata = dict(candidate.metadata)
            metadata.update({"seed_rank": seed_rank, "multi_interest_decayed_score": score})
            row = RecallCandidate(item_id=candidate.item_id, source="multi_interest_recall", score=score, metadata=metadata)
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:per_user]


def _build_implicit_svd_index(sequences: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("implicit_svd_enabled"):
        return {}
    user_ids = [str(sequence.get("user_id", "")) for sequence in sequences if sequence.get("user_id")]
    item_ids = sorted({str(item_id) for sequence in sequences for item_id in sequence.get("recent_positive_item_sequence", []) if item_id})
    if not user_ids or len(item_ids) < 2:
        return {}
    user_index = {user_id: index for index, user_id in enumerate(user_ids)}
    item_index = {item_id: index for index, item_id in enumerate(item_ids)}
    matrix = np.zeros((len(user_ids), len(item_ids)), dtype=np.float32)
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        if user_id not in user_index:
            continue
        for item_id in sequence.get("recent_positive_item_sequence", []):
            item_id = str(item_id)
            if item_id in item_index:
                matrix[user_index[user_id], item_index[item_id]] = 1.0
    if not np.any(matrix):
        return {}
    factors = max(1, min(int(config.get("implicit_svd_factors", 16)), min(matrix.shape) - 1))
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    try:
        u, singular_values, vt = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return {}
    reconstructed = (u[:, :factors] * singular_values[:factors]) @ vt[:factors, :]
    per_user = int(config.get("implicit_svd_per_user", 30))
    min_score = float(config.get("implicit_svd_min_score", 0.0))
    index: dict[str, list[RecallCandidate]] = {}
    for user_id, user_row in user_index.items():
        seen = {str(item_id) for item_id in sequences[user_row].get("recent_item_sequence", [])}
        rows = []
        for item_id, item_col in item_index.items():
            if item_id in seen:
                continue
            score = float(reconstructed[user_row, item_col])
            if score < min_score:
                continue
            rows.append((item_id, score))
        index[user_id] = [
            RecallCandidate(item_id=item_id, source="implicit_svd_recall", score=round(score, 6), metadata={"reason": "train_implicit_svd", "source_score": round(score, 6), "source_rank": rank})
            for rank, (item_id, score) in enumerate(sorted(rows, key=lambda item: (-item[1], item[0]))[:per_user], start=1)
        ]
    return index


def _implicit_svd_candidates_for_user(sequence: dict[str, Any], index: dict[str, list[RecallCandidate]], config: dict[str, Any]) -> list[RecallCandidate]:
    if not config.get("implicit_svd_enabled") or not index:
        return []
    return index.get(str(sequence.get("user_id", "")), [])[: int(config.get("implicit_svd_per_user", 30))]


def _build_implicit_mf_index(sequences: list[dict[str, Any]], config: dict[str, Any], model_name: str) -> dict[str, list[RecallCandidate]]:
    if not config.get(f"{model_name}_enabled") or importlib.util.find_spec("implicit") is None or importlib.util.find_spec("scipy") is None:
        return {}
    user_ids = [str(sequence.get("user_id", "")) for sequence in sequences if sequence.get("user_id")]
    item_ids = sorted({str(item_id) for sequence in sequences for item_id in sequence.get("recent_positive_item_sequence", []) if item_id})
    if not user_ids or len(item_ids) < 2:
        return {}
    from scipy.sparse import csr_matrix
    from implicit import als, bpr

    user_index = {user_id: index for index, user_id in enumerate(user_ids)}
    item_index = {item_id: index for index, item_id in enumerate(item_ids)}
    row_indices = []
    col_indices = []
    values = []
    for sequence in sequences:
        user_id = str(sequence.get("user_id", ""))
        if user_id not in user_index:
            continue
        for item_id in dict.fromkeys(sequence.get("recent_positive_item_sequence", [])):
            item_id = str(item_id)
            if item_id in item_index:
                row_indices.append(user_index[user_id])
                col_indices.append(item_index[item_id])
                values.append(float(config.get(f"{model_name}_alpha", 1.0)))
    if not values:
        return {}
    user_items = csr_matrix((values, (row_indices, col_indices)), shape=(len(user_ids), len(item_ids)), dtype=np.float32)
    factors = max(1, min(int(config.get(f"{model_name}_factors", 16)), min(user_items.shape)))
    iterations = max(1, int(config.get(f"{model_name}_iterations", 10)))
    regularization = float(config.get(f"{model_name}_regularization", 0.01))
    if model_name == "als_mf":
        model = als.AlternatingLeastSquares(factors=factors, iterations=iterations, regularization=regularization, random_state=42)
    elif model_name == "bpr_mf":
        model = bpr.BayesianPersonalizedRanking(
            factors=factors,
            iterations=iterations,
            regularization=regularization,
            learning_rate=float(config.get("bpr_mf_learning_rate", 0.01)),
            random_state=42,
        )
    else:
        return {}
    try:
        model.fit(user_items, show_progress=False)
    except (ValueError, IndexError, TypeError):
        return {}
    per_user = int(config.get(f"{model_name}_per_user", 30))
    min_score = float(config.get(f"{model_name}_min_score", 0.0))
    source = f"{model_name}_recall"
    reason = "train_implicit_als" if model_name == "als_mf" else "train_implicit_bpr"
    item_by_index = {index: item_id for item_id, index in item_index.items()}
    index: dict[str, list[RecallCandidate]] = {}
    for user_id, user_row in user_index.items():
        try:
            recommended_ids, scores = model.recommend(user_row, user_items[user_row], N=per_user, filter_already_liked_items=True)
        except (ValueError, IndexError, TypeError):
            continue
        rows = []
        for item_col, score in zip(recommended_ids, scores, strict=False):
            item_id = item_by_index.get(int(item_col))
            score = float(score)
            if item_id is None or not math.isfinite(score) or score < min_score:
                continue
            rows.append((item_id, score))
        index[user_id] = [
            RecallCandidate(
                item_id=item_id,
                source=source,
                score=round(score, 6),
                metadata={"reason": reason, "source_score": round(score, 6), "source_rank": rank, "model_name": model_name},
            )
            for rank, (item_id, score) in enumerate(sorted(rows, key=lambda item: (-item[1], item[0]))[:per_user], start=1)
        ]
    return index


def _implicit_mf_candidates_for_user(sequence: dict[str, Any], index: dict[str, list[RecallCandidate]], config: dict[str, Any], model_name: str) -> list[RecallCandidate]:
    if not config.get(f"{model_name}_enabled") or not index:
        return []
    return index.get(str(sequence.get("user_id", "")), [])[: int(config.get(f"{model_name}_per_user", 30))]


def _build_lightfm_index(sequences: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, list[RecallCandidate]]:
    if not config.get("lightfm_enabled") or importlib.util.find_spec("lightfm") is None or importlib.util.find_spec("scipy") is None:
        return {}
    train_sequences = [
        sequence
        for sequence in sequences
        if sequence.get("user_id") and any(sequence.get("recent_positive_item_sequence", []))
    ]
    user_ids = [str(sequence.get("user_id", "")) for sequence in train_sequences]
    item_ids = sorted({str(item_id) for sequence in train_sequences for item_id in sequence.get("recent_positive_item_sequence", []) if item_id})
    if not user_ids or len(item_ids) < 2:
        return {}
    from scipy.sparse import csr_matrix
    from lightfm import LightFM

    user_index = {user_id: index for index, user_id in enumerate(user_ids)}
    item_index = {item_id: index for index, item_id in enumerate(item_ids)}
    row_indices = []
    col_indices = []
    values = []
    seen_by_user: dict[str, set[str]] = {}
    for sequence in train_sequences:
        user_id = str(sequence.get("user_id", ""))
        if user_id not in user_index:
            continue
        seen_by_user[user_id] = {str(item_id) for item_id in sequence.get("recent_item_sequence", []) if item_id}
        for item_id in dict.fromkeys(sequence.get("recent_positive_item_sequence", [])):
            item_id = str(item_id)
            if item_id in item_index:
                row_indices.append(user_index[user_id])
                col_indices.append(item_index[item_id])
                values.append(1.0)
    if not values:
        return {}
    interactions = csr_matrix((values, (row_indices, col_indices)), shape=(len(user_ids), len(item_ids)), dtype=np.float32)
    model = LightFM(
        no_components=max(1, int(config.get("lightfm_components", 16))),
        loss=str(config.get("lightfm_loss", "warp")),
        learning_rate=float(config.get("lightfm_learning_rate", 0.05)),
        random_state=42,
    )
    try:
        model.fit(interactions, epochs=max(1, int(config.get("lightfm_epochs", 5))), num_threads=1)
    except (ValueError, IndexError, TypeError):
        return {}
    per_user = int(config.get("lightfm_per_user", 30))
    min_score = float(config.get("lightfm_min_score", -1.0))
    item_cols = np.arange(len(item_ids), dtype=np.int32)
    item_by_index = {index: item_id for item_id, index in item_index.items()}
    index: dict[str, list[RecallCandidate]] = {}
    for user_id, user_row in user_index.items():
        try:
            scores = model.predict(user_row, item_cols, num_threads=1)
        except (ValueError, IndexError, TypeError):
            continue
        rows = []
        seen = seen_by_user.get(user_id, set())
        for item_col, score in enumerate(scores):
            item_id = item_by_index.get(item_col)
            score = float(score)
            if item_id is None or item_id in seen or not math.isfinite(score) or score < min_score:
                continue
            rows.append((item_id, score))
        index[user_id] = [
            RecallCandidate(
                item_id=item_id,
                source="lightfm_recall",
                score=round(score, 6),
                metadata={"reason": f"train_lightfm_{model.loss}", "source_score": round(score, 6), "source_rank": rank, "model_name": "lightfm"},
            )
            for rank, (item_id, score) in enumerate(sorted(rows, key=lambda item: (-item[1], item[0]))[:per_user], start=1)
        ]
    return index


def _lightfm_candidates_for_user(sequence: dict[str, Any], index: dict[str, list[RecallCandidate]], config: dict[str, Any]) -> list[RecallCandidate]:
    if not config.get("lightfm_enabled") or not index:
        return []
    return index.get(str(sequence.get("user_id", "")), [])[: int(config.get("lightfm_per_user", 30))]


def _session_transition_candidates_for_user(sequence: dict[str, Any], index: dict[str, list[RecallCandidate]], config: dict[str, Any]) -> list[RecallCandidate]:
    if not config.get("session_transition_enabled") or not index:
        return []
    seed_window = int(config.get("session_transition_seed_window", 10))
    per_seed = int(config.get("session_transition_per_seed", 20))
    per_user = int(config.get("session_transition_per_user", 30))
    recency_decay = float(config.get("session_transition_recency_decay", 0.9))
    seen_items = {str(item_id) for item_id in sequence.get("recent_item_sequence", [])}
    seeds = list(dict.fromkeys(reversed([str(item_id) for item_id in sequence.get("recent_item_sequence", [])[-seed_window:]])))
    by_item: dict[str, RecallCandidate] = {}
    for seed_rank, seed in enumerate(seeds):
        decay = recency_decay**seed_rank
        for candidate in index.get(seed, [])[:per_seed]:
            if candidate.item_id in seen_items:
                continue
            score = round(candidate.score * decay, 6)
            metadata = dict(candidate.metadata)
            metadata.update({"seed_rank": seed_rank, "transition_decayed_score": score})
            row = RecallCandidate(item_id=candidate.item_id, source="session_transition_recall", score=score, metadata=metadata)
            current = by_item.get(row.item_id)
            if current is None or row.score > current.score:
                by_item[row.item_id] = row
    rows = list(by_item.values())
    rows.sort(key=lambda item: (-item.score, item.item_id))
    return rows[:per_user]


def _finalize_pool(raw_runs: dict[str, dict[str, Any]], config: dict[str, Any], pool_size: int) -> dict[str, dict[str, Any]]:
    pool_config = dict(config)
    pool_config["candidate_pool_size"] = pool_size
    rows = {}
    for user_id, run in raw_runs.items():
        pool = _limit_candidate_pool(run["merged_before_pool_limit"], pool_size, pool_config)
        ranking = rank_candidates(user_id, pool, pool_config)
        rows[user_id] = {**run, "pool_after_limit": pool, "ranking": ranking}
    return rows


def _metrics_for_runs(config: dict[str, Any], runs: dict[str, dict[str, Any]], inputs: dict[str, Any]) -> dict[str, Any]:
    candidates_by_user = {user_id: run["pool_after_limit"] for user_id, run in runs.items()}
    rankings_by_user = {user_id: run["ranking"] for user_id, run in runs.items()}
    fallback_users = {user_id for user_id, run in runs.items() if run["fallback_used"]}
    return evaluate(candidates_by_user, rankings_by_user, inputs["holdout"], config, fallback_users).to_dict()


def _source_overlap_rows(runs: dict[str, dict[str, Any]], inputs: dict[str, Any], common: dict[str, Any]) -> list[dict[str, Any]]:
    source_candidate_counts: Counter[str] = Counter()
    source_user_counts: Counter[str] = Counter()
    source_hit_users: Counter[str] = Counter()
    exclusive_hit_users: Counter[str] = Counter()
    pair_counts: Counter[str] = Counter()
    positives = inputs["positives"]
    for user_id, run in runs.items():
        targets = positives.get(user_id, set())
        user_sources: set[str] = set()
        user_hit_sources: set[str] = set()
        for candidate in run["pool_after_limit"]:
            unique_sources = sorted(set(candidate.sources))
            source_candidate_counts.update(unique_sources)
            user_sources.update(unique_sources)
            for left_index, left in enumerate(unique_sources):
                for right in unique_sources[left_index + 1:]:
                    pair_counts[f"{left}+{right}"] += 1
            if candidate.item_id in targets:
                user_hit_sources.update(unique_sources)
        source_user_counts.update(user_sources)
        source_hit_users.update(user_hit_sources)
        if len(user_hit_sources) == 1:
            exclusive_hit_users.update(user_hit_sources)
    sources = sorted(set(source_candidate_counts) | set(source_user_counts) | set(source_hit_users) | set(exclusive_hit_users))
    rows = [
        {
            **common,
            "row_type": "source",
            "source": source,
            "candidate_count": source_candidate_counts[source],
            "user_count": source_user_counts[source],
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
            "user_count": "",
            "hit_users": "",
            "exclusive_hit_users": "",
            "pair": pair,
            "pair_count": count,
        }
        for pair, count in sorted(pair_counts.items())
    )
    return rows


def _miss_target_rows(runs: dict[str, dict[str, Any]], inputs: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    positives = inputs["positives"]
    target_metadata = inputs["target_metadata"]
    for user_id, run in sorted(runs.items()):
        targets = positives.get(user_id, set())
        if not targets:
            continue
        candidate_sets = {
            "raw_non_popular": diagnostics._candidate_ids(run["raw_non_popular_before_fallback"]),
            "raw_with_fallback": diagnostics._candidate_ids(run["raw_with_fallback_before_merge"]),
            "raw_pre_pool": diagnostics._candidate_ids(run["merged_before_pool_limit"]),
            "pool100": diagnostics._candidate_ids(run["pool_after_limit"]),
            "pool200": diagnostics._candidate_ids(diagnostics._limit_candidate_pool(run["merged_before_pool_limit"], 200, {**config, "candidate_pool_size": 200})),
            "topk": {item.get("parent_asin") for item in run["ranking"].items if item.get("parent_asin")},
        }
        sequence = run["sequence"]
        has_behavior_seed = bool(sequence.get("recent_positive_item_sequence") or sequence.get("recent_strong_positive_item_sequence"))
        for target in sorted(targets):
            target_sources = _target_sources(run["pool_after_limit"], target)
            metadata = target_metadata.get(target, {})
            has_title = bool(metadata.get("has_title"))
            has_category = bool(metadata.get("category"))
            raw_hit = target in candidate_sets["raw_pre_pool"]
            pool_hit = target in candidate_sets["pool100"]
            topk_hit = target in candidate_sets["topk"]
            rows.append({
                "user_id": user_id,
                "target_item": target,
                "raw_non_popular_hit": raw_hit_bool(target, candidate_sets["raw_non_popular"]),
                "raw_with_fallback_hit": raw_hit_bool(target, candidate_sets["raw_with_fallback"]),
                "raw_pre_pool_hit": raw_hit,
                "pool100_hit": pool_hit,
                "pool200_hit": target in candidate_sets["pool200"],
                "topk_hit": topk_hit,
                "miss_stage": _target_stage(target, candidate_sets),
                "gap_reason": _gap_reason(raw_hit, pool_hit, topk_hit, has_title, has_category, has_behavior_seed),
                "category": str(metadata.get("category") or "unknown"),
                "popularity_bucket": diagnostics._bucket_popularity(metadata.get("popular_rank")),
                "is_long_tail": diagnostics._bucket_popularity(metadata.get("popular_rank")) in {"beyond_50", "not_in_popular_topn"},
                "has_title_metadata": has_title,
                "has_category_metadata": has_category,
                "has_behavior_seed": has_behavior_seed,
                "has_co_visit_opportunity": has_behavior_seed,
                "semantic_opportunity": bool(has_title or has_category),
                "category_long_tail_opportunity": bool(has_category and diagnostics._bucket_popularity(metadata.get("popular_rank")) in {"beyond_50", "not_in_popular_topn"}),
                "metadata_neighbor_opportunity": bool(has_title or has_category),
                "target_sources_json": json.dumps(target_sources, ensure_ascii=False),
            })
    return rows


def raw_hit_bool(target: str, ids: set[str]) -> bool:
    return target in ids


def _target_stage(target: str, candidate_sets: dict[str, set[str]]) -> str:
    if target in candidate_sets["topk"]:
        return "topk_hit"
    if target in candidate_sets["pool100"]:
        return "pool_has_target_topk_miss"
    if target in candidate_sets["raw_pre_pool"]:
        return "raw_has_target_pool_truncated"
    if target in candidate_sets["raw_with_fallback"]:
        return "raw_with_fallback_has_target_merge_filtered"
    if target in candidate_sets["raw_non_popular"]:
        return "raw_non_popular_has_target_fallback_or_merge_filtered"
    return "raw_stage_miss"


def _gap_reason(raw_hit: bool, pool_hit: bool, topk_hit: bool, has_title: bool, has_category: bool, has_behavior_seed: bool) -> str:
    if topk_hit:
        return "covered_topk"
    if pool_hit:
        return "ranking_gap_pool_has_target"
    if raw_hit:
        return "pool_truncation_gap"
    reasons = []
    if has_title or has_category:
        reasons.append("semantic_or_metadata_opportunity")
    if has_behavior_seed:
        reasons.append("behavior_neighbor_opportunity")
    return "+".join(reasons) or "unknown_gap"


def _target_sources(candidates: list[Any], target: str) -> list[str]:
    for candidate in candidates:
        if candidate.item_id == target:
            return sorted(set(candidate.sources))
    return []


def _source_gap_rows(miss_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counters: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for row in miss_rows:
        stage = str(row["miss_stage"])
        for opportunity in ["semantic_opportunity", "has_co_visit_opportunity", "category_long_tail_opportunity", "metadata_neighbor_opportunity"]:
            counters[(stage, opportunity)]["targets"] += 1
            counters[(stage, opportunity)]["opportunity_targets"] += int(bool(row[opportunity]))
    return [
        {
            "miss_stage": stage,
            "opportunity": opportunity,
            "targets": values["targets"],
            "opportunity_targets": values["opportunity_targets"],
            "opportunity_rate": round(values["opportunity_targets"] / values["targets"], 6) if values["targets"] else 0.0,
        }
        for (stage, opportunity), values in sorted(counters.items())
    ]


def _summary_rows(miss_rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    for row in miss_rows:
        value = str(row.get(key) or "unknown")
        counters[value]["targets"] += 1
        counters[value]["raw_pre_pool_hits"] += int(bool(row["raw_pre_pool_hit"]))
        counters[value]["pool100_hits"] += int(bool(row["pool100_hit"]))
        counters[value]["topk_hits"] += int(bool(row["topk_hit"]))
        counters[value]["raw_stage_misses"] += int(row["miss_stage"] == "raw_stage_miss")
    return [
        {
            key: value,
            "targets": counts["targets"],
            "raw_pre_pool_hits": counts["raw_pre_pool_hits"],
            "raw_pre_pool_hit_rate": round(counts["raw_pre_pool_hits"] / counts["targets"], 6) if counts["targets"] else 0.0,
            "pool100_hits": counts["pool100_hits"],
            "topk_hits": counts["topk_hits"],
            "raw_stage_misses": counts["raw_stage_misses"],
        }
        for value, counts in sorted(counters.items())
    ]


def _opportunity_summary(miss_rows: list[dict[str, Any]]) -> dict[str, Any]:
    opportunity_keys = ["semantic_opportunity", "has_co_visit_opportunity", "category_long_tail_opportunity", "metadata_neighbor_opportunity"]
    raw_misses = [row for row in miss_rows if row["miss_stage"] == "raw_stage_miss"]
    raw_miss_user_ids = {str(row["user_id"]) for row in raw_misses}
    metadata_opportunity_user_ids = {
        str(row["user_id"])
        for row in raw_misses
        if bool(row["metadata_neighbor_opportunity"])
    }
    co_visit_opportunity_user_ids = {
        str(row["user_id"])
        for row in raw_misses
        if bool(row["has_co_visit_opportunity"])
    }
    baseline_miss_users = len(raw_miss_user_ids)
    metadata_threshold = max(3, math.ceil(0.10 * baseline_miss_users)) if baseline_miss_users else 3
    co_visit_threshold = max(5, math.ceil(0.15 * baseline_miss_users)) if baseline_miss_users else 5
    metadata_users = len(metadata_opportunity_user_ids)
    co_visit_users = len(co_visit_opportunity_user_ids)
    return {
        "targets": len(miss_rows),
        "raw_stage_miss_targets": len(raw_misses),
        "baseline_miss_users": baseline_miss_users,
        "opportunities_on_raw_misses": {
            key: sum(int(bool(row[key])) for row in raw_misses)
            for key in opportunity_keys
        },
        "opportunity_users_on_raw_misses": {
            "metadata_neighbor_opportunity_users": metadata_users,
            "co_visit_opportunity_users": co_visit_users,
        },
        "opportunity_gate": {
            "metadata_neighbor_min_users": metadata_threshold,
            "co_visit_min_users": co_visit_threshold,
            "metadata_neighbor_gate_pass": metadata_users >= metadata_threshold,
            "co_visit_gate_pass": co_visit_users >= co_visit_threshold,
            "stop_loss_no_new_source": metadata_users < metadata_threshold and co_visit_users < co_visit_threshold,
            "counting_unit": "raw_stage_miss_users",
        },
        "priority_order": ["semantic_opportunity", "has_co_visit_opportunity", "category_long_tail_opportunity", "metadata_neighbor_opportunity"],
        "no_leakage_note": "Use these aggregate diagnostics to prioritize experiments only; do not use target ids for candidate generation, query construction, target-driven source index construction/filtering, candidate whitelist construction, or parameter selection. Static catalog item metadata may be indexed as train-visible item features when it is not derived from holdout labels.",
    }


def _ablation_base_phase_config(phase_config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in phase_config.items()
        if key not in {
            "co_visit_fallback_repair_enabled",
            "co_visit_seed_window",
            "co_visit_per_seed",
            "co_visit_per_user",
            "co_visit_min_score",
            "co_visit_max_item_user_freq",
            "co_visit_recency_decay",
            "category_long_tail_enabled",
            "category_long_tail_start_rank",
            "category_long_tail_per_user",
            "category_long_tail_per_category",
            "category_long_tail_seed_window",
            "metadata_neighbor_enabled",
            "metadata_neighbor_per_user",
            "metadata_neighbor_per_seed",
            "metadata_neighbor_seed_window",
            "metadata_neighbor_min_token_overlap",
            "metadata_neighbor_category_weight",
            "metadata_neighbor_max_bucket_candidates",
            "semantic_title_category_expansion",
        }
    }



def _source_aware_matrix(phase_config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    matrix = [
        ("score_sorted_all_sources", {}),
        ("source_balanced_fallback_preserving", _source_aware_budget_patch()),
    ]
    include = phase_config.get("source_aware_experiments")
    if include is None:
        return matrix
    include_set = {str(name) for name in include}
    return [(name, patch) for name, patch in matrix if name in include_set]



def _ablation_matrix(phase_config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    matrix = [
        ("baseline_only", {}),
        ("semantic_title_category", _semantic_patch()),
        ("co_visit_fallback", _co_visit_patch()),
        ("category_long_tail", _category_long_tail_patch()),
        ("metadata_neighbor", _metadata_neighbor_patch()),
        ("semantic_title_category_metadata_neighbor", _semantic_patch() | _metadata_neighbor_patch()),
    ]
    include = phase_config.get("ablation_experiments")
    if include is None:
        return matrix[:-1]
    include_set = {str(name) for name in include}
    return [(name, patch) for name, patch in matrix if name in include_set]


def _semantic_patch() -> dict[str, Any]:
    return {"semantic_title_category_expansion": {"enabled": True, "per_user": 20, "per_seed": 10, "seed_window": 20, "min_title_overlap": 1, "weak_categories": ["All Electronics", "Office Products", "Computers"]}}


def _co_visit_patch() -> dict[str, Any]:
    return {"co_visit_fallback_repair_enabled": True, "co_visit_seed_window": 20, "co_visit_per_seed": 20, "co_visit_per_user": 30, "co_visit_min_score": 1.0, "co_visit_max_item_user_freq": 50, "co_visit_recency_decay": 0.9}


def _category_long_tail_patch() -> dict[str, Any]:
    return {"category_long_tail_enabled": True, "category_long_tail_start_rank": 50, "category_long_tail_per_user": 30, "category_long_tail_seed_window": 20}


def _metadata_neighbor_patch() -> dict[str, Any]:
    return {"metadata_neighbor_enabled": True, "metadata_neighbor_per_user": 10, "metadata_neighbor_per_seed": 3, "metadata_neighbor_seed_window": 5, "metadata_neighbor_min_token_overlap": 1, "metadata_neighbor_max_bucket_candidates": 500}


def _graph_patch() -> dict[str, Any]:
    return {"item_graph_enabled": True, "item_graph_seed_window": 20, "item_graph_per_seed": 20, "item_graph_per_user": 30, "graph_walk_seed_enabled": False}


def _usercf_patch() -> dict[str, Any]:
    return {"usercf_enabled": True, "usercf_seed_window": 20, "usercf_similar_users": 30, "usercf_per_user": 30, "usercf_min_score": 0.0}


def _swing_patch() -> dict[str, Any]:
    return {"swing_enabled": True, "swing_seed_window": 20, "swing_per_seed": 20, "swing_per_user": 30, "swing_alpha": 1.0, "swing_min_score": 0.0}


def _session_transition_patch() -> dict[str, Any]:
    return {"session_transition_enabled": True, "session_transition_seed_window": 20, "session_transition_per_seed": 20, "session_transition_per_user": 30, "session_transition_recency_decay": 0.9, "session_transition_min_score": 1.0}


def _implicit_svd_patch() -> dict[str, Any]:
    return {"implicit_svd_enabled": True, "implicit_svd_factors": 16, "implicit_svd_per_user": 30, "implicit_svd_min_score": 0.0}


def _vector_two_tower_patch() -> dict[str, Any]:
    return {"two_tower_enabled": True, "two_tower_per_user": 30, "two_tower_seed_window": 50, "two_tower_min_overlap": 1, "two_tower_recency_decay": 0.85}


def _als_mf_dependency_gate_patch() -> dict[str, Any]:
    return {"als_mf_enabled": True, "als_mf_factors": 16, "als_mf_iterations": 10, "als_mf_regularization": 0.01, "als_mf_alpha": 1.0, "als_mf_per_user": 30, "als_mf_min_score": 0.0}


def _bpr_mf_dependency_gate_patch() -> dict[str, Any]:
    return {"bpr_mf_enabled": True, "bpr_mf_factors": 16, "bpr_mf_iterations": 10, "bpr_mf_regularization": 0.01, "bpr_mf_learning_rate": 0.01, "bpr_mf_per_user": 30, "bpr_mf_min_score": 0.0}


def _lightfm_mf_dependency_gate_patch() -> dict[str, Any]:
    return {
        "lightfm_enabled": True,
        "lightfm_components": 16,
        "lightfm_epochs": 5,
        "lightfm_loss": "logistic",
        "lightfm_learning_rate": 0.05,
        "lightfm_per_user": 30,
        "lightfm_min_score": -1.0,
    }


def _multi_interest_patch() -> dict[str, Any]:
    return {"multi_interest_enabled": True, "multi_interest_seed_window": 20, "multi_interest_per_seed": 20, "multi_interest_per_user": 30, "multi_interest_min_score": 1.0, "multi_interest_recency_decay": 0.9, "multi_interest_session_weight": 0.25}


def _behavior_untried_patch() -> dict[str, Any]:
    return _usercf_patch() | _swing_patch() | _session_transition_patch() | _implicit_svd_patch()


def _source_aware_source_patch() -> dict[str, Any]:
    return _semantic_patch() | _co_visit_patch() | _usercf_patch() | _swing_patch()



def _source_aware_budget_patch() -> dict[str, Any]:
    return {
        "candidate_pool_strategy": "balanced_source_budget",
        "candidate_source_minimums": {
            "semantic_title_category_expansion": 40,
            "co_visit_fallback_repair": 20,
            "usercf_recall": 10,
            "swing_recall": 10,
        },
        "candidate_source_maximums": {
            "popular": 40,
        },
        "candidate_fill_order": [
            "semantic_title_category_expansion",
            "co_visit_fallback_repair",
            "usercf_recall",
            "swing_recall",
            "itemcf",
            "category",
            "popular",
        ],
        "candidate_multi_source_boost": 0.1,
    }



def _all_source_patch() -> dict[str, Any]:
    return _semantic_patch() | _co_visit_patch() | _category_long_tail_patch() | _metadata_neighbor_patch() | _behavior_untried_patch() | _multi_interest_patch()


def _run_state(runs: dict[str, dict[str, Any]], inputs: dict[str, Any]) -> dict[str, Any]:
    positives = inputs["positives"]
    raw_hit_users = set()
    pool_hit_users = set()
    topk_hit_users = set()
    for user_id, run in runs.items():
        targets = positives.get(user_id, set())
        if not targets:
            continue
        raw_ids = diagnostics._candidate_ids(run["merged_before_pool_limit"])
        pool_ids = diagnostics._candidate_ids(run["pool_after_limit"])
        topk_ids = {item.get("parent_asin") for item in run["ranking"].items if item.get("parent_asin")}
        if targets & raw_ids:
            raw_hit_users.add(user_id)
        if targets & pool_ids:
            pool_hit_users.add(user_id)
        if targets & topk_ids:
            topk_hit_users.add(user_id)
    return {"raw_hit_users": raw_hit_users, "pool_hit_users": pool_hit_users, "topk_hit_users": topk_hit_users, "fallback_users": {user_id for user_id, run in runs.items() if run["fallback_used"]}}


def _summary_metrics_row(experiment_name: str, common: dict[str, Any], metrics: dict[str, Any], state: dict[str, Any], baseline_state: dict[str, Any]) -> dict[str, Any]:
    users = int(common["users_with_holdout"])
    raw_hit_users = len(state["raw_hit_users"])
    exclusive_users = state["pool_hit_users"] - baseline_state["pool_hit_users"]
    return {"experiment_name": experiment_name, "holdout_user_ids_hash": common["holdout_user_ids_hash"], "users_with_holdout": users, "raw_coverage_hit_users": raw_hit_users, "raw_coverage_hit_rate": round(raw_hit_users / users, 6) if users else 0.0, "candidate_hit_users": metrics.get("candidate_hit_users", 0), "candidate_hit_rate": metrics.get("candidate_hit_rate_at_pool", 0.0), "topk_hit_users": metrics.get("ranked_hit_users", 0), "topk_hit_rate": metrics.get("hit_rate_at_k", 0.0), "exclusive_hit_users": len(exclusive_users), "baseline_displacement_users": len(baseline_state["pool_hit_users"] - state["pool_hit_users"]), "candidate_volume_avg": metrics.get("candidate_count_avg", 0.0), "runtime_seconds": "", "fallback_error_count": 0, "fallback_rate": metrics.get("fallback_rate", 0.0)}


def _exclusive_hit_rows(experiment_name: str, runs: dict[str, dict[str, Any]], inputs: dict[str, Any], baseline_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    positives = inputs["positives"]
    for user_id, run in sorted(runs.items()):
        if user_id in baseline_state["pool_hit_users"]:
            continue
        targets = positives.get(user_id, set())
        hits = targets & diagnostics._candidate_ids(run["pool_after_limit"])
        for target in sorted(hits):
            rows.append({"experiment_name": experiment_name, "user_id": user_id, "target_item": target, "sources_json": json.dumps(_target_sources(run["pool_after_limit"], target), ensure_ascii=False)})
    return rows


def _overlap_matrix_rows(experiment_name: str, source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"experiment_name": experiment_name, **row} for row in source_rows]


def _baseline_displacement_rows(experiment_name: str, state: dict[str, Any], baseline_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for user_id in sorted(baseline_state["pool_hit_users"] - state["pool_hit_users"]):
        rows.append({"experiment_name": experiment_name, "user_id": user_id, "displacement_stage": "pool_hit_lost"})
    for user_id in sorted(baseline_state["topk_hit_users"] - state["topk_hit_users"]):
        rows.append({"experiment_name": experiment_name, "user_id": user_id, "displacement_stage": "topk_hit_lost"})
    return rows


def _validate_loaded_holdout(path_value: str, holdout_user_ids: list[str], holdout_hash: str) -> tuple[Path, str]:
    loaded_holdout_path = _resolve_path(path_value)
    loaded_holdout = _load_holdout_user_ids(loaded_holdout_path)
    loaded_hash = _holdout_user_ids_hash(loaded_holdout)
    if loaded_holdout != holdout_user_ids:
        raise ValueError("Loaded holdout user ids do not match the reproduced baseline denominator: " f"loaded_hash={loaded_hash} reproduced_hash={holdout_hash}")
    return loaded_holdout_path, loaded_hash


def _holdout_user_ids(inputs: dict[str, Any]) -> list[str]:
    positives = inputs["positives"]
    return sorted(sequence.get("user_id", "") for sequence in inputs["sequences"] if positives.get(sequence.get("user_id", "")))


def _holdout_user_ids_hash(user_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(user_ids)).encode("utf-8")).hexdigest()


def _load_holdout_user_ids(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return sorted(str(user_id) for user_id in payload)
    return sorted(str(user_id) for user_id in payload.get("holdout_user_ids", []))


def _assert_phase_output_dir(output_dir: Path) -> None:
    phase_root = _resolve_path(DEFAULT_OUTPUT_ROOT)
    if output_dir != phase_root and phase_root not in output_dir.parents:
        raise ValueError(f"Phase 1.21 outputs must be under {phase_root}; got {output_dir}")


def _assert_limit_users(limit_users: int, phase_config: dict[str, Any]) -> None:
    expected = int(phase_config.get("limit_users", REQUIRED_LIMIT_USERS))
    if limit_users != expected:
        raise ValueError(f"Phase 1.21 requires --limit-users {expected}; got {limit_users}")


def _assert_denominator(inputs: dict[str, Any], phase_config: dict[str, Any]) -> None:
    expected_users = int(phase_config.get("expected_users_with_holdout", REQUIRED_USERS_WITH_HOLDOUT))
    if inputs["evaluation_mode"] != REQUIRED_EVALUATION_MODE:
        raise ValueError(f"Phase 1.21 requires evaluation_mode={REQUIRED_EVALUATION_MODE}; got {inputs['evaluation_mode']}")
    if inputs["hit_rate_denominator"] != REQUIRED_DENOMINATOR:
        raise ValueError(f"Phase 1.21 requires hit_rate_denominator={REQUIRED_DENOMINATOR}; got {inputs['hit_rate_denominator']}")
    if inputs["users_with_holdout"] != expected_users:
        raise ValueError(f"Phase 1.21 requires users_with_holdout={expected_users}; got {inputs['users_with_holdout']}")


def _assert_disabled_ranking_routes(config: dict[str, Any]) -> None:
    violations = []
    for key in ["ltr_model", "ranking_v2", "item_feature_rerank", "source_aware_fusion"]:
        value = config.get(key) or {}
        if not isinstance(value, dict) or value.get("enabled") is not False:
            violations.append(f"{key}.enabled=false")
    if config.get("include_ranking_v2"):
        violations.append("include_ranking_v2 not enabled")
    if config.get("version") == "ltr_v2":
        violations.append('version != "ltr_v2"')
    if config.get("feature_version") == "ranking_v2":
        violations.append('feature_version != "ranking_v2"')
    if violations:
        raise ValueError("Phase 1.21 recall coverage must not enable ranking/rerank routes: " + ", ".join(violations))


def _assert_phase_source_features_safe(phase_config: dict[str, Any]) -> None:
    if "candidate_pool_size" in phase_config and int(phase_config["candidate_pool_size"]) <= 0:
        raise ValueError("Phase 1.21 candidate_pool_size must be positive")
    for key in ["miss_targets_path", "holdout_targets_path", "target_item_whitelist_path"]:
        if phase_config.get(key):
            raise ValueError(f"Phase 1.21 no-leakage contract forbids {key} in source generation config")



def _ranking_rerank_disabled_checks() -> dict[str, Any]:
    return {
        "ltr_model.enabled": False,
        "ranking_v2.enabled": False,
        "include_ranking_v2": "not enabled",
        "version": '!= "ltr_v2"',
        "feature_version": '!= "ranking_v2"',
        "item_feature_rerank.enabled": False,
        "source_aware_fusion.enabled": False,
    }


def _miss_stage_count(rows: list[dict[str, Any]], stage: str) -> int:
    for row in rows:
        if row.get("miss_stage") == stage:
            return int(row.get("user_count") or 0)
    return 0


def _stage_hit_users(rows: list[dict[str, Any]], stage: str) -> int:
    for row in rows:
        if row.get("stage") == stage:
            return int(row.get("hit_users") or 0)
    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _run_id(mode: str, config_path: Path, config_hash: str, limit_users: int) -> str:
    payload = f"phase_1_21|{mode}|{config_path}|{config_hash}|{limit_users}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


if __name__ == "__main__":
    main()
