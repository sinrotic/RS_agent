from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from rs_core.common.config import load_config
from rs_core.common.io import read_jsonl, write_json, write_jsonl
from rs_core.recsys.candidate_merge import (
    load_category_candidates,
    load_graph_walk_seed_recall,
    load_item_graph_recall,
    load_itemcf_by_source,
    load_popular_candidates,
    load_semantic_index,
    load_two_tower_index,
    load_two_tower_seed_recall,
    merge_for_user,
)
from rs_core.recsys.evaluation import evaluate, frozen_candidate_signature, heldout_positives, inspect_physical_ranking_pipeline_artifacts
from rs_core.recsys.ranking import rank_candidates
from rs_core.recsys.types import MergedCandidate
from rs_core.rsagent.decision import make_agent_decision
from rs_core.rsagent.feedback_rerank import apply_feedback_rerank
from rs_core.rsagent.inference_policy import RerankPolicyClient, apply_optional_inference_policy, resolve_inference_policy_config
from rs_core.rsagent.policy import apply_feedback_to_candidates, normalize_feedback_input, parse_feedback
from rs_core.rsagent.schema import FeedbackConstraints, RecommendationTurnResult

ROOT = Path(__file__).resolve().parents[2]


def run_hybrid_demo(
    config_path: str | Path,
    limit_users: int | None = None,
    inference_client: RerankPolicyClient | None = None,
    config_overrides: dict[str, Any] | None = None,
    feedback_constraints: FeedbackConstraints | None = None,
    feedback_text: str | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if config_overrides:
        config = _merge_nested(config, config_overrides)
    if feedback_constraints is None:
        feedback_constraints = _feedback_constraints_from_config(config, feedback_text)
    clean_dir = _resolve_path(config.get("clean_dir", "data/processed/amazon_2023_recall_clean_smoke_e2e"))
    views_dir = _resolve_path(config.get("views_dir", "data/processed/amazon_2023_recall_views_smoke_e2e"))
    output_dir = _resolve_path(config.get("output_dir", "outputs/hybrid_demo/hybrid_demo_small"))
    report_path = _resolve_path(config.get("report_path", "dic/HYBRID_DEMO_SMALL_REPORT.md"))

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

    popular = load_popular_candidates(paths["popular"], limit=int(config.get("popular_fallback_count", 50)))
    category_top = load_category_candidates(paths["category_top"])
    if "evaluation_mode" in config:
        configured_evaluation_mode = config.get("evaluation_mode")
        evaluation_mode = str(configured_evaluation_mode) if configured_evaluation_mode not in (None, "") else "public_serving"
        if evaluation_mode == "none":
            evaluation_mode = "public_serving"
    else:
        evaluation_mode = "valid_test"
    if evaluation_mode not in {"valid_test", "leave_one_positive_out", "public_serving"}:
        raise ValueError(f"Unsupported evaluation_mode: {evaluation_mode}")

    run_started_at = perf_counter()
    train_sequences = read_jsonl(paths["sequences"])
    if limit_users is not None:
        train_sequences = train_sequences[:limit_users]
    holdout = []
    lopo_stats: dict[str, int] = {}
    if evaluation_mode == "leave_one_positive_out":
        train_sequences, holdout, lopo_stats = _leave_one_positive_out_sequences(train_sequences)
    itemcf_seed_items = _itemcf_seed_items(train_sequences)
    itemcf_weak = load_itemcf_by_source(paths["itemcf_weak"], "itemcf_weak", itemcf_seed_items)
    itemcf_strong = load_itemcf_by_source(paths["itemcf_strong"], "itemcf_strong", itemcf_seed_items) if paths["itemcf_strong"].exists() else {}
    item_graph = load_item_graph_recall(paths["item_graph"], itemcf_seed_items) if config.get("item_graph_enabled") else {}
    graph_walk_seed = (
        load_graph_walk_seed_recall(paths["graph_walk_seed"], itemcf_seed_items, paths["graph_walk_seed_manifest"])
        if config.get("graph_walk_seed_enabled")
        else {}
    )
    two_tower_seed = (
        load_two_tower_seed_recall(
            paths["two_tower_seed"],
            itemcf_seed_items,
            paths.get("two_tower_seed_manifest") if config.get("fail_on_missing_sidecar") else None,
        )
        if config.get("two_tower_seed_enabled")
        else {}
    )
    item_category = _load_item_category(paths["category_items"])
    semantic_index = load_semantic_index(paths["semantic"], config.get("semantic_text_fields")) if config.get("semantic_enabled") or config.get("metadata_neighbor_enabled") else {}
    two_tower_index = (
        load_two_tower_index(paths["two_tower"], config.get("two_tower_text_fields"))
        if config.get("two_tower_enabled")
        else {}
    )

    candidates_by_user = {}
    rankings_by_user = {}
    fallback_users: set[str] = set()
    source_diagnostics = _source_diagnostics(train_sequences, itemcf_weak, itemcf_strong, item_graph, two_tower_seed, graph_walk_seed)
    recommendation_rows = []
    candidate_generation_latencies: list[float] = []
    ranking_latencies: list[float] = []
    recommendation_latencies: list[float] = []
    for sequence in train_sequences:
        user_id = sequence.get("user_id", "")
        result = recommend_for_user(
            sequence,
            popular,
            itemcf_weak,
            itemcf_strong,
            category_top,
            item_category,
            config,
            semantic_index,
            two_tower_index,
            item_graph,
            two_tower_seed,
            graph_walk_seed,
            feedback_constraints=feedback_constraints,
            inference_client=inference_client,
            turn_index=2 if feedback_constraints else 1,
        )
        candidates = result.candidates
        ranking = result.ranking
        decision = result.decision
        fallback_used = result.fallback_used
        candidates_by_user[user_id] = candidates
        rankings_by_user[user_id] = ranking
        if fallback_used:
            fallback_users.add(user_id)
        timing = result.diagnostics.get("timing", {})
        candidate_generation_latencies.append(float(timing.get("candidate_generation_seconds", 0.0)))
        ranking_latencies.append(float(timing.get("ranking_seconds", 0.0)))
        recommendation_latencies.append(float(timing.get("total_recommendation_seconds", 0.0)))
        row = decision.to_dict()
        row["candidate_count"] = len(candidates)
        row["diagnostics"] = result.diagnostics
        recommendation_rows.append(row)

    if evaluation_mode == "valid_test":
        for split_name in ("valid", "test"):
            path = clean_dir / f"canonical_interactions.{split_name}.jsonl"
            if path.exists():
                holdout.extend(read_jsonl(path))
    metrics = evaluate(candidates_by_user, rankings_by_user, holdout, config, fallback_users).to_dict()
    metrics["evaluation_mode"] = evaluation_mode
    metrics["source_diagnostics"] = source_diagnostics
    metrics["latency"] = _latency_summary(
        candidate_generation_latencies,
        ranking_latencies,
        recommendation_latencies,
        perf_counter() - run_started_at,
    )
    metrics["diagnostic_gate"] = _diagnostic_gate(metrics, config)
    if evaluation_mode == "leave_one_positive_out":
        metrics.update(lopo_stats)
    metrics["agent_evaluation_feedback"] = feedback_constraints.to_dict() if feedback_constraints else {}
    metrics["inference_policy"] = _mode_inference_summary(recommendation_rows)
    metrics["config_summary"] = _config_summary(config, clean_dir, views_dir, limit_users, evaluation_mode, lopo_stats)
    if evaluation_mode == "leave_one_positive_out":
        metrics["sample_limitations"].append(
            "Leave-one-positive-out is a demo internal train split; recall views may still be built from the full train artifact."
        )
        metrics["sample_limitations"].append(
            f"Leave-one-positive-out evaluated {lopo_stats.get('lopo_eligible_users', 0)} of "
            f"{lopo_stats.get('lopo_input_users', 0)} input users; "
            f"{lopo_stats.get('lopo_skipped_users_fewer_than_2_positives', 0)} users were skipped because they had fewer than 2 positives."
        )

    ranking_cases = _ranking_hit_cases(candidates_by_user, holdout, config)
    ranking_case_summary = _ranking_case_summary(ranking_cases)
    recommendations_path = output_dir / "recommendations.jsonl"
    metrics_path = output_dir / "metrics.json"
    ranking_cases_path = output_dir / "ranking_hit_cases.jsonl"
    ranking_case_summary_path = output_dir / "ranking_case_summary.json"
    recall_registry_artifact_path = output_dir / "recall_registry_artifact.json"
    source_coverage_path = output_dir / "recall_source_coverage.json"
    pool_curve_path = output_dir / "recall_pool_curve.json"
    latency_report_path = output_dir / "recall_latency_report.json"
    fallback_report_path = output_dir / "recall_fallback_report.json"
    overlap_report_path = output_dir / "recall_overlap_source_contribution.json"
    frozen_candidates_path = output_dir / "frozen_candidates.jsonl"
    ranking_stage_trace_path = output_dir / "ranking_stage_trace.jsonl"
    ranking_stage_summary_path = output_dir / "ranking_stage_summary.json"
    if config.get("export_frozen_candidates", False):
        frozen_rows = _frozen_candidate_export_rows(candidates_by_user)
        write_jsonl(frozen_candidates_path, frozen_rows)
        metrics["frozen_candidates_path"] = str(frozen_candidates_path)
        metrics["frozen_candidates_signature"] = frozen_candidate_signature(frozen_rows)
        metrics["config_summary"]["export_frozen_candidates"] = True
        metrics["config_summary"]["frozen_candidates_path"] = str(frozen_candidates_path)
    else:
        frozen_candidates_path = None
        metrics["config_summary"]["export_frozen_candidates"] = False
    if config.get("export_ranking_stage_artifacts", False):
        ranking_stage_trace_rows = _ranking_stage_trace_rows(candidates_by_user, config)
        ranking_stage_summary = _ranking_stage_summary(ranking_stage_trace_rows, config, ranking_stage_trace_path, ranking_stage_summary_path)
        write_jsonl(ranking_stage_trace_path, ranking_stage_trace_rows)
        write_json(ranking_stage_summary_path, ranking_stage_summary)
        metrics["ranking_stage_artifact_paths"] = {
            "trace": str(ranking_stage_trace_path),
            "summary": str(ranking_stage_summary_path),
        }
        metrics["ranking_stage_artifact_inspection"] = inspect_physical_ranking_pipeline_artifacts(ranking_stage_summary)
        metrics["config_summary"]["export_ranking_stage_artifacts"] = True
    else:
        metrics["config_summary"]["export_ranking_stage_artifacts"] = False
    promotion_artifact_paths = {
        "source_coverage": source_coverage_path,
        "pool_curve": pool_curve_path,
        "latency": latency_report_path,
        "fallback": fallback_report_path,
        "overlap_source_contribution": overlap_report_path,
    }
    write_jsonl(recommendations_path, recommendation_rows)
    write_jsonl(ranking_cases_path, ranking_cases)
    write_json(ranking_case_summary_path, ranking_case_summary)
    _write_recall_promotion_artifacts(metrics, promotion_artifact_paths)
    metrics["recall_registry_artifact_path"] = str(recall_registry_artifact_path)
    metrics["recall_promotion_artifact_paths"] = {name: str(path) for name, path in promotion_artifact_paths.items()}
    write_json(metrics_path, metrics)
    recall_registry_artifact = _recall_registry_artifact(config, metrics, metrics_path, frozen_candidates_path, promotion_artifact_paths)
    write_json(recall_registry_artifact_path, recall_registry_artifact)
    _write_report(report_path, config, metrics, recommendation_rows, ranking_case_summary)

    result = {
        "recommendations_path": str(recommendations_path),
        "metrics_path": str(metrics_path),
        "ranking_cases_path": str(ranking_cases_path),
        "ranking_case_summary_path": str(ranking_case_summary_path),
        "recall_registry_artifact_path": str(recall_registry_artifact_path),
        "recall_promotion_artifact_paths": {name: str(path) for name, path in promotion_artifact_paths.items()},
        "report_path": str(report_path),
        "metrics": metrics,
    }
    if frozen_candidates_path is not None:
        result["frozen_candidates_path"] = str(frozen_candidates_path)
    if config.get("export_ranking_stage_artifacts", False):
        result["ranking_stage_trace_path"] = str(ranking_stage_trace_path)
        result["ranking_stage_summary_path"] = str(ranking_stage_summary_path)
    return result


def run_qwen_evaluation_harness(
    config_path: str | Path,
    limit_users: int | None = None,
    inference_client: RerankPolicyClient | None = None,
    feedback_text: str = "I prefer Audio and bluetooth",
    output_dir: str | Path | None = None,
    qwen_model_id: str | None = None,
    qwen_max_new_tokens: int | None = None,
) -> dict[str, Any]:
    base_config = load_config(config_path)
    base_output_dir = _resolve_path(output_dir or base_config.get("evaluation_harness_output_dir", "outputs/agent/qwen/qwen_evaluation_harness"))
    feedback_constraints = parse_feedback(normalize_feedback_input(feedback_text))
    feedback_defaults = _feedback_evaluation_defaults(base_config)
    qwen_overrides = _merge_nested(_qwen_evaluation_defaults(base_config), feedback_defaults)
    if qwen_model_id:
        qwen_overrides.setdefault("inference_policy", {}).setdefault("model", {})["model_id"] = qwen_model_id
    if qwen_max_new_tokens is not None:
        qwen_overrides.setdefault("inference_policy", {}).setdefault("model", {})["max_new_tokens"] = qwen_max_new_tokens
    qwen_client = inference_client or _build_harness_inference_client(base_config, qwen_overrides)
    mode_specs = [
        ("deterministic_baseline", {"inference_policy": {"enabled": False}, "rerank_policy": {"enabled": False}}, None, None),
        ("rule_feedback_rerank", _merge_nested({"inference_policy": {"enabled": False}}, feedback_defaults), feedback_constraints, None),
        ("qwen_feedback_rerank", qwen_overrides, feedback_constraints, qwen_client),
    ]
    mode_results: dict[str, Any] = {}
    for mode_name, overrides, constraints, client in mode_specs:
        report_path = base_output_dir / mode_name / "report.md"
        mode_overrides = _merge_nested(
            overrides,
            {
                "output_dir": str(base_output_dir / mode_name),
                "report_path": str(report_path),
                "strategy_name": f"evaluation_{mode_name}",
            },
        )
        mode_results[mode_name] = run_hybrid_demo(
            config_path,
            limit_users=limit_users,
            inference_client=client,
            config_overrides=mode_overrides,
            feedback_constraints=constraints,
        )
    comparison = _evaluation_comparison(mode_results, feedback_text)
    comparison_path = base_output_dir / "comparison.json"
    report_path = base_output_dir / "comparison.md"
    write_json(comparison_path, comparison)
    report_path.write_text(_evaluation_comparison_report(comparison), encoding="utf-8")
    return {
        "comparison_path": str(comparison_path),
        "report_path": str(report_path),
        "modes": {mode: {key: value for key, value in result.items() if key != "metrics"} for mode, result in mode_results.items()},
        "comparison": comparison,
    }


def _build_harness_inference_client(config: dict[str, Any], config_overrides: dict[str, Any]) -> RerankPolicyClient | None:
    policy = resolve_inference_policy_config(_merge_nested(config, config_overrides))
    if not policy.get("enabled") or policy.get("provider") != "local_transformers":
        return None
    from rs_core.rsagent.qwen_client import QwenLocalClient

    return QwenLocalClient(policy)


def _feedback_constraints_from_config(config: dict[str, Any], feedback_text: str | None) -> FeedbackConstraints | None:
    text = feedback_text if feedback_text is not None else config.get("evaluation_feedback")
    if not text:
        return None
    return parse_feedback(normalize_feedback_input(str(text)))


def _recall_registry_artifact(
    config: dict[str, Any],
    metrics: dict[str, Any],
    metrics_path: Path,
    frozen_candidates_path: Path | None,
    artifact_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    promotion_artifacts = _recall_promotion_artifacts(metrics, frozen_candidates_path, artifact_paths or {})
    missing_promotion_artifacts = [
        name for name, artifact in promotion_artifacts.items()
        if not artifact.get("available")
    ]
    missing_promotion_next_actions = {
        name: artifact.get("next_action", "Produce and attach the missing recall promotion artifact before promotion.")
        for name, artifact in promotion_artifacts.items()
        if not artifact.get("available")
    }
    gate_status = "INCONCLUSIVE_MISSING_ARTIFACT" if missing_promotion_artifacts else "PASS_OBSERVATION_ONLY"
    allowed_metrics = [
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
        "fallback_success_rate",
        "candidate_generation_latency_p50",
        "candidate_generation_latency_p95",
        "candidate_generation_latency_p99",
        "artifact_completeness",
        "reproducibility",
        "leakage_risk",
    ]
    forbidden_metrics = [
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
    diagnostic_only_metrics = ["hit_rate_at_k", "ndcg_at_k", "mrr_at_k", "map_at_k", "candidate_hit_missed_topk_users"]
    diagnostic_excluded_metrics = ["topk_hit_rate", "topk_hit_users", "ranking_gap_pool_has_target", "ltr_score", "rerank_score", "ctr", "cvr", "gmv"]
    method_card_evidence = _method_card_evidence(config, metrics)
    return {
        "schema_version": "recall_experiment_registry_artifact_v1",
        "schema_path": ".omc/recall/schema/recall_experiment_registry.schema.yaml",
        "source_registry_path": ".omc/recall/registry/source_group_registry.yaml",
        "experiment_id": str(config.get("strategy_name") or "hybrid_demo_recall_observation"),
        "method_family": "hybrid_merge",
        "source_group": "hybrid_merge",
        "source_name": "hybrid_merge",
        "lane": "observation",
        "scope_contract": "recall_only",
        "promotion_scope": "recall_only_candidate_pool_default",
        "evaluation_contract": str(metrics.get("evaluation_mode") or metrics.get("config_summary", {}).get("evaluation_mode") or "unknown"),
        "candidate_pool_size": int(config.get("candidate_pool_size", 50)),
        "input_signature": {
            "evaluation_mode": metrics.get("evaluation_mode"),
            "users_total": metrics.get("users_total"),
            "users_with_holdout": metrics.get("users_with_holdout"),
            "hit_rate_denominator": metrics.get("hit_rate_denominator", "users_with_holdout"),
        },
        "artifact_signature": {
            "metrics_json_sha256": _sha256_file(metrics_path),
            "frozen_candidates_jsonl_sha256": _sha256_file(frozen_candidates_path) if frozen_candidates_path else None,
        },
        "method_card_evidence": method_card_evidence,
        "canonical_baseline": method_card_evidence["canonical_baseline"],
        "baseline_vs_source": method_card_evidence["baseline_vs_source"],
        "evidence_level": method_card_evidence["evidence_level"],
        "experiment_scope": method_card_evidence["experiment_scope"],
        "pool_displacement_risk": method_card_evidence["pool_displacement_risk"],
        "source_candidate_counts": method_card_evidence["source_candidate_counts"],
        "legacy_migration": method_card_evidence["legacy_migration"],
        "promotion_blockers": method_card_evidence["promotion_blockers"],
        "promotion_required_artifacts": promotion_artifacts,
        "allowed_metrics": allowed_metrics,
        "diagnostic_only_metrics": diagnostic_only_metrics,
        "diagnostic_excluded_metrics": diagnostic_excluded_metrics,
        "forbidden_metrics": forbidden_metrics,
        "metrics_path": str(metrics_path),
        "frozen_candidates_path": str(frozen_candidates_path) if frozen_candidates_path else None,
        "missing_promotion_required_artifacts": missing_promotion_artifacts,
        "missing_promotion_next_actions": missing_promotion_next_actions,
        "gate_status": gate_status,
        "decision_reason": "Hybrid workflow emits a recall-only registry artifact; promotion requires complete frozen candidates, source ablation, latency, fallback, and overlap/source contribution evidence without ranking or online business metrics.",
        "rollback_baseline": gate_status != "PASS_OBSERVATION_ONLY",
    }


def _method_card_evidence(config: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    canonical_baseline = "semantic_title_category_expansion"
    source_name = str(config.get("source_name") or config.get("strategy_name") or "hybrid_merge")
    candidate_pool_size = int(config.get("candidate_pool_size", 50))
    before_cap = _source_candidate_counts_before_cap(metrics)
    after_cap = dict(metrics.get("source_item_coverage", {}) or {})
    pool_displacement_risk = str(config.get("pool_displacement_risk", "unknown"))
    promotion_blockers = []
    if pool_displacement_risk == "unknown":
        promotion_blockers.append("pool_displacement_risk_unknown")
    return {
        "schema_version": "recall_method_card_evidence_v1",
        "canonical_baseline": canonical_baseline,
        "baseline_vs_source": {
            "baseline_source_name": canonical_baseline,
            "source_name": source_name,
            "comparison_scope": "candidate_pool_recall_only",
            "candidate_pool_size": candidate_pool_size,
            "recall_only_metrics": {
                "candidate_hit_rate_at_pool": metrics.get("candidate_hit_rate_at_pool"),
                "recall_at_pool": metrics.get("recall_at_pool"),
                "candidate_hit_users": metrics.get("candidate_hit_users"),
                "empty_candidate_rate": metrics.get("empty_candidate_rate"),
                "fallback_rate": metrics.get("fallback_rate"),
            },
        },
        "evidence_level": str(config.get("evidence_level", "observation")),
        "experiment_scope": str(config.get("experiment_scope", metrics.get("evaluation_mode", "unknown"))),
        "pool_displacement_risk": pool_displacement_risk,
        "source_candidate_counts": {
            "before_cap": before_cap,
            "after_cap": after_cap,
            "candidate_pool_size": candidate_pool_size,
        },
        "legacy_migration": {
            "legacy_source_name": config.get("legacy_source_name"),
            "legacy_artifact_path": config.get("legacy_artifact_path"),
            "migration_status": str(config.get("legacy_migration_status", "not_declared")),
            "migration_notes": str(config.get("legacy_migration_notes", "")),
        },
        "promotion_blockers": promotion_blockers,
    }



def _source_candidate_counts_before_cap(metrics: dict[str, Any]) -> dict[str, int]:
    diagnostics = dict(metrics.get("source_diagnostics", {}) or {})
    mapping = {
        "itemcf": "itemcf_raw_unseen_candidates",
        "item_graph": "item_graph_raw_unseen_candidates",
        "two_tower_seed": "two_tower_seed_raw_unseen_candidates",
        "graph_walk_seed": "graph_walk_seed_raw_unseen_candidates",
    }
    counts = {
        source: int(diagnostics[key])
        for source, key in mapping.items()
        if key in diagnostics
    }
    for source, count in (metrics.get("recall_source_coverage", {}) or {}).items():
        counts.setdefault(str(source), int(count))
    return dict(sorted(counts.items()))



def _recall_promotion_artifacts(
    metrics: dict[str, Any],
    frozen_candidates_path: Path | None,
    artifact_paths: dict[str, Path],
) -> dict[str, dict[str, Any]]:
    latency = metrics.get("latency") if isinstance(metrics.get("latency"), dict) else {}
    source_overlap = metrics.get("source_overlap") if isinstance(metrics.get("source_overlap"), dict) else {}
    source_contribution = {
        "candidate_hit_source_coverage": metrics.get("candidate_hit_source_coverage"),
        "per_source_candidate_contribution": metrics.get("per_source_candidate_contribution"),
        "source_marginal_candidate_hit_users": metrics.get("source_marginal_candidate_hit_users"),
        "source_marginal_candidate_hit_rate": metrics.get("source_marginal_candidate_hit_rate"),
    }
    return {
        "frozen_candidates": {
            "available": frozen_candidates_path is not None and frozen_candidates_path.exists(),
            "path": str(frozen_candidates_path) if frozen_candidates_path else None,
            "sha256": _sha256_file(frozen_candidates_path),
            "signature": metrics.get("frozen_candidates_signature"),
        },
        "ablation": {
            "available": False,
            "path": None,
            "sha256": None,
            "metrics": source_contribution,
            "reason": "Dedicated leave-one-source-out ablation is not produced by run_hybrid_demo.",
            "next_action": "Run the dedicated recall ablation workflow and attach its evidence manifest before promotion.",
        },
        "latency": {
            "available": "candidate_generation_p95_seconds" in latency and _path_exists(artifact_paths.get("latency")),
            "path": _path_string(artifact_paths.get("latency")),
            "sha256": _sha256_file(artifact_paths.get("latency")),
            "metrics": {
                "candidate_generation_avg_seconds": latency.get("candidate_generation_avg_seconds"),
                "candidate_generation_p95_seconds": latency.get("candidate_generation_p95_seconds"),
            },
        },
        "fallback": {
            "available": metrics.get("fallback_rate") is not None and _path_exists(artifact_paths.get("fallback")),
            "path": _path_string(artifact_paths.get("fallback")),
            "sha256": _sha256_file(artifact_paths.get("fallback")),
            "metrics": {
                "fallback_rate": metrics.get("fallback_rate"),
                "empty_candidate_users": metrics.get("empty_candidate_users"),
                "empty_candidate_rate": metrics.get("empty_candidate_rate"),
            },
        },
        "overlap_source_contribution": {
            "available": bool(source_overlap) and _path_exists(artifact_paths.get("overlap_source_contribution")),
            "path": _path_string(artifact_paths.get("overlap_source_contribution")),
            "sha256": _sha256_file(artifact_paths.get("overlap_source_contribution")),
            "metrics": {
                "source_overlap": source_overlap,
                "source_user_coverage": metrics.get("source_user_coverage"),
                "source_item_coverage": metrics.get("source_item_coverage"),
                "recall_source_coverage": metrics.get("recall_source_coverage"),
            },
        },
    }


def _write_recall_promotion_artifacts(metrics: dict[str, Any], artifact_paths: dict[str, Path]) -> None:
    source_coverage = {
        "source_user_coverage": metrics.get("source_user_coverage"),
        "source_item_coverage": metrics.get("source_item_coverage"),
        "recall_source_coverage": metrics.get("recall_source_coverage"),
        "candidate_hit_source_coverage": metrics.get("candidate_hit_source_coverage"),
        "per_source_candidate_contribution": metrics.get("per_source_candidate_contribution"),
    }
    pool_curve = {
        "candidate_hit_rate_at_cutoffs": metrics.get("candidate_hit_rate_at_cutoffs"),
        "candidate_recall_at_cutoffs": metrics.get("candidate_recall_at_cutoffs"),
        "source_marginal_candidate_hit_users": metrics.get("source_marginal_candidate_hit_users"),
        "source_marginal_candidate_hit_rate": metrics.get("source_marginal_candidate_hit_rate"),
    }
    latency = {
        "candidate_generation_avg_seconds": (metrics.get("latency") or {}).get("candidate_generation_avg_seconds"),
        "candidate_generation_p95_seconds": (metrics.get("latency") or {}).get("candidate_generation_p95_seconds"),
    }
    fallback = {
        "fallback_rate": metrics.get("fallback_rate"),
        "empty_candidate_users": metrics.get("empty_candidate_users"),
        "empty_candidate_rate": metrics.get("empty_candidate_rate"),
    }
    overlap = {
        "source_overlap": metrics.get("source_overlap"),
        "source_user_coverage": metrics.get("source_user_coverage"),
        "source_item_coverage": metrics.get("source_item_coverage"),
        "recall_source_coverage": metrics.get("recall_source_coverage"),
    }
    payloads = {
        "source_coverage": source_coverage,
        "pool_curve": pool_curve,
        "latency": latency,
        "fallback": fallback,
        "overlap_source_contribution": overlap,
    }
    for name, payload in payloads.items():
        path = artifact_paths.get(name)
        if path is not None:
            write_json(path, payload)


def _path_exists(path: Path | None) -> bool:
    return path is not None and path.exists()


def _path_string(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _qwen_evaluation_defaults(config: dict[str, Any]) -> dict[str, Any]:
    configured = dict(config.get("inference_policy", {}) or {})
    model = dict(configured.get("model", {}) or {})
    prompt = dict(configured.get("prompt", {}) or {})
    signals = dict(configured.get("signals", {}) or {})
    model.setdefault("max_new_tokens", 256)
    model.setdefault("do_sample", False)
    prompt.setdefault("max_candidates", 5)
    prompt.setdefault("metadata_fields", ["title_clean", "category", "main_category"])
    prompt.setdefault("max_metadata_chars_per_field", 120)
    signals.setdefault("max_signals", 1)
    return {
        "inference_policy": {
            **configured,
            "enabled": True,
            "model": model,
            "prompt": prompt,
            "signals": signals,
        }
    }


def _feedback_evaluation_defaults(config: dict[str, Any]) -> dict[str, Any]:
    rank_weights = dict(config.get("rank_weights", {}))
    rank_weights.setdefault("feedback_category", 10.0)
    rank_weights.setdefault("feedback_keyword", 10.0)
    rank_weights.setdefault("feedback_keyword_penalty", 10.0)
    rank_weights.setdefault("feedback_model_rerank", 10.0)
    return {
        "feedback_category_boost": config.get("feedback_category_boost", 1.0),
        "feedback_keyword_boost": config.get("feedback_keyword_boost", 1.0),
        "feedback_keyword_penalty": config.get("feedback_keyword_penalty", 1.0),
        "rank_weights": rank_weights,
    }


def _mode_inference_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summaries = [row.get("diagnostics", {}).get("inference_policy", {}) for row in rows]
    accepted = sum(int(summary.get("accepted_signal_count", 0) or 0) for summary in summaries)
    rejected = sum(int(summary.get("rejected_signal_count", 0) or 0) for summary in summaries)
    fallback_count = sum(1 for summary in summaries if summary.get("fallback_used"))
    routes = Counter(str(summary.get("route", "missing")) for summary in summaries)
    model_ids = sorted({str(summary.get("model_id")) for summary in summaries if summary.get("model_id")})
    return {
        "accepted_signal_count": accepted,
        "rejected_signal_count": rejected,
        "fallback_count": fallback_count,
        "routes": dict(sorted(routes.items())),
        "model_ids": model_ids,
    }


def _evaluation_comparison(mode_results: dict[str, dict[str, Any]], feedback_text: str) -> dict[str, Any]:
    metric_keys = [
        "hit_rate_at_k",
        "candidate_hit_rate_at_pool",
        "ranked_hit_users",
        "candidate_hit_users",
        "fallback_rate",
        "candidate_count_avg",
        "category_diversity_avg",
    ]
    modes: dict[str, Any] = {}
    for mode, result in mode_results.items():
        metrics = result.get("metrics", {})
        modes[mode] = {
            "metrics": {key: metrics.get(key) for key in metric_keys},
            "agent_evaluation_feedback": metrics.get("agent_evaluation_feedback", {}),
            "inference_policy": metrics.get("inference_policy", {}),
            "paths": {key: value for key, value in result.items() if key.endswith("_path")},
        }
    return {
        "feedback_text": feedback_text,
        "mode_order": list(mode_results.keys()),
        "modes": modes,
        "rank_delta": _evaluation_rank_delta_summary(mode_results),
    }


def _evaluation_rank_delta_summary(mode_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cases_by_mode = {
        mode: _ranking_cases_by_key(read_jsonl(result["ranking_cases_path"]))
        for mode, result in mode_results.items()
        if result.get("ranking_cases_path")
    }
    baseline = cases_by_mode.get("deterministic_baseline", {})
    qwen = cases_by_mode.get("qwen_feedback_rerank", {})
    rule = cases_by_mode.get("rule_feedback_rerank", {})
    rank_deltas: list[int] = []
    rule_rank_deltas: list[int] = []
    improved = worsened = unchanged = 0
    topk_gained = topk_lost = 0
    signal_on_target = 0
    signal_on_non_target = 0
    non_target_signal_above_target = 0
    harmful_non_target_signal_cases = 0
    examples: list[dict[str, Any]] = []
    for key, qwen_case in sorted(qwen.items()):
        base_case = baseline.get(key)
        if not base_case:
            continue
        base_rank = int(base_case.get("target_rank", 0) or 0)
        qwen_rank = int(qwen_case.get("target_rank", 0) or 0)
        if not base_rank or not qwen_rank:
            continue
        delta = base_rank - qwen_rank
        rank_deltas.append(delta)
        if delta > 0:
            improved += 1
        elif delta < 0:
            worsened += 1
        else:
            unchanged += 1
        if not base_case.get("is_topk_hit") and qwen_case.get("is_topk_hit"):
            topk_gained += 1
        if base_case.get("is_topk_hit") and not qwen_case.get("is_topk_hit"):
            topk_lost += 1
        rule_case = rule.get(key)
        if rule_case:
            rule_rank = int(rule_case.get("target_rank", 0) or 0)
            if rule_rank:
                rule_rank_deltas.append(rule_rank - qwen_rank)
        target_has_signal = _case_target_has_qwen_signal(qwen_case)
        non_target_signal_count = _case_non_target_qwen_signal_count(qwen_case)
        if target_has_signal:
            signal_on_target += 1
        if non_target_signal_count:
            signal_on_non_target += 1
            non_target_signal_above_target += non_target_signal_count
            if delta <= 0:
                harmful_non_target_signal_cases += 1
        examples.append({
            "user_id": qwen_case.get("user_id"),
            "target_item": qwen_case.get("target_item"),
            "deterministic_rank": base_rank,
            "rule_rank": int(rule_case.get("target_rank", 0) or 0) if rule_case else None,
            "qwen_rank": qwen_rank,
            "rank_improvement_delta": delta,
            "qwen_topk_hit": bool(qwen_case.get("is_topk_hit")),
            "qwen_signal_on_target": target_has_signal,
            "qwen_non_target_signals_above_target": non_target_signal_count,
        })
    return {
        "baseline_mode": "deterministic_baseline",
        "qwen_mode": "qwen_feedback_rerank",
        "comparable_cases": len(rank_deltas),
        "target_rank_improved_count": improved,
        "target_rank_worsened_count": worsened,
        "target_rank_unchanged_count": unchanged,
        "target_rank_delta_avg": _avg([float(value) for value in rank_deltas]),
        "target_rank_delta_vs_rule_avg": _avg([float(value) for value in rule_rank_deltas]),
        "topk_gained_count": topk_gained,
        "topk_lost_count": topk_lost,
        "qwen_signal_on_target_count": signal_on_target,
        "qwen_signal_on_non_target_count": signal_on_non_target,
        "qwen_non_target_signals_above_target_count": non_target_signal_above_target,
        "harmful_non_target_signal_cases": harmful_non_target_signal_cases,
        "examples": examples[:10],
    }


def _ranking_cases_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("user_id", "")), str(row.get("target_item", ""))): row
        for row in rows
        if row.get("user_id") and row.get("target_item")
    }


def _case_target_has_qwen_signal(row: dict[str, Any]) -> bool:
    target = row.get("target_item")
    for item in row.get("top_items", []):
        if item.get("parent_asin") == target:
            return _item_has_qwen_signal(item)
    return "feedback_model_rerank" in set(row.get("target_sources", []))


def _case_non_target_qwen_signal_count(row: dict[str, Any]) -> int:
    target = row.get("target_item")
    return sum(
        1
        for item in row.get("items_above_target", [])
        if item.get("parent_asin") != target and _item_has_qwen_signal(item)
    )


def _item_has_qwen_signal(item: dict[str, Any]) -> bool:
    return any(event.get("type") == "qwen_rerank_signal" for event in item.get("rerank_events", []))


def _evaluation_comparison_report(comparison: dict[str, Any]) -> str:
    metric_keys = [
        "hit_rate_at_k",
        "candidate_hit_rate_at_pool",
        "ranked_hit_users",
        "candidate_hit_users",
        "fallback_rate",
        "candidate_count_avg",
        "category_diversity_avg",
    ]
    lines = [
        "# Qwen Evaluation Harness Comparison",
        "",
        "## Scope",
        "",
        "Compares deterministic baseline, deterministic feedback rerank, and optional Qwen feedback rerank over the same recommendation inputs.",
        "",
        f"- feedback_text: `{comparison.get('feedback_text', '')}`",
        "",
        "## Metrics",
        "",
        "| Mode | " + " | ".join(metric_keys) + " |",
        "| --- | " + " | ".join("---" for _ in metric_keys) + " |",
    ]
    for mode in comparison.get("mode_order", []):
        metrics = comparison.get("modes", {}).get(mode, {}).get("metrics", {})
        lines.append("| " + mode + " | " + " | ".join(str(metrics.get(key)) for key in metric_keys) + " |")
    rank_delta = comparison.get("rank_delta", {})
    lines.extend([
        "",
        "## Rank Delta Summary",
        "",
        f"- comparable_cases: {rank_delta.get('comparable_cases')}",
        f"- target_rank_improved_count: {rank_delta.get('target_rank_improved_count')}",
        f"- target_rank_worsened_count: {rank_delta.get('target_rank_worsened_count')}",
        f"- target_rank_unchanged_count: {rank_delta.get('target_rank_unchanged_count')}",
        f"- target_rank_delta_avg: {rank_delta.get('target_rank_delta_avg')}",
        f"- topk_gained_count: {rank_delta.get('topk_gained_count')}",
        f"- topk_lost_count: {rank_delta.get('topk_lost_count')}",
        f"- qwen_signal_on_target_count: {rank_delta.get('qwen_signal_on_target_count')}",
        f"- qwen_signal_on_non_target_count: {rank_delta.get('qwen_signal_on_non_target_count')}",
        f"- harmful_non_target_signal_cases: {rank_delta.get('harmful_non_target_signal_cases')}",
        "",
        "| User | Target | deterministic_rank | rule_rank | qwen_rank | rank_improvement_delta | signal_on_target | non_target_signals_above |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for example in rank_delta.get("examples", []):
        lines.append(
            f"| {example.get('user_id')} | {example.get('target_item')} | "
            f"{example.get('deterministic_rank')} | {example.get('rule_rank')} | {example.get('qwen_rank')} | "
            f"{example.get('rank_improvement_delta')} | {example.get('qwen_signal_on_target')} | "
            f"{example.get('qwen_non_target_signals_above_target')} |"
        )
    lines.extend([
        "",
        "## Inference Policy Diagnostics",
        "",
        "| Mode | accepted_signals | rejected_signals | fallback_count | routes |",
        "| --- | --- | --- | --- | --- |",
    ])
    for mode in comparison.get("mode_order", []):
        policy = comparison.get("modes", {}).get(mode, {}).get("inference_policy", {})
        lines.append(
            f"| {mode} | {policy.get('accepted_signal_count')} | {policy.get('rejected_signal_count')} | "
            f"{policy.get('fallback_count')} | `{json.dumps(policy.get('routes', {}), ensure_ascii=False)}` |"
        )
    lines.extend(["", "## Artifacts", ""])
    for mode in comparison.get("mode_order", []):
        paths = comparison.get("modes", {}).get(mode, {}).get("paths", {})
        lines.append(f"### {mode}")
        lines.append("")
        for key, value in sorted(paths.items()):
            lines.append(f"- {key}: `{value}`")
        lines.append("")
    return "\n".join(lines)


def recommend_for_user(
    user_sequence: dict[str, Any],
    popular: list[Any],
    itemcf_weak: dict[str, list[Any]],
    itemcf_strong: dict[str, list[Any]],
    category_top: dict[str, list[Any]],
    item_category: dict[str, str],
    config: dict[str, Any],
    semantic_index: dict[str, dict[str, Any]] | None = None,
    two_tower_index: dict[str, dict[str, Any]] | None = None,
    item_graph: dict[str, list[Any]] | None = None,
    two_tower_seed: dict[str, list[Any]] | None = None,
    graph_walk_seed: dict[str, list[Any]] | None = None,
    feedback_constraints: FeedbackConstraints | None = None,
    prior_turn_items: set[str] | None = None,
    inference_client: RerankPolicyClient | None = None,
    turn_index: int | None = None,
    extra_candidates: list[MergedCandidate] | None = None,
) -> RecommendationTurnResult:
    user_id = user_sequence.get("user_id", "")
    started_at = perf_counter()
    candidate_started_at = perf_counter()
    candidates, fallback_used = merge_for_user(
        user_sequence,
        popular,
        itemcf_weak,
        itemcf_strong,
        category_top,
        item_category,
        config,
        semantic_index,
        two_tower_index,
        item_graph,
        two_tower_seed,
        graph_walk_seed,
    )
    if extra_candidates:
        candidates = _merge_extra_candidates(candidates, extra_candidates)
    candidates, feedback_diagnostics = apply_feedback_to_candidates(
        candidates, feedback_constraints, config, prior_turn_items
    )
    candidates, feedback_rerank_diagnostics = apply_feedback_rerank(
        candidates, feedback_constraints, itemcf_weak, itemcf_strong, config, turn_index
    )
    candidates, inference_diagnostics = apply_optional_inference_policy(
        user_sequence=user_sequence,
        candidates=candidates,
        feedback_constraints=feedback_constraints,
        config=config,
        client=inference_client,
        turn_index=turn_index,
    )
    candidate_generation_seconds = perf_counter() - candidate_started_at
    ranking_started_at = perf_counter()
    ranking = rank_candidates(user_id, candidates, config)
    ranking_seconds = perf_counter() - ranking_started_at
    ranking.fallback_used = fallback_used
    diagnostics = {
        "candidate_count": len(candidates),
        "source_coverage": _candidate_source_coverage(candidates),
        "timing": {
            "candidate_generation_seconds": round(candidate_generation_seconds, 6),
            "ranking_seconds": round(ranking_seconds, 6),
            "total_recommendation_seconds": round(perf_counter() - started_at, 6),
        },
        **_internal_fallback_diagnostics(candidates),
        **feedback_diagnostics,
        **feedback_rerank_diagnostics,
        **inference_diagnostics,
    }
    decision = make_agent_decision(user_id, ranking, config, diagnostics)
    return RecommendationTurnResult(
        candidates=candidates,
        ranking=ranking,
        decision=decision,
        fallback_used=fallback_used,
        diagnostics=diagnostics,
    )


def _merge_extra_candidates(
    candidates: list[MergedCandidate],
    extra_candidates: list[MergedCandidate],
) -> list[MergedCandidate]:
    merged: dict[str, MergedCandidate] = {candidate.item_id: candidate for candidate in candidates}
    for extra in extra_candidates:
        if not extra.item_id:
            continue
        current = merged.get(extra.item_id)
        if current is None:
            merged[extra.item_id] = extra
            continue
        for source in extra.sources:
            if source not in current.sources:
                current.sources.append(source)
            current.source_scores[source] = max(
                float(current.source_scores.get(source, 0.0)),
                float(extra.source_scores.get(source, 0.0)),
            )
        if not current.category:
            current.category = extra.category
        current.metadata.update({key: value for key, value in extra.metadata.items() if key not in current.metadata})
    return list(merged.values())


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _candidate_source_coverage(candidates: list[Any]) -> dict[str, int]:
    coverage: Counter[str] = Counter()
    for candidate in candidates:
        for source in candidate.sources:
            coverage[source] += 1
    return dict(sorted(coverage.items()))


def _frozen_candidate_export_rows(candidates_by_user: dict[str, list[Any]]) -> list[dict[str, Any]]:
    rows = []
    for user_id, candidates in candidates_by_user.items():
        for rank, candidate in enumerate(candidates, start=1):
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


def _ranking_stage_trace_rows(candidates_by_user: dict[str, list[Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for user_id in sorted(candidates_by_user):
        candidates = candidates_by_user[user_id]
        full_ranking = rank_candidates(user_id, candidates, config, top_k=len(candidates) or int(config.get("top_k", 5))).items
        for item in full_ranking:
            score_trace = item.get("score_trace", []) or []
            rows.append({
                "user_id": user_id,
                "item_id": item.get("parent_asin"),
                "candidate_pool_size": int(config.get("candidate_pool_size", 50)),
                "top_k": int(config.get("top_k", 5)),
                "input_candidate_count": len(candidates),
                "coarse_rank": item.get("coarse_rank"),
                "fine_rank": item.get("fine_rank"),
                "final_rank": item.get("final_rank"),
                "coarse_score": item.get("coarse_score"),
                "fine_score": item.get("fine_score"),
                "rerank_score": item.get("rerank_score"),
                "final_score": item.get("final_score"),
                "score": item.get("score"),
                "rank_movement": item.get("rank_movement", {}),
                "stage_trace": score_trace,
                "stage_names": [str(stage.get("stage")) for stage in score_trace if stage.get("stage")],
                "sources": item.get("sources", []),
                "score_components": item.get("score_components", {}),
                "rerank_events": item.get("rerank_events", []),
            })
    return rows



def _ranking_stage_summary(
    rows: list[dict[str, Any]],
    config: dict[str, Any],
    trace_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    expected_stages = ["coarse", "fine", "rerank"]
    stage_counts = {stage: 0 for stage in expected_stages}
    pass_through_stage_counts = {stage: 0 for stage in expected_stages}
    input_candidate_counts_by_user: dict[str, int] = {}
    for row in rows:
        user_id = str(row.get("user_id", ""))
        if user_id and user_id not in input_candidate_counts_by_user:
            input_candidate_counts_by_user[user_id] = int(row.get("input_candidate_count", 0) or 0)
        stages = set(row.get("stage_names", []))
        for stage in expected_stages:
            if stage in stages:
                stage_counts[stage] += 1
    total_ranked_items = len(rows)
    for stage in expected_stages:
        if stage_counts[stage] == total_ranked_items:
            pass_through_stage_counts[stage] = stage_counts[stage]
    user_count = len(input_candidate_counts_by_user)
    return {
        "schema_version": "ranking_stage_artifact_v1",
        "trace_path": str(trace_path),
        "summary_path": str(summary_path),
        "candidate_pool_size": int(config.get("candidate_pool_size", 50)),
        "top_k": int(config.get("top_k", 5)),
        "expected_stages": expected_stages,
        "stage_counts": stage_counts,
        "pass_through_stage_counts": pass_through_stage_counts,
        "total_ranked_items": total_ranked_items,
        "user_count": user_count,
        "input_candidate_count_total": sum(input_candidate_counts_by_user.values()),
        "input_candidate_count_min": min(input_candidate_counts_by_user.values()) if input_candidate_counts_by_user else 0,
        "input_candidate_count_max": max(input_candidate_counts_by_user.values()) if input_candidate_counts_by_user else 0,
        "online_metrics": {},
        "online_metric_claims": [],
    }



def _internal_fallback_diagnostics(candidates: list[Any]) -> dict[str, Any]:
    reasons = Counter(
        str(candidate.metadata.get("_internal_fallback_reason"))
        for candidate in candidates
        if candidate.metadata.get("_internal_fallback_reason")
    )
    sources = Counter(
        str(candidate.metadata.get("_internal_fallback_source"))
        for candidate in candidates
        if candidate.metadata.get("_internal_fallback_source")
    )
    if not reasons and not sources:
        return {}
    return {
        "fallback_recovery": {
            "used": True,
            "reasons": dict(sorted(reasons.items())),
            "sources": dict(sorted(sources.items())),
        }
    }


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _required_paths(clean_dir: Path, views_dir: Path) -> dict[str, Path]:
    return {
        "sequences": clean_dir / "user_sequences.train.jsonl",
        "popular": views_dir / "popular_recall.jsonl",
        "itemcf_weak": views_dir / "itemcf_recall_weak.jsonl",
        "itemcf_strong": views_dir / "itemcf_recall_strong.jsonl",
        "category_items": views_dir / "category_recall_items.jsonl",
        "category_top": views_dir / "category_top_items.jsonl",
    }


def _ensure_inputs(paths: dict[str, Path]) -> None:
    optional_keys = {"itemcf_strong"}
    missing = [str(path) for key, path in paths.items() if key not in optional_keys and not path.exists()]
    if missing:
        raise FileNotFoundError("Missing hybrid demo inputs: " + ", ".join(missing))


def _load_item_category(path: Path) -> dict[str, str]:
    mapping = {}
    for row in read_jsonl(path):
        if row.get("parent_asin"):
            mapping[row["parent_asin"]] = row.get("main_category") or row.get("category", "")
    return mapping


def _leave_one_positive_out_sequences(
    train_sequences: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    evaluation_sequences = []
    holdout = []
    stats = {
        "lopo_input_users": len(train_sequences),
        "lopo_eligible_users": 0,
        "lopo_skipped_users_fewer_than_2_positives": 0,
    }
    for sequence in train_sequences:
        positives = sequence.get("recent_positive_item_sequence", [])
        positive_timestamps = sequence.get("recent_positive_timestamp_sequence", [])
        if len(positives) < 2:
            stats["lopo_skipped_users_fewer_than_2_positives"] += 1
            continue
        stats["lopo_eligible_users"] += 1
        heldout_item = positives[-1]
        updated = dict(sequence)
        updated["recent_item_sequence"], updated["recent_timestamp_sequence"] = _remove_item_timestamps(
            sequence.get("recent_item_sequence", []),
            sequence.get("recent_timestamp_sequence", []),
            heldout_item,
        )
        updated["recent_positive_item_sequence"], updated["recent_positive_timestamp_sequence"] = _remove_item_timestamps(
            positives,
            positive_timestamps,
            heldout_item,
        )
        updated["recent_strong_positive_item_sequence"], updated["recent_strong_positive_timestamp_sequence"] = _remove_item_timestamps(
            sequence.get("recent_strong_positive_item_sequence", []),
            sequence.get("recent_strong_positive_timestamp_sequence", []),
            heldout_item,
        )
        updated["sequence_len"] = len(updated.get("recent_item_sequence", []))
        updated["positive_sequence_len"] = len(updated.get("recent_positive_item_sequence", []))
        updated["strong_positive_sequence_len"] = len(updated.get("recent_strong_positive_item_sequence", []))
        evaluation_sequences.append(updated)
        holdout.append({"user_id": sequence.get("user_id", ""), "parent_asin": heldout_item, "label_binary": 1})
    return evaluation_sequences, holdout, stats


def _remove_item_timestamps(
    items: list[Any],
    timestamps: list[Any],
    target_item: Any,
) -> tuple[list[Any], list[Any]]:
    updated_items = []
    updated_timestamps = []
    timestamps_are_aligned = len(timestamps) == len(items)
    for index, item in enumerate(items):
        if item == target_item:
            continue
        updated_items.append(item)
        if timestamps_are_aligned:
            updated_timestamps.append(timestamps[index])
    return updated_items, updated_timestamps


def _resolve_two_tower_artifact_path(config: dict[str, Any], views_dir: Path) -> Path:
    configured_path = config.get("two_tower_artifact_path")
    if configured_path:
        return _resolve_path(configured_path)
    return views_dir / str(config.get("two_tower_artifact_name", "semantic_recall_inputs.jsonl"))


def _resolve_item_graph_artifact_path(config: dict[str, Any], views_dir: Path) -> Path:
    configured_path = config.get("item_graph_artifact_path")
    if configured_path:
        return _resolve_path(configured_path)
    return views_dir / str(config.get("item_graph_artifact_name", "item_graph_recall.jsonl"))


def _resolve_two_tower_seed_artifact_path(config: dict[str, Any], views_dir: Path) -> Path:
    configured_path = config.get("two_tower_seed_artifact_path") or config.get("two_tower_seed_sidecar_path")
    if configured_path:
        return _resolve_path(configured_path)
    return views_dir / str(config.get("two_tower_seed_artifact_name", config.get("two_tower_seed_sidecar_name", "two_tower_seed_recall.jsonl")))


def _resolve_two_tower_seed_manifest_path(config: dict[str, Any], views_dir: Path) -> Path:
    configured_path = config.get("two_tower_seed_manifest_path")
    if configured_path:
        return _resolve_path(configured_path)
    return views_dir / str(config.get("two_tower_seed_manifest_name", "two_tower_seed_manifest.json"))



def _resolve_graph_walk_seed_artifact_path(config: dict[str, Any], views_dir: Path) -> Path:
    configured_path = config.get("graph_walk_seed_artifact_path") or config.get("graph_walk_seed_sidecar_path")
    if configured_path:
        return _resolve_path(configured_path)
    return views_dir / str(config.get("graph_walk_seed_artifact_name", config.get("graph_walk_seed_sidecar_name", "graph_walk_seed_neighbors.jsonl")))



def _resolve_graph_walk_seed_manifest_path(config: dict[str, Any], views_dir: Path) -> Path:
    configured_path = config.get("graph_walk_seed_manifest_path")
    if configured_path:
        return _resolve_path(configured_path)
    return views_dir / str(config.get("graph_walk_seed_manifest_name", "graph_walk_seed_manifest.json"))


def _latency_summary(
    candidate_generation_latencies: list[float],
    ranking_latencies: list[float],
    recommendation_latencies: list[float],
    total_run_seconds: float,
) -> dict[str, float]:
    return {
        "candidate_generation_avg_seconds": _avg(candidate_generation_latencies),
        "candidate_generation_p95_seconds": _percentile(candidate_generation_latencies, 0.95),
        "ranking_avg_seconds": _avg(ranking_latencies),
        "ranking_p95_seconds": _percentile(ranking_latencies, 0.95),
        "recommendation_avg_seconds": _avg(recommendation_latencies),
        "recommendation_p95_seconds": _percentile(recommendation_latencies, 0.95),
        "total_run_seconds": round(total_run_seconds, 6),
    }


def _diagnostic_gate(metrics: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    top_k = int(config.get("top_k", 5))
    candidate_pool_size = int(config.get("candidate_pool_size", 50))
    candidate_hit_rate = float(metrics.get("candidate_hit_rate_at_pool") or 0.0)
    hit_rate = float(metrics.get("hit_rate_at_k") or 0.0)
    ndcg = float(metrics.get("ndcg_at_k") or 0.0)
    mrr = float(metrics.get("mrr_at_k") or 0.0)
    rank_p50 = metrics.get("candidate_hit_rank_p50")
    rank_p90 = metrics.get("candidate_hit_rank_p90")
    missed_topk = int(metrics.get("candidate_hit_missed_topk_users") or 0)
    candidate_hit_users = int(metrics.get("candidate_hit_users") or 0)
    fallback_rate = float(metrics.get("fallback_rate") or 0.0)
    overlap = metrics.get("source_overlap", {}) or {}
    multi_source_rate = float(overlap.get("multi_source_candidate_rate") or 0.0)
    latency = metrics.get("latency", {}) or {}
    ranking_p95 = float(latency.get("ranking_p95_seconds") or 0.0)
    candidate_generation_p95 = float(latency.get("candidate_generation_p95_seconds") or 0.0)
    recall_bottleneck = candidate_hit_rate < 0.1 or candidate_hit_users == 0
    ranking_bottleneck = (
        candidate_hit_users > 0
        and (hit_rate + 0.001 < candidate_hit_rate)
        and (missed_topk > 0 or (rank_p50 is not None and float(rank_p50) > top_k))
    )
    source_merge_bottleneck = fallback_rate >= 0.2 or (multi_source_rate < 0.1 and candidate_pool_size > top_k)
    latency_bottleneck = candidate_pool_size >= 200 and ranking_p95 > 0.05
    architecture_escalation = bool(latency_bottleneck or (recall_bottleneck and candidate_pool_size >= 200))
    if recall_bottleneck or source_merge_bottleneck:
        recommended_next_phase = "phase_1_11_recall_source_merge"
    elif ranking_bottleneck:
        recommended_next_phase = "phase_1_12_ranking_ltr_gate"
    elif architecture_escalation:
        recommended_next_phase = "phase_2_architecture_poc_review"
    else:
        recommended_next_phase = "phase_1_10_baseline_ready"
    gate = {
        "recall_bottleneck": recall_bottleneck,
        "ranking_bottleneck": ranking_bottleneck,
        "source_merge_bottleneck": source_merge_bottleneck,
        "latency_bottleneck": latency_bottleneck,
        "architecture_escalation": architecture_escalation,
        "recommended_next_phase": recommended_next_phase,
        "evidence": {
            "top_k": top_k,
            "candidate_pool_size": candidate_pool_size,
            "candidate_hit_rate_at_pool": candidate_hit_rate,
            "hit_rate_at_k": hit_rate,
            "ndcg_at_k": ndcg,
            "mrr_at_k": mrr,
            "candidate_hit_users": candidate_hit_users,
            "candidate_hit_missed_topk_users": missed_topk,
            "candidate_hit_rank_p50": rank_p50,
            "candidate_hit_rank_p90": rank_p90,
            "fallback_rate": fallback_rate,
            "multi_source_candidate_rate": multi_source_rate,
            "ranking_p95_seconds": ranking_p95,
            "candidate_generation_p95_seconds": candidate_generation_p95,
        },
    }
    if config.get("two_tower_enabled") and config.get("strict_promotion_gate", {}).get("enabled", False):
        gate["two_tower_strict_promotion_gate"] = _two_tower_strict_promotion_gate(metrics, config)
    return gate


def _two_tower_strict_promotion_gate(metrics: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    gate_config = dict(config.get("strict_promotion_gate", {}) or {})
    evaluation_mode = str(metrics.get("evaluation_mode") or config.get("evaluation_mode", "valid_test"))
    baseline = _strict_gate_metric_baseline(gate_config, "semantic_title_baseline")
    lopo_baseline = _strict_gate_metric_baseline(gate_config, "semantic_title_lopo_baseline")
    paired_valid_test = _strict_gate_metric_baseline(gate_config, "paired_valid_test")
    paired_lopo = _strict_gate_metric_baseline(gate_config, "paired_lopo")
    latency_budget = float(gate_config.get("candidate_generation_p95_seconds_budget", 0.05))
    required_metrics = ["candidate_hit_rate_at_pool", "recall_at_pool"]
    metric_checks = {
        name: _metric_not_below(metrics, baseline, name)
        for name in required_metrics
    }
    candidate_hit_users_check = _metric_not_below(metrics, baseline, "candidate_hit_users")
    latency_check = float((metrics.get("latency") or {}).get("candidate_generation_p95_seconds") or 0.0) <= latency_budget
    source_contribution = metrics.get("per_source_candidate_contribution", {}) or {}
    source_overlap = metrics.get("source_overlap", {}) or {}
    source_evidence_check = "two_tower" in (metrics.get("recall_source_coverage", {}) or {}) and bool(source_contribution) and bool(source_overlap)
    lopo_reference = lopo_baseline if evaluation_mode == "leave_one_positive_out" else lopo_baseline
    lopo_current = metrics if evaluation_mode == "leave_one_positive_out" else paired_lopo
    lopo_checks = {
        name: _metric_not_below(lopo_current, lopo_reference, name)
        for name in required_metrics
    } if lopo_current and lopo_reference else {}
    paired_lopo_no_regression = bool(lopo_checks) and all(lopo_checks.values())
    valid_test_mode = evaluation_mode == "valid_test"
    promotable = bool(
        valid_test_mode
        and baseline
        and all(metric_checks.values())
        and candidate_hit_users_check
        and paired_lopo_no_regression
        and latency_check
        and source_evidence_check
    )
    if evaluation_mode == "leave_one_positive_out":
        decision = "lopo_sanity_only_no_promotion"
    elif promotable:
        decision = "eligible_for_manual_promotion_review"
    else:
        decision = "default_off_side_lane_only"
    return {
        "enabled": True,
        "variant": gate_config.get("variant", config.get("two_tower_variant", "two_tower")),
        "evaluation_mode": evaluation_mode,
        "promotable": promotable,
        "decision": decision,
        "checks": {
            "valid_test_mode": valid_test_mode,
            "semantic_title_baseline_present": bool(baseline),
            "valid_test_metrics_not_below_semantic_title_baseline": metric_checks,
            "candidate_hit_users_not_down": candidate_hit_users_check,
            "paired_lopo_no_regression": paired_lopo_no_regression,
            "candidate_generation_p95_within_budget": latency_check,
            "source_contribution_and_overlap_present": source_evidence_check,
        },
        "evidence": {
            "current_metrics": {name: metrics.get(name) for name in required_metrics + ["candidate_hit_users"]},
            "diagnostic_excluded_metrics": {name: metrics.get(name) for name in ["hit_rate_at_k", "ndcg_at_k", "mrr_at_k", "map_at_k"] if name in metrics},
            "semantic_title_baseline_metrics": baseline,
            "semantic_title_lopo_baseline_metrics": lopo_baseline,
            "paired_valid_test_metrics": paired_valid_test,
            "paired_lopo_metrics": paired_lopo,
            "evidence_paths": _strict_gate_evidence_paths(gate_config),
            "lopo_checks": lopo_checks,
            "candidate_generation_p95_seconds": (metrics.get("latency") or {}).get("candidate_generation_p95_seconds"),
            "candidate_generation_p95_seconds_budget": latency_budget,
            "two_tower_candidate_contribution": source_contribution.get("two_tower", 0),
            "source_overlap": source_overlap,
        },
    }


def _metric_not_below(metrics: dict[str, Any], baseline: dict[str, Any], name: str) -> bool:
    if name not in baseline:
        return False
    return float(metrics.get(name) or 0.0) + 1e-9 >= float(baseline.get(name) or 0.0)


def _strict_gate_metric_baseline(gate_config: dict[str, Any], prefix: str) -> dict[str, Any]:
    baseline = dict(gate_config.get(f"{prefix}_metrics", {}) or {})
    path = gate_config.get(f"{prefix}_metrics_path")
    if path:
        metrics_path = _resolve_path(path)
        if metrics_path.exists():
            loaded = json.loads(metrics_path.read_text(encoding="utf-8"))
            baseline.update({key: loaded.get(key) for key in ["candidate_hit_rate_at_pool", "recall_at_pool", "candidate_hit_users"] if key in loaded})
    return baseline


def _strict_gate_evidence_paths(gate_config: dict[str, Any]) -> dict[str, Any]:
    paths = {}
    for key in [
        "semantic_title_baseline_metrics_path",
        "semantic_title_lopo_baseline_metrics_path",
        "paired_valid_test_metrics_path",
        "paired_lopo_metrics_path",
    ]:
        configured = gate_config.get(key)
        if configured:
            resolved = _resolve_path(configured)
            paths[key] = {"path": str(resolved), "exists": resolved.exists()}
    return paths


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    rows = sorted(values)
    index = min(len(rows) - 1, max(0, int(round((len(rows) - 1) * percentile))))
    return round(rows[index], 6)


def _source_diagnostics(
    train_sequences: list[dict[str, Any]],
    itemcf_weak: dict[str, list[Any]],
    itemcf_strong: dict[str, list[Any]],
    item_graph: dict[str, list[Any]] | None = None,
    two_tower_seed: dict[str, list[Any]] | None = None,
    graph_walk_seed: dict[str, list[Any]] | None = None,
) -> dict[str, int]:
    users_with_positive_seeds = 0
    users_with_itemcf_seed_hits = 0
    users_with_itemcf_raw_candidates = 0
    itemcf_raw_candidates = 0
    itemcf_raw_unseen_candidates = 0
    item_graph = item_graph or {}
    two_tower_seed = two_tower_seed or {}
    graph_walk_seed = graph_walk_seed or {}
    users_with_item_graph_seed_hits = 0
    users_with_item_graph_raw_candidates = 0
    item_graph_raw_candidates = 0
    item_graph_raw_unseen_candidates = 0
    users_with_two_tower_seed_hits = 0
    users_with_two_tower_seed_raw_candidates = 0
    two_tower_seed_raw_candidates = 0
    two_tower_seed_raw_unseen_candidates = 0
    users_with_graph_walk_seed_hits = 0
    users_with_graph_walk_seed_raw_candidates = 0
    graph_walk_seed_raw_candidates = 0
    graph_walk_seed_raw_unseen_candidates = 0
    itemcf_seed_items = set(itemcf_weak) | set(itemcf_strong)
    item_graph_seed_items = set(item_graph)
    two_tower_seed_items = set(two_tower_seed)
    graph_walk_seed_items = set(graph_walk_seed)
    for sequence in train_sequences:
        seen_items = set(sequence.get("recent_item_sequence", []))
        seeds = set(sequence.get("recent_positive_item_sequence", [])) | set(
            sequence.get("recent_strong_positive_item_sequence", [])
        )
        if seeds:
            users_with_positive_seeds += 1
        if seeds & itemcf_seed_items:
            users_with_itemcf_seed_hits += 1
        if seeds & item_graph_seed_items:
            users_with_item_graph_seed_hits += 1
        if seeds & two_tower_seed_items:
            users_with_two_tower_seed_hits += 1
        if seeds & graph_walk_seed_items:
            users_with_graph_walk_seed_hits += 1
        raw_items = []
        graph_items = []
        two_tower_seed_items_for_user = []
        graph_walk_seed_items_for_user = []
        for seed in seeds:
            raw_items.extend(candidate.item_id for candidate in itemcf_weak.get(seed, []))
            raw_items.extend(candidate.item_id for candidate in itemcf_strong.get(seed, []))
            graph_items.extend(candidate.item_id for candidate in item_graph.get(seed, []))
            two_tower_seed_items_for_user.extend(candidate.item_id for candidate in two_tower_seed.get(seed, []))
            graph_walk_seed_items_for_user.extend(candidate.item_id for candidate in graph_walk_seed.get(seed, []))
        if raw_items:
            users_with_itemcf_raw_candidates += 1
        if graph_items:
            users_with_item_graph_raw_candidates += 1
        if two_tower_seed_items_for_user:
            users_with_two_tower_seed_raw_candidates += 1
        if graph_walk_seed_items_for_user:
            users_with_graph_walk_seed_raw_candidates += 1
        itemcf_raw_candidates += len(raw_items)
        itemcf_raw_unseen_candidates += sum(1 for item_id in raw_items if item_id not in seen_items)
        item_graph_raw_candidates += len(graph_items)
        item_graph_raw_unseen_candidates += sum(1 for item_id in graph_items if item_id not in seen_items)
        two_tower_seed_raw_candidates += len(two_tower_seed_items_for_user)
        two_tower_seed_raw_unseen_candidates += sum(1 for item_id in two_tower_seed_items_for_user if item_id not in seen_items)
        graph_walk_seed_raw_candidates += len(graph_walk_seed_items_for_user)
        graph_walk_seed_raw_unseen_candidates += sum(1 for item_id in graph_walk_seed_items_for_user if item_id not in seen_items)
    return {
        "users_with_positive_seeds": users_with_positive_seeds,
        "users_with_itemcf_seed_hits": users_with_itemcf_seed_hits,
        "users_with_itemcf_raw_candidates": users_with_itemcf_raw_candidates,
        "itemcf_raw_candidates": itemcf_raw_candidates,
        "itemcf_raw_unseen_candidates": itemcf_raw_unseen_candidates,
        "users_with_item_graph_seed_hits": users_with_item_graph_seed_hits,
        "users_with_item_graph_raw_candidates": users_with_item_graph_raw_candidates,
        "item_graph_raw_candidates": item_graph_raw_candidates,
        "item_graph_raw_unseen_candidates": item_graph_raw_unseen_candidates,
        "users_with_two_tower_seed_hits": users_with_two_tower_seed_hits,
        "users_with_two_tower_seed_raw_candidates": users_with_two_tower_seed_raw_candidates,
        "two_tower_seed_raw_candidates": two_tower_seed_raw_candidates,
        "two_tower_seed_raw_unseen_candidates": two_tower_seed_raw_unseen_candidates,
        "users_with_graph_walk_seed_hits": users_with_graph_walk_seed_hits,
        "users_with_graph_walk_seed_raw_candidates": users_with_graph_walk_seed_raw_candidates,
        "graph_walk_seed_raw_candidates": graph_walk_seed_raw_candidates,
        "graph_walk_seed_raw_unseen_candidates": graph_walk_seed_raw_unseen_candidates,
    }


def _itemcf_seed_items(train_sequences: list[dict[str, Any]]) -> set[str]:
    seeds: set[str] = set()
    for sequence in train_sequences:
        seeds.update(sequence.get("recent_positive_item_sequence", []))
        seeds.update(sequence.get("recent_strong_positive_item_sequence", []))
    return seeds


def _ranking_hit_cases(
    candidates_by_user: dict[str, list[Any]],
    holdout_records: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    positives = heldout_positives(holdout_records)
    rows: list[dict[str, Any]] = []
    for user_id in sorted(candidates_by_user):
        targets = positives.get(user_id, set())
        if not targets:
            continue
        candidates = candidates_by_user[user_id]
        full_ranking = rank_candidates(user_id, candidates, config, top_k=len(candidates) or int(config.get("top_k", 5))).items
        for target in sorted(targets):
            rank = _rank_of_item(full_ranking, target)
            if rank is None:
                continue
            item = full_ranking[rank - 1]
            rows.append({
                "user_id": user_id,
                "target_item": target,
                "target_rank": rank,
                "target_score": item.get("score"),
                "target_coarse_score": item.get("coarse_score"),
                "target_fine_score": item.get("fine_score"),
                "target_rerank_score": item.get("rerank_score"),
                "target_final_score": item.get("final_score"),
                "target_coarse_rank": item.get("coarse_rank"),
                "target_fine_rank": item.get("fine_rank"),
                "target_final_rank": item.get("final_rank"),
                "target_rank_movement": item.get("rank_movement", {}),
                "target_reason_codes": _score_trace_reason_codes(item),
                "target_score_trace": item.get("score_trace", []),
                "target_sources": item.get("sources", []),
                "target_source_scores": _candidate_source_scores(candidates, target),
                "target_score_components": item.get("score_components", {}),
                "top_k": int(config.get("top_k", 5)),
                "is_topk_hit": rank <= int(config.get("top_k", 5)),
                "affected_user_id": user_id,
                "target_item_id": target,
                "baseline_rank": rank,
                "variant_rank": rank,
                "items_above_target": full_ranking[: rank - 1],
                "top_items": full_ranking[: int(config.get("top_k", 5))],
                "topk_replacement_reason": _topk_replacement_reason(full_ranking, target, int(config.get("top_k", 5))),
            })
    return rows


def _ranking_case_summary(ranking_cases: list[dict[str, Any]]) -> dict[str, Any]:
    missed_cases = [row for row in ranking_cases if not row.get("is_topk_hit")]
    above_source_combinations: Counter[str] = Counter()
    top_item_source_combinations: Counter[str] = Counter()
    target_source_combinations: Counter[str] = Counter()
    score_gaps: list[float] = []
    semantic_only_above = 0
    above_items_total = 0
    for row in missed_cases:
        target_source_combinations[_source_key(row.get("target_sources", []))] += 1
        target_score = float(row.get("target_score") or 0.0)
        top_items = row.get("top_items", [])
        if top_items:
            score_gaps.append(round(float(top_items[0].get("score") or 0.0) - target_score, 6))
        for item in row.get("items_above_target", []):
            key = _source_key(item.get("sources", []))
            above_source_combinations[key] += 1
            above_items_total += 1
            if key == "semantic":
                semantic_only_above += 1
        for item in top_items:
            top_item_source_combinations[_source_key(item.get("sources", []))] += 1
    return {
        "total_hit_cases": len(ranking_cases),
        "topk_hit_cases": len(ranking_cases) - len(missed_cases),
        "missed_topk_cases": len(missed_cases),
        "target_source_combinations": dict(sorted(target_source_combinations.items())),
        "items_above_source_combinations": dict(above_source_combinations.most_common()),
        "top_item_source_combinations": dict(top_item_source_combinations.most_common()),
        "items_above_total": above_items_total,
        "semantic_only_items_above_share": round(semantic_only_above / above_items_total, 6) if above_items_total else 0.0,
        "top1_score_gap_avg": _avg(score_gaps),
        "top1_score_gap_max": max(score_gaps) if score_gaps else 0.0,
        "top1_score_gap_min": min(score_gaps) if score_gaps else 0.0,
    }


def _topk_replacement_reason(items: list[dict[str, Any]], target: str, top_k: int) -> dict[str, Any]:
    target_rank = _rank_of_item(items, target)
    target_item = items[target_rank - 1] if target_rank else {}
    if target_rank is None:
        return {"reason": "target_not_in_candidate_ranking", "replaced_by": []}
    if target_rank <= top_k:
        return {"reason": "target_in_topk", "replaced_by": []}
    replaced_by = []
    for item in items[:top_k]:
        replaced_by.append({
            "item_id": item.get("parent_asin"),
            "score": item.get("score"),
            "score_advantage": round(float(item.get("score") or 0.0) - float(target_item.get("score") or 0.0), 6),
            "dominant_score_component": _dominant_score_component(item),
            "near_miss_tiebreak_triggered": any(event.get("type") == "stable_tie_break" for event in item.get("rerank_events", [])),
        })
    return {"reason": "target_below_topk", "replaced_by": replaced_by}


def _dominant_score_component(item: dict[str, Any]) -> str | None:
    components = item.get("score_components", {}) or {}
    if not components:
        return None
    return max(components, key=lambda key: abs(float((components.get(key) or {}).get("contribution") or 0.0)))



def _score_trace_reason_codes(item: dict[str, Any]) -> dict[str, list[str]]:
    reason_codes: dict[str, list[str]] = {}
    for stage in item.get("score_trace", []) or []:
        stage_name = stage.get("stage")
        if stage_name:
            reason_codes[str(stage_name)] = list(stage.get("reason_codes", []) or [])
    return reason_codes


def _source_key(sources: list[Any]) -> str:
    return "+".join(sorted(str(source) for source in sources)) or "unknown"


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _rank_of_item(items: list[dict[str, Any]], item_id: str) -> int | None:
    for index, item in enumerate(items, start=1):
        if item.get("parent_asin") == item_id:
            return index
    return None


def _candidate_source_scores(candidates: list[Any], item_id: str) -> dict[str, float]:
    for candidate in candidates:
        if candidate.item_id == item_id:
            return {source: float(score) for source, score in sorted(candidate.source_scores.items())}
    return {}


def _config_summary(
    config: dict[str, Any],
    clean_dir: Path,
    views_dir: Path,
    limit_users: int | None,
    evaluation_mode: str,
    lopo_stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    summary = {
        "clean_dir": str(clean_dir),
        "views_dir": str(views_dir),
        "evaluation_mode": evaluation_mode,
        "top_k": config.get("top_k", 5),
        "candidate_pool_size": config.get("candidate_pool_size", 50),
        "limit_users": limit_users,
        "rank_weights": config.get("rank_weights", {}),
        "rerank_policy": config.get("rerank_policy", {}),
        "source_aware_fusion": config.get("source_aware_fusion", {}),
        "item_feature_rerank": config.get("item_feature_rerank", {}),
        "ltr_model": config.get("ltr_model", {}),
        "topk_source_minimums": config.get("topk_source_minimums", {}),
        "candidate_source_minimums": config.get("candidate_source_minimums", {}),
        "semantic_enabled": bool(config.get("semantic_enabled", False)),
        "semantic_per_user": config.get("semantic_per_user"),
        "semantic_min_overlap": config.get("semantic_min_overlap"),
        "semantic_score_mode": config.get("semantic_score_mode", "raw"),
        "semantic_category_weight": config.get("semantic_category_weight", 2.0),
        "semantic_text_fields": config.get("semantic_text_fields"),
        "two_tower_enabled": bool(config.get("two_tower_enabled", False)),
        "two_tower_variant": config.get("two_tower_variant"),
        "two_tower_artifact_path": config.get("two_tower_artifact_path"),
        "two_tower_artifact_name": config.get("two_tower_artifact_name", "semantic_recall_inputs.jsonl"),
        "two_tower_per_user": config.get("two_tower_per_user"),
        "two_tower_text_fields": config.get("two_tower_text_fields"),
        "two_tower_min_overlap": config.get("two_tower_min_overlap"),
        "two_tower_recency_decay": config.get("two_tower_recency_decay"),
        "two_tower_seed_enabled": bool(config.get("two_tower_seed_enabled", False)),
        "two_tower_seed_artifact_path": config.get("two_tower_seed_artifact_path") or config.get("two_tower_seed_sidecar_path"),
        "two_tower_seed_artifact_name": config.get("two_tower_seed_artifact_name", config.get("two_tower_seed_sidecar_name", "two_tower_seed_recall.jsonl")),
        "two_tower_seed_manifest_path": config.get("two_tower_seed_manifest_path"),
        "two_tower_seed_manifest_name": config.get("two_tower_seed_manifest_name", "two_tower_seed_manifest.json"),
        "fail_on_missing_sidecar": bool(config.get("fail_on_missing_sidecar", False)),
        "two_tower_seed_per_seed": config.get("two_tower_seed_per_seed"),
        "two_tower_seed_per_user": config.get("two_tower_seed_per_user"),
        "two_tower_seed_window": config.get("two_tower_seed_window"),
        "two_tower_seed_recent_positive_window": config.get("two_tower_seed_recent_positive_window"),
        "two_tower_seed_recent_strong_window": config.get("two_tower_seed_recent_strong_window"),
        "two_tower_seed_recency_decay": config.get("two_tower_seed_recency_decay"),
        "two_tower_seed_score_floor": config.get("two_tower_seed_score_floor"),
        "item_graph_enabled": bool(config.get("item_graph_enabled", False)),
        "item_graph_artifact_path": config.get("item_graph_artifact_path"),
        "item_graph_artifact_name": config.get("item_graph_artifact_name", "item_graph_recall.jsonl"),
        "item_graph_per_seed": config.get("item_graph_per_seed"),
        "item_graph_per_user": config.get("item_graph_per_user"),
        "item_graph_seed_window": config.get("item_graph_seed_window"),
        "item_graph_recent_positive_window": config.get("item_graph_recent_positive_window"),
        "item_graph_recent_strong_window": config.get("item_graph_recent_strong_window"),
        "graph_walk_seed_enabled": bool(config.get("graph_walk_seed_enabled", False)),
        "graph_walk_seed_algorithm": config.get("graph_walk_seed_algorithm", "deepwalk"),
        "graph_walk_seed_artifact_path": config.get("graph_walk_seed_artifact_path") or config.get("graph_walk_seed_sidecar_path"),
        "graph_walk_seed_artifact_name": config.get("graph_walk_seed_artifact_name", config.get("graph_walk_seed_sidecar_name", "graph_walk_seed_neighbors.jsonl")),
        "graph_walk_seed_manifest_path": config.get("graph_walk_seed_manifest_path"),
        "graph_walk_seed_manifest_name": config.get("graph_walk_seed_manifest_name", "graph_walk_seed_manifest.json"),
        "graph_walk_seed_per_seed": config.get("graph_walk_seed_per_seed"),
        "graph_walk_seed_per_user": config.get("graph_walk_seed_per_user"),
        "graph_walk_seed_window": config.get("graph_walk_seed_window"),
        "graph_walk_seed_recent_positive_window": config.get("graph_walk_seed_recent_positive_window"),
        "graph_walk_seed_recent_strong_window": config.get("graph_walk_seed_recent_strong_window"),
        "graph_walk_seed_recency_decay": config.get("graph_walk_seed_recency_decay"),
        "graph_walk_seed_score_floor": config.get("graph_walk_seed_score_floor"),
        "graph_walk_training": config.get("graph_walk_training", {}),
        "candidate_source_maximums": config.get("candidate_source_maximums", {}),
        "candidate_pool_strategy": config.get("candidate_pool_strategy"),
    }
    if lopo_stats:
        summary.update(lopo_stats)
    return summary


def _write_report(
    path: Path,
    config: dict[str, Any],
    metrics: dict[str, Any],
    rows: list[dict[str, Any]],
    ranking_case_summary: dict[str, Any] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    examples = rows[: int(config.get("sample_examples", 3))]
    lines = [
        "# Hybrid Demo Small Report",
        "",
        "## Config Summary",
        "",
        "```json",
        json.dumps(metrics.get("config_summary", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Metrics and Ablation",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key in [
        "evaluation_mode",
        "users_total",
        "users_with_holdout",
        "users_evaluated",
        "lopo_input_users",
        "lopo_eligible_users",
        "lopo_skipped_users_fewer_than_2_positives",
        "hit_rate_denominator",
        "candidate_count_avg",
        "fallback_rate",
        "candidate_hit_rate_at_pool",
        "candidate_hit_users",
        "candidate_hit_rank_min",
        "candidate_hit_rank_avg",
        "candidate_hit_rank_p50",
        "candidate_hit_rank_p90",
        "candidate_hit_missed_topk_users",
        "ranked_hit_users",
        "recall_at_k",
        "recall_at_pool",
        "ndcg_at_k",
        "mrr_at_k",
        "map_at_k",
        "hit_rate_at_k",
        "popular_only_hit_rate_at_k",
        "itemcf_only_hit_rate_at_k",
        "hybrid_hit_rate_at_k",
        "hybrid_no_itemcf_hit_rate_at_k",
        "category_diversity_avg",
    ]:
        lines.append(f"| {key} | {metrics.get(key)} |")
    lines.extend([
        "",
        "## Fallback and Source Coverage",
        "",
        f"- fallback_rate: {metrics.get('fallback_rate')}",
        f"- recall_source_coverage: `{json.dumps(metrics.get('recall_source_coverage', {}), ensure_ascii=False)}`",
        f"- topk_source_coverage: `{json.dumps(metrics.get('topk_source_coverage', {}), ensure_ascii=False)}`",
        f"- per_source_candidate_contribution: `{json.dumps(metrics.get('per_source_candidate_contribution', {}), ensure_ascii=False)}`",
        f"- per_source_topk_contribution: `{json.dumps(metrics.get('per_source_topk_contribution', {}), ensure_ascii=False)}`",
        f"- source_overlap: `{json.dumps(metrics.get('source_overlap', {}), ensure_ascii=False)}`",
        f"- source_diagnostics: `{json.dumps(metrics.get('source_diagnostics', {}), ensure_ascii=False)}`",
        "",
        "## Diagnostic Gate",
        "",
        "```json",
        json.dumps(metrics.get("diagnostic_gate", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Latency Diagnostics",
        "",
        "```json",
        json.dumps(metrics.get("latency", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Recall Bottleneck Diagnostics",
        "",
        f"- candidate_hit_rate_at_pool: {metrics.get('candidate_hit_rate_at_pool')}",
        f"- candidate_hit_users: {metrics.get('candidate_hit_users')}",
        f"- ranked_hit_users: {metrics.get('ranked_hit_users')}",
        f"- candidate_hit_missed_topk_users: {metrics.get('candidate_hit_missed_topk_users')}",
        f"- candidate_hit_rank_min: {metrics.get('candidate_hit_rank_min')}",
        f"- candidate_hit_rank_avg: {metrics.get('candidate_hit_rank_avg')}",
        f"- candidate_hit_rank_p50: {metrics.get('candidate_hit_rank_p50')}",
        f"- candidate_hit_rank_p90: {metrics.get('candidate_hit_rank_p90')}",
        f"- candidate_hit_source_coverage: `{json.dumps(metrics.get('candidate_hit_source_coverage', {}), ensure_ascii=False)}`",
        "",
        "## Ranking Case Summary",
        "",
        f"- total_hit_cases: {(ranking_case_summary or {}).get('total_hit_cases', 0)}",
        f"- topk_hit_cases: {(ranking_case_summary or {}).get('topk_hit_cases', 0)}",
        f"- missed_topk_cases: {(ranking_case_summary or {}).get('missed_topk_cases', 0)}",
        f"- semantic_only_items_above_share: {(ranking_case_summary or {}).get('semantic_only_items_above_share', 0.0)}",
        f"- top1_score_gap_avg: {(ranking_case_summary or {}).get('top1_score_gap_avg', 0.0)}",
        f"- target_source_combinations: `{json.dumps((ranking_case_summary or {}).get('target_source_combinations', {}), ensure_ascii=False)}`",
        f"- items_above_source_combinations: `{json.dumps((ranking_case_summary or {}).get('items_above_source_combinations', {}), ensure_ascii=False)}`",
        "",
        "## Sample Limitations",
        "",
    ])
    for limitation in metrics.get("sample_limitations", []):
        lines.append(f"- {limitation}")
    if not metrics.get("sample_limitations"):
        lines.append("- None reported.")
    lines.extend(["", "## Recommendation Examples", ""])
    for row in examples:
        lines.append(f"### User {row.get('user_id')}")
        lines.append("")
        lines.append(f"- strategy: {row.get('strategy_name')}")
        lines.append(f"- risk_flags: {', '.join(row.get('risk_flags', [])) or 'none'}")
        lines.append("- items:")
        for item in row.get("final_items", [])[:5]:
            lines.append(f"  - {item.get('parent_asin')} score={item.get('score')} sources={','.join(item.get('sources', []))}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
