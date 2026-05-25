from __future__ import annotations

import hashlib
from collections import Counter
from copy import deepcopy
from math import isfinite, log2
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from rs_core.common.io import iter_jsonl, read_json
from rs_core.recsys.ranking import rank_candidates
from rs_core.recsys.types import MergedCandidate
from rs_core.workflow.full_data_pool500_route_gate import CANONICAL_SOURCES, FORBIDDEN_SOURCE_LABELS, canonicalize_source_label
from rs_core.workflow.pool500_ranking_adapter import POOL500_LINEAGE_KEY, adapt_pool500_rows_to_candidates

SCHEMA_VERSION = "pool500_shadow_ranking_evidence_v1"
DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION = "pool500_diagnostic_frozen_pool_ranking_evidence_v1"
DIAGNOSTIC_FROZEN_POOL_INPUT_CONTRACT = "frozen_diagnostic_candidate_pool"
DIAGNOSTIC_FROZEN_POOL_EXTRA_SOURCES = {
    "cold_start_category_sibling",
    "cold_start_metadata_neighbor",
    "cold_start_semantic_token",
}
FULL_POOL500_READY = "FULL_POOL500_READY"
PASS = "PASS"
STOP = "STOP"

DIAGNOSTIC_ONLY_FLAGS = {
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "ranking_replacement_allowed": False,
    "promotion_allowed": False,
    "pool1000_allowed": False,
    "diagnostic_only": True,
}

SHADOW_REPORT_BOUNDARY_FLAGS = {
    "not_ranking_input": True,
    "current_ranking_route_unchanged": True,
    "promotion_requires_future_plan": True,
}

DEFAULT_RESOURCE_BUDGET = {
    "max_users": 500,
    "max_rows": 250000,
    "max_runtime_seconds": 1800,
}

FORBIDDEN_FIELDS = {
    "current_ranking_route",
    "candidate",
    "candidate_id",
    "candidate_type",
    "challenger",
    "champion",
    "promotion_lane",
    "promotion_eligible",
    "promotion_ready",
    "production_ready",
    "lane",
}
FORBIDDEN_RUN_KINDS = {"variant", "challenger", "candidate", "champion"}
FORBIDDEN_READY_VALUES = {"promotion-ready", "production-ready"}
FIXED_COMPARISON_TOP_K = 20
FIXED_COMPARISON_TOP10_K = 10
FIXED_COMPARISON_CONFIG_IDS = ("B0", "D1", "D2", "A1", "A2", "R1", "R2", "R3")
FIXED_COMPARISON_REQUIRED_ITEM_FIELDS = ("parent_asin", "score_trace", "rank_movement", "score_components")
LABEL_METRIC_DEFINITION_VERSION = "pool500_label_metrics_per_user_mean_v1"
STRICT_LABEL_GATE_THRESHOLDS = {
    "topk_union_candidate_coverage": 1.0,
    "user_label_coverage": 1.0,
    "positive_user_coverage": 1.0,
}
QUALITY_GUARD_THRESHOLDS = {
    "fallback_exposure_topk_ratio": 0.5,
    "metadata_missing_rate": 0.01,
    "category_missing_rate": 0.05,
    "top_category_ratio": 0.95,
}

BASELINE_DIAGNOSTIC_UNIFORM_RANK_WEIGHTS = {
    "popular": 1.0,
    "category": 1.0,
    "semantic": 1.0,
    "semantic_title_category_expansion": 1.0,
    "itemcf_weak": 1.0,
    "itemcf_strong": 1.0,
    "co_visit_fallback_repair": 1.0,
    "usercf_recall": 1.0,
    "swing_recall": 1.0,
    "two_tower": 1.0,
}


def build_pool500_shadow_ranking_evidence(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    shadow_metrics: dict[str, Any],
    source_artifact_gate_result: dict[str, Any] | None = None,
    source_shadow_evidence_validation: dict[str, Any] | None = None,
    source_artifact_gate_decision: str | None = None,
    source_shadow_evidence_decision: str | None = None,
    lineage_hash: str | None = "diagnostic-shadow-ranking-lineage",
    baseline_artifact_hash: str | None = "diagnostic-current-ranking-baseline",
    resource_budget: dict[str, Any] | None = None,
    failure_recovery_strategy: str | None = "stop shadow ranking, preserve current ranking route, and rerun after evidence repair",
    cleanup_strategy: str | None = "delete diagnostic shadow ranking intermediates after report review",
    generated_at: str | None = None,
) -> dict[str, Any]:
    artifact_decision = source_artifact_gate_decision
    if artifact_decision is None and isinstance(source_artifact_gate_result, dict):
        artifact_decision = source_artifact_gate_result.get("decision")
    shadow_decision = source_shadow_evidence_decision
    if shadow_decision is None and isinstance(source_shadow_evidence_validation, dict):
        shadow_decision = source_shadow_evidence_validation.get("status")
    return {
        "schema_version": SCHEMA_VERSION,
        "report_semantics": "diagnostic shadow ranking report",
        "diagnostic_method_id": diagnostic_method_id,
        "comparison_group": comparison_group,
        "shadow_metrics": dict(shadow_metrics),
        "source_artifact_gate_decision": artifact_decision,
        "source_shadow_evidence_decision": shadow_decision,
        "lineage_hash": lineage_hash,
        "baseline_artifact_hash": baseline_artifact_hash,
        "resource_budget": dict(DEFAULT_RESOURCE_BUDGET if resource_budget is None else resource_budget),
        "failure_recovery_strategy": failure_recovery_strategy,
        "cleanup_strategy": cleanup_strategy,
        **DIAGNOSTIC_ONLY_FLAGS,
        **SHADOW_REPORT_BOUNDARY_FLAGS,
        "generated_at": generated_at,
    }


def run_pool500_shadow_ranking(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    config: dict[str, Any],
    artifact_gate_result: dict[str, Any],
    recall_shadow_evidence_validation: dict[str, Any] | None = None,
    candidates_by_user: dict[str, list[MergedCandidate]] | None = None,
    rows: Iterable[dict[str, Any]] | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    blockers = _preflight_blockers(artifact_gate_result, recall_shadow_evidence_validation)
    if blockers:
        return _stop_result(
            diagnostic_method_id=diagnostic_method_id,
            comparison_group=comparison_group,
            artifact_gate_result=artifact_gate_result,
            recall_shadow_evidence_validation=recall_shadow_evidence_validation,
            blockers=blockers,
            adapter_result=None,
            top_k=top_k,
        )

    core = _run_pool500_ranking_core(candidates_by_user=candidates_by_user, rows=rows, config=config, top_k=top_k)
    if core["blockers"]:
        return _stop_result(
            diagnostic_method_id=diagnostic_method_id,
            comparison_group=comparison_group,
            artifact_gate_result=artifact_gate_result,
            recall_shadow_evidence_validation=recall_shadow_evidence_validation,
            blockers=core["blockers"],
            adapter_result=core.get("adapter_result"),
            top_k=top_k,
        )

    evidence = build_pool500_shadow_ranking_evidence(
        diagnostic_method_id=diagnostic_method_id,
        comparison_group=comparison_group,
        shadow_metrics=core["shadow_metrics"],
        source_artifact_gate_result=artifact_gate_result,
        source_shadow_evidence_validation=recall_shadow_evidence_validation,
    )
    validation = validate_pool500_shadow_ranking_evidence(evidence)
    status = PASS if validation["status"] == PASS else STOP
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "decision": status,
        "evidence": evidence,
        "validation": validation,
        "ranking_results": core["ranking_results"] if status == PASS else {},
        "adapter_result": _adapter_summary(core.get("adapter_result")),
        "blockers": validation["blockers"],
        "diagnostics": [],
    }


def run_pool500_diagnostic_frozen_pool_ranking(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    config: dict[str, Any],
    pool500_candidates_path: str | Path,
    candidate_manifest_path: str | Path,
    expected_candidate_hash: str,
    expected_manifest_hash: str,
    diagnostic_input_contract: str = DIAGNOSTIC_FROZEN_POOL_INPUT_CONTRACT,
    source_artifact_gate_result: dict[str, Any] | None = None,
    recall_shadow_evidence_validation: dict[str, Any] | None = None,
    top_k: int = 20,
    label_artifact_path: str | Path | None = None,
    label_evaluator_enabled: bool = False,
) -> dict[str, Any]:
    input_validation = _validate_diagnostic_frozen_pool_input(
        pool500_candidates_path=pool500_candidates_path,
        candidate_manifest_path=candidate_manifest_path,
        expected_candidate_hash=expected_candidate_hash,
        expected_manifest_hash=expected_manifest_hash,
        diagnostic_input_contract=diagnostic_input_contract,
        source_artifact_gate_result=source_artifact_gate_result,
    )
    label_context = _build_pool500_label_context(
        candidate_path=Path(input_validation["pool500_candidates_path"]),
        manifest_path=Path(input_validation["candidate_manifest_path"]),
        explicit_label_artifact_path=label_artifact_path,
        evaluator_enabled=label_evaluator_enabled,
        ranking_results=None,
    )
    if input_validation["blockers"]:
        label_context["label_state"] = "blocked"
        label_context["label_blockers"] = [*label_context.get("label_blockers", []), *input_validation["blockers"]]
        evidence = build_pool500_diagnostic_frozen_pool_ranking_evidence(
            diagnostic_method_id=diagnostic_method_id,
            comparison_group=comparison_group,
            input_validation=input_validation,
            shadow_metrics={"user_count": 0, "top_k": top_k, "stopped_before_ranking": True},
            source_artifact_gate_result=source_artifact_gate_result,
            source_shadow_evidence_validation=recall_shadow_evidence_validation,
            label_context=label_context,
        )
        validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence(evidence)
        evidence["interpretation_label"] = validation["interpretation_label"]
        return _diagnostic_frozen_pool_result(evidence, validation, {}, None, [*input_validation["blockers"], *validation["blockers"]])

    core = _run_pool500_ranking_core(
        candidates_by_user=None,
        rows=_iter_diagnostic_frozen_pool_rows(Path(input_validation["pool500_candidates_path"])),
        config=config,
        top_k=top_k,
        extra_allowed_sources=DIAGNOSTIC_FROZEN_POOL_EXTRA_SOURCES,
    )
    if core["blockers"]:
        evidence = build_pool500_diagnostic_frozen_pool_ranking_evidence(
            diagnostic_method_id=diagnostic_method_id,
            comparison_group=comparison_group,
            input_validation=input_validation,
            shadow_metrics={"user_count": 0, "top_k": top_k, "stopped_before_ranking": True},
            source_artifact_gate_result=source_artifact_gate_result,
            source_shadow_evidence_validation=recall_shadow_evidence_validation,
            label_context=label_context,
        )
        validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence(evidence)
        evidence["interpretation_label"] = validation["interpretation_label"]
        return _diagnostic_frozen_pool_result(evidence, validation, {}, core.get("adapter_result"), [*core["blockers"], *validation["blockers"]])

    label_context = _build_pool500_label_context(
        candidate_path=Path(input_validation["pool500_candidates_path"]),
        manifest_path=Path(input_validation["candidate_manifest_path"]),
        explicit_label_artifact_path=label_artifact_path,
        evaluator_enabled=label_evaluator_enabled,
        ranking_results=core["ranking_results"],
    )
    evidence = build_pool500_diagnostic_frozen_pool_ranking_evidence(
        diagnostic_method_id=diagnostic_method_id,
        comparison_group=comparison_group,
        input_validation=input_validation,
        shadow_metrics=core["shadow_metrics"],
        source_artifact_gate_result=source_artifact_gate_result,
        source_shadow_evidence_validation=recall_shadow_evidence_validation,
        label_context=label_context,
    )
    validation = validate_pool500_diagnostic_frozen_pool_ranking_evidence(evidence)
    status = PASS if validation["status"] == PASS else STOP
    evidence["interpretation_label"] = validation["interpretation_label"]
    return {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "status": status,
        "decision": status,
        "evidence": evidence,
        "validation": validation,
        "ranking_results": core["ranking_results"] if status == PASS else {},
        "adapter_result": _adapter_summary(core.get("adapter_result")),
        "blockers": validation["blockers"],
        "diagnostics": core["diagnostics"],
    }


def run_pool500_fixed_ranking_comparison_report(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    pool500_candidates_path: str | Path,
    candidate_manifest_path: str | Path,
    expected_candidate_hash: str,
    expected_manifest_hash: str,
    interpretation_label: str | None = None,
    diagnostic_input_contract: str = DIAGNOSTIC_FROZEN_POOL_INPUT_CONTRACT,
    source_artifact_gate_result: dict[str, Any] | None = None,
    recall_shadow_evidence_validation: dict[str, Any] | None = None,
    label_artifact_path: str | Path | None = None,
    label_evaluator_enabled: bool = False,
) -> dict[str, Any]:
    comparison_results: dict[str, dict[str, Any]] = {}
    blockers: list[dict[str, Any]] = []
    for config_id, config in build_pool500_fixed_ranking_comparison_configs().items():
        result = run_pool500_diagnostic_frozen_pool_ranking(
            diagnostic_method_id=diagnostic_method_id,
            comparison_group=f"{comparison_group}_{config_id}",
            config=config,
            pool500_candidates_path=pool500_candidates_path,
            candidate_manifest_path=candidate_manifest_path,
            expected_candidate_hash=expected_candidate_hash,
            expected_manifest_hash=expected_manifest_hash,
            diagnostic_input_contract=diagnostic_input_contract,
            source_artifact_gate_result=source_artifact_gate_result,
            recall_shadow_evidence_validation=recall_shadow_evidence_validation,
            top_k=FIXED_COMPARISON_TOP_K,
            label_artifact_path=label_artifact_path,
            label_evaluator_enabled=label_evaluator_enabled,
        )
        comparison_results[config_id] = _fixed_comparison_run_summary(config_id, config, result)
        blockers.extend(result.get("blockers", []))
        blockers.extend(_ranking_result_explainability_blockers(config_id, result.get("ranking_results", {})))
    baseline = comparison_results.get("B0", {})
    case_diffs = {
        config_id: _case_diff_rows(
            baseline.get("ranking_results", {}),
            summary.get("ranking_results", {}),
            summary.get("interpretation_label") or baseline.get("interpretation_label") or interpretation_label,
        )
        for config_id, summary in comparison_results.items()
        if config_id != "B0"
    }
    blockers.extend(_case_diff_blockers(case_diffs))
    label_aggregation = _apply_fixed_comparison_label_context(
        comparison_results=comparison_results,
        candidate_path=Path(pool500_candidates_path),
        manifest_path=Path(candidate_manifest_path),
        explicit_label_artifact_path=label_artifact_path,
        evaluator_enabled=label_evaluator_enabled,
    )
    status = PASS if not blockers and all(summary.get("status") == PASS for summary in comparison_results.values()) else STOP
    report = {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "status": status,
        "decision": status,
        "report_semantics": "diagnostic fixed ranking comparison report",
        "diagnostic_method_id": diagnostic_method_id,
        "comparison_group": comparison_group,
        "fixed_config_ids": list(FIXED_COMPARISON_CONFIG_IDS),
        "top_k": FIXED_COMPARISON_TOP_K,
        "top10_view_source": "truncated_from_top20",
        "recommended_diagnostic_config_id": "R1",
        "recommendation_scope": "diagnostic_followup_only",
        "promotion_readiness": "not_allowed_in_this_report",
        **label_aggregation,
        "comparison_results": comparison_results,
        "case_diffs": case_diffs,
        "blockers": blockers,
        **DIAGNOSTIC_ONLY_FLAGS,
        **SHADOW_REPORT_BOUNDARY_FLAGS,
    }
    report["metrics_summary"] = build_pool500_fixed_ranking_metrics_summary(report)
    assert_pool500_summary_projection_matches_report(report, report["metrics_summary"])
    return report


def build_pool500_fixed_ranking_comparison_configs() -> dict[str, dict[str, Any]]:
    b0 = {
        "top_k": FIXED_COMPARISON_TOP_K,
        "rank_weights": dict(BASELINE_DIAGNOSTIC_UNIFORM_RANK_WEIGHTS),
        "normalized_additive_ranking": {"enabled": False},
    }
    configs = {
        "B0": deepcopy(b0),
        "D1": _merge_ranking_config(b0, {"topk_source_minimums": {"itemcf": 1}}),
        "D2": _merge_ranking_config(b0, {"topk_source_minimums": {"itemcf": 1, "semantic": 1, "category": 1}}),
        "A1": _merge_ranking_config(
            b0,
            {
                "normalized_additive_ranking": {
                    "enabled": True,
                    "weights": {
                        "source_signal": 0.2,
                        "item_feature": 0.2,
                        "freshness_quality": 0.1,
                        "near_miss_tiebreak_strength": 0.05,
                    },
                }
            },
        ),
        "A2": _merge_ranking_config(
            b0,
            {
                "normalized_additive_ranking": {
                    "enabled": True,
                    "weights": {
                        "source_signal": 0.4,
                        "item_feature": 0.4,
                        "freshness_quality": 0.2,
                        "near_miss_tiebreak_strength": 0.1,
                    },
                }
            },
        ),
        "R1": _merge_ranking_config(b0, {"fallback_heavy_topk_cap": {"enabled": True, "max_topk_ratio": 0.5}}),
        "R2": _merge_ranking_config(b0, {"source_diversity_constrained_rerank": {"enabled": True, "max_per_source_topk_ratio": 0.5}}),
        "R3": _merge_ranking_config(
            b0,
            {
                "normalized_additive_ranking": {
                    "enabled": True,
                    "weights": {
                        "source_signal": 0.2,
                        "item_feature": 0.2,
                        "freshness_quality": 0.1,
                        "near_miss_tiebreak_strength": 0.05,
                    },
                },
                "conservative_quality_guard": {"enabled": True},
                "ltr_model": {"enabled": False},
            },
        ),
    }
    return {config_id: configs[config_id] for config_id in FIXED_COMPARISON_CONFIG_IDS}


def build_pool500_fixed_ranking_metrics_summary(comparison_report: dict[str, Any]) -> dict[str, Any]:
    comparison_results = comparison_report.get("comparison_results")
    if not isinstance(comparison_results, dict):
        raise ValueError("comparison_report.comparison_results is required")
    return {
        "schema_version": comparison_report.get("schema_version"),
        "status": comparison_report.get("status"),
        "decision": comparison_report.get("decision"),
        "report_semantics": comparison_report.get("report_semantics"),
        "fixed_config_ids": list(comparison_report.get("fixed_config_ids") or []),
        "top_k": comparison_report.get("top_k"),
        "top10_view_source": comparison_report.get("top10_view_source"),
        "recommended_diagnostic_config_id": comparison_report.get("recommended_diagnostic_config_id"),
        "recommendation_scope": comparison_report.get("recommendation_scope"),
        "promotion_readiness": comparison_report.get("promotion_readiness"),
        "label_evaluation_state_by_config": comparison_report.get("label_evaluation_state_by_config", {}),
        "all_configs_label_comparable": comparison_report.get("all_configs_label_comparable", False),
        "baseline_label_comparable": comparison_report.get("baseline_label_comparable", False),
        "label_metric_eligibility": comparison_report.get("label_metric_eligibility", False),
        "label_ineligible_reason": comparison_report.get("label_ineligible_reason"),
        "label_metric_definition_version": comparison_report.get("label_metric_definition_version"),
        "per_config": {
            config_id: {
                "status": summary.get("status"),
                "decision": summary.get("decision"),
                "interpretation_label": summary.get("interpretation_label"),
                "fallback_exposure_topk_ratio": summary.get("fallback_exposure_topk_ratio"),
                "metadata_missing_rate": summary.get("metadata_missing_rate"),
                "category_missing_rate": summary.get("category_missing_rate"),
                "top_category_ratio": summary.get("top_category_ratio"),
                "topk_source_mix": summary.get("topk_source_mix", {}),
                "repaired_user_topk_stats": summary.get("repaired_user_topk_stats", {}),
                "label_state": summary.get("label_state"),
                "label_discovery_policy": summary.get("label_discovery_policy"),
                "label_artifact_metadata": _public_label_artifact_metadata(summary.get("label_artifact_metadata")),
                "label_metrics_available": summary.get("label_metrics_available", False),
                "label_adjacent_metrics": summary.get("label_adjacent_metrics", {}),
                "blocker_count": len(summary.get("blockers", [])),
            }
            for config_id, summary in comparison_results.items()
            if isinstance(summary, dict)
        },
        "blocker_count": len(comparison_report.get("blockers", [])),
    }


def assert_pool500_summary_projection_matches_report(report: dict[str, Any], summary: dict[str, Any]) -> None:
    allowed_top_level = {
        "schema_version",
        "status",
        "decision",
        "report_semantics",
        "fixed_config_ids",
        "top_k",
        "top10_view_source",
        "recommended_diagnostic_config_id",
        "recommendation_scope",
        "promotion_readiness",
        "label_evaluation_state_by_config",
        "all_configs_label_comparable",
        "baseline_label_comparable",
        "label_metric_eligibility",
        "label_ineligible_reason",
        "label_metric_definition_version",
        "per_config",
        "blocker_count",
    }
    extra = set(summary) - allowed_top_level
    if extra:
        raise AssertionError(f"summary contains report-absent authority fields: {sorted(extra)}")
    for field in allowed_top_level - {"per_config", "blocker_count"}:
        if summary.get(field) != report.get(field):
            raise AssertionError(f"summary field {field} does not match report")
    semantic_blockers = [
        *_validate_forbidden_semantics(report),
        *_validate_forbidden_semantics(summary),
        *_validate_fixed_report_summary_ready_semantics(report),
        *_validate_fixed_report_summary_ready_semantics(summary),
    ]
    if semantic_blockers:
        raise AssertionError(f"report/summary contains forbidden semantics: {semantic_blockers}")
    if summary.get("blocker_count") != len(report.get("blockers", [])):
        raise AssertionError("summary blocker_count does not match report")
    comparison_results = report.get("comparison_results") or {}
    per_config = summary.get("per_config") or {}
    if set(per_config) != set(comparison_results):
        raise AssertionError("summary per_config ids do not match report")
    per_config_allowed = {
        "status",
        "decision",
        "interpretation_label",
        "fallback_exposure_topk_ratio",
        "metadata_missing_rate",
        "category_missing_rate",
        "top_category_ratio",
        "topk_source_mix",
        "repaired_user_topk_stats",
        "label_state",
        "label_discovery_policy",
        "label_artifact_metadata",
        "label_metrics_available",
        "label_adjacent_metrics",
        "blocker_count",
    }
    for config_id, projected in per_config.items():
        source = comparison_results[config_id]
        extra_config_fields = set(projected) - per_config_allowed
        if extra_config_fields:
            raise AssertionError(f"summary config {config_id} contains report-absent fields: {sorted(extra_config_fields)}")
        for field in per_config_allowed - {"blocker_count", "label_artifact_metadata"}:
            if projected.get(field) != source.get(field):
                raise AssertionError(f"summary config {config_id} field {field} does not match report")
        if projected.get("label_artifact_metadata") != _public_label_artifact_metadata(source.get("label_artifact_metadata")):
            raise AssertionError(f"summary config {config_id} label_artifact_metadata does not match public report projection")
        if projected.get("blocker_count") != len(source.get("blockers", [])):
            raise AssertionError(f"summary config {config_id} blocker_count does not match report")


def _merge_ranking_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _fixed_comparison_run_summary(config_id: str, config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    ranking_results = result.get("ranking_results", {}) if result.get("status") == PASS else {}
    persisted_ranking_results = _redact_ranking_results(ranking_results)
    shadow_metrics = result.get("evidence", {}).get("shadow_metrics", {})
    return {
        "config_id": config_id,
        "status": result.get("status"),
        "decision": result.get("decision"),
        "top_k": FIXED_COMPARISON_TOP_K,
        "config": config,
        "config_delta_vs_B0": _config_delta_vs_b0(config),
        "interpretation_label": result.get("validation", {}).get("interpretation_label") or result.get("evidence", {}).get("interpretation_label"),
        "shadow_metrics": shadow_metrics,
        "fallback_exposure_topk_ratio": shadow_metrics.get("fallback_exposure_topk_ratio"),
        "metadata_missing_rate": shadow_metrics.get("metadata_missing_rate"),
        "category_missing_rate": shadow_metrics.get("category_missing_rate"),
        "top_category_ratio": shadow_metrics.get("top_category_ratio"),
        "topk_source_mix": shadow_metrics.get("topk_source_mix", {}),
        "repaired_user_topk_stats": shadow_metrics.get("repaired_user_topk_stats", {}),
        "label_metrics_available": result.get("evidence", {}).get("label_metrics_available", shadow_metrics.get("label_metrics_available", False)),
        "label_adjacent_metrics": result.get("evidence", {}).get("label_adjacent_metrics", shadow_metrics.get("label_adjacent_metrics", {})),
        "label_state": result.get("evidence", {}).get("label_state"),
        "label_discovery_policy": result.get("evidence", {}).get("label_discovery_policy"),
        "label_artifact_metadata": result.get("evidence", {}).get("label_artifact_metadata"),
        "label_blockers": result.get("evidence", {}).get("label_blockers", []),
        "stage_trace_coverage": shadow_metrics.get("stage_trace_coverage", {}),
        "topk_source_contribution": shadow_metrics.get("topk_source_contribution", {}),
        "ranking_results": persisted_ranking_results,
        "top10_results": {user_id: items[:FIXED_COMPARISON_TOP10_K] for user_id, items in persisted_ranking_results.items()},
        "score_trace": {user_id: [{"parent_asin": item.get("parent_asin"), "score_trace": item.get("score_trace", [])} for item in items] for user_id, items in persisted_ranking_results.items()},
        "rank_movement": {user_id: [{"parent_asin": item.get("parent_asin"), "rank_movement": item.get("rank_movement", {})} for item in items] for user_id, items in persisted_ranking_results.items()},
        "score_components": {user_id: [{"parent_asin": item.get("parent_asin"), "score_components": item.get("score_components", {})} for item in items] for user_id, items in persisted_ranking_results.items()},
        "blockers": result.get("blockers", []),
    }


def _apply_fixed_comparison_label_context(
    *,
    comparison_results: dict[str, dict[str, Any]],
    candidate_path: Path,
    manifest_path: Path,
    explicit_label_artifact_path: str | Path | None,
    evaluator_enabled: bool,
) -> dict[str, Any]:
    union_pairs = _topk_union_pairs(comparison_results)
    full_pool_pairs = _full_pool_candidate_pairs(candidate_path)
    discovered = _discover_pool500_label_artifact(candidate_path, manifest_path, explicit_label_artifact_path)
    metadata = None
    if discovered.get("source") in {"explicit", "manifest"} and discovered.get("path"):
        metadata = _label_artifact_metadata(discovered["path"], None, candidate_pairs=union_pairs, full_pool_candidate_pairs=full_pool_pairs)
    blockers = list(discovered.get("blockers", []))
    if metadata is not None:
        blockers.extend(metadata.get("blockers", []))
    state = _pool500_label_state(evaluator_enabled, metadata, blockers, discovered.get("source"))
    metrics_available = state == "label_comparable"
    sanitized_metadata = _public_label_artifact_metadata(metadata)
    for summary in comparison_results.values():
        config_metrics = _label_artifact_metrics_for_ranking(metadata, summary.get("ranking_results", {}), FIXED_COMPARISON_TOP_K) if metrics_available else {}
        summary["label_metrics_available"] = metrics_available
        summary["label_adjacent_metrics"] = config_metrics
        summary["label_state"] = state
        summary["label_discovery_policy"] = "explicit_label_path > manifest_declared_label_path > known_output_directory_read_only_discovery"
        summary["label_artifact_metadata"] = sanitized_metadata
        summary["label_blockers"] = blockers
    state_by_config = {config_id: summary.get("label_state") for config_id, summary in comparison_results.items()}
    all_comparable = bool(comparison_results) and all(state == "label_comparable" for state in state_by_config.values())
    baseline_comparable = state_by_config.get("B0") == "label_comparable"
    return {
        "label_evaluation_state_by_config": state_by_config,
        "all_configs_label_comparable": all_comparable,
        "baseline_label_comparable": baseline_comparable,
        "label_metric_eligibility": all_comparable,
        "label_ineligible_reason": None if all_comparable else _label_ineligible_reason(state_by_config, blockers),
        "label_metric_definition_version": LABEL_METRIC_DEFINITION_VERSION,
    }


def _topk_union_pairs(comparison_results: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for summary in comparison_results.values():
        ranking_results = summary.get("ranking_results", {})
        if not isinstance(ranking_results, dict):
            continue
        for user_id, items in ranking_results.items():
            for item in items[:FIXED_COMPARISON_TOP_K]:
                if isinstance(item, dict) and item.get("parent_asin"):
                    pairs.add((str(user_id), str(item.get("parent_asin"))))
    return pairs


def _full_pool_candidate_pairs(candidate_path: Path) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in iter_jsonl(candidate_path):
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if user_id and item_id:
            pairs.add((user_id, item_id))
    return pairs


def _label_ineligible_reason(state_by_config: dict[str, Any], blockers: list[dict[str, Any]]) -> str | None:
    states = sorted({str(state) for state in state_by_config.values()})
    if not states:
        return "no_fixed_config_results"
    if blockers:
        codes = sorted({str(blocker.get("code")) for blocker in blockers})
        return f"label_state={','.join(states)}; blockers={','.join(codes)}"
    return f"label_state={','.join(states)}"


def _public_label_artifact_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if metadata is None:
        return None
    fields = (
        "path",
        "hash",
        "row_count",
        "schema_version",
        "join_key",
        "candidate_coverage",
        "user_coverage",
        "positive_coverage",
        "topk_union_candidate_coverage",
        "user_label_coverage",
        "positive_user_coverage",
        "full_pool_candidate_coverage_diagnostic",
        "positive_count",
        "coverage_thresholds",
        "failed_thresholds",
        "eligible_user_count",
    )
    return {field: metadata.get(field) for field in fields if field in metadata}


def _redact_ranking_results(ranking_results: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {user_id: [_ranking_item_payload(item) for item in items] for user_id, items in ranking_results.items()}



def _ranking_result_explainability_blockers(config_id: str, ranking_results: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for user_id, items in ranking_results.items():
        for item in items:
            missing = [field for field in FIXED_COMPARISON_REQUIRED_ITEM_FIELDS if field not in item]
            if missing:
                blockers.append(_blocker("POOL500_FIXED_COMPARISON_EXPLAINABILITY_FIELD_MISSING", {"config_id": config_id, "user_id": user_id, "parent_asin": item.get("parent_asin"), "missing_fields": missing}))
            stages = {trace.get("stage") for trace in item.get("score_trace", []) if isinstance(trace, dict)}
            if item.get("score_trace") is not None and stages != {"coarse", "fine", "rerank"}:
                blockers.append(_blocker("POOL500_FIXED_COMPARISON_SCORE_TRACE_INCOMPLETE", {"config_id": config_id, "user_id": user_id, "parent_asin": item.get("parent_asin"), "stages": sorted(stages)}))
            forbidden = sorted({str(source) for source in item.get("sources", []) if str(source) in FORBIDDEN_SOURCE_LABELS})
            if forbidden:
                blockers.append(_blocker("POOL500_FIXED_COMPARISON_FORBIDDEN_SOURCE_LABEL", {"config_id": config_id, "user_id": user_id, "parent_asin": item.get("parent_asin"), "sources": forbidden}))
    return blockers


def _case_diff_rows(
    baseline_results: dict[str, list[dict[str, Any]]],
    variant_results: dict[str, list[dict[str, Any]]],
    interpretation_label: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for user_id in sorted(set(baseline_results) | set(variant_results)):
        baseline_by_item = {item.get("parent_asin"): item for item in baseline_results.get(user_id, []) if item.get("parent_asin")}
        variant_items = variant_results.get(user_id, [])[:FIXED_COMPARISON_TOP10_K]
        user_rows: list[dict[str, Any]] = []
        for variant_rank, variant_item in enumerate(variant_items, start=1):
            parent_asin = variant_item.get("parent_asin")
            baseline_item = baseline_by_item.get(parent_asin, {})
            baseline_rank = baseline_item.get("final_rank")
            variant_final_rank = variant_item.get("final_rank", variant_rank)
            rank_delta = None if baseline_rank is None else int(variant_final_rank) - int(baseline_rank)
            baseline_score = baseline_item.get("score")
            variant_score = variant_item.get("score")
            score_delta = None if baseline_score is None or variant_score is None else round(float(variant_score) - float(baseline_score), 6)
            baseline_sources = set(baseline_item.get("sources", []))
            variant_sources = set(variant_item.get("sources", []))
            user_rows.append(
                {
                    "user_id": user_id,
                    "parent_asin": parent_asin,
                    "baseline_rank": baseline_rank,
                    "variant_rank": variant_final_rank,
                    "rank_delta": rank_delta,
                    "baseline_score": baseline_score,
                    "variant_score": variant_score,
                    "score_delta": score_delta,
                    "sources": variant_item.get("sources", []),
                    "category": variant_item.get("category"),
                    "baseline_score_trace": baseline_item.get("score_trace", []),
                    "variant_score_trace": variant_item.get("score_trace", []),
                    "baseline_score_components": baseline_item.get("score_components", {}),
                    "variant_score_components": variant_item.get("score_components", {}),
                    "rank_movement": variant_item.get("rank_movement"),
                    "dominant_score_component": _dominant_score_component(variant_item.get("score_components", {})),
                    "source_delta": {"added": sorted(variant_sources - baseline_sources), "removed": sorted(baseline_sources - variant_sources)},
                    "category_delta": {"baseline": baseline_item.get("category"), "variant": variant_item.get("category")},
                    "interpretation_label": interpretation_label,
                }
            )
        if user_rows:
            rows.append(max(user_rows, key=lambda row: abs(row["rank_delta"] or 0)))
    return sorted(rows, key=lambda row: abs(row["rank_delta"] or 0), reverse=True)[:10]


def _case_diff_blockers(case_diffs: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    required_fields = {
        "user_id",
        "parent_asin",
        "baseline_rank",
        "variant_rank",
        "rank_delta",
        "baseline_score",
        "variant_score",
        "score_delta",
        "sources",
        "category",
        "baseline_score_trace",
        "variant_score_trace",
        "baseline_score_components",
        "variant_score_components",
        "rank_movement",
        "dominant_score_component",
        "source_delta",
        "category_delta",
        "interpretation_label",
    }
    for config_id, rows in case_diffs.items():
        for row in rows:
            missing = sorted(field for field in required_fields if field not in row)
            if missing:
                blockers.append(_blocker("POOL500_FIXED_COMPARISON_CASE_DIFF_FIELD_MISSING", {"config_id": config_id, "missing_fields": missing, "row": row}))
            forbidden = sorted({str(source) for source in row.get("sources", []) if str(source) in FORBIDDEN_SOURCE_LABELS})
            if forbidden:
                blockers.append(_blocker("POOL500_FIXED_COMPARISON_CASE_DIFF_FORBIDDEN_SOURCE", {"config_id": config_id, "sources": forbidden}))
            stages = {trace.get("stage") for trace in row.get("variant_score_trace", []) if isinstance(trace, dict)}
            if row.get("variant_score_trace") and stages != {"coarse", "fine", "rerank"}:
                blockers.append(_blocker("POOL500_FIXED_COMPARISON_CASE_DIFF_TRACE_INCOMPLETE", {"config_id": config_id, "parent_asin": row.get("parent_asin"), "stages": sorted(stages)}))
    return blockers


def _dominant_score_component(score_components: dict[str, Any]) -> str | None:
    contributions: dict[str, float] = {}
    for name, diagnostics in score_components.items():
        if isinstance(diagnostics, dict) and diagnostics.get("contribution") is not None:
            contributions[str(name)] = abs(float(diagnostics.get("contribution") or 0.0))
    if not contributions:
        return None
    return max(contributions, key=contributions.get)


def build_pool500_diagnostic_frozen_pool_ranking_evidence(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    input_validation: dict[str, Any],
    shadow_metrics: dict[str, Any],
    source_artifact_gate_result: dict[str, Any] | None = None,
    source_shadow_evidence_validation: dict[str, Any] | None = None,
    label_context: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    label_context = label_context or {"label_state": "mechanism_only", "label_artifact_metadata": None, "label_blockers": []}
    return {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "report_semantics": "diagnostic frozen-pool shadow ranking report",
        "diagnostic_method_id": diagnostic_method_id,
        "comparison_group": comparison_group,
        "input_contract": DIAGNOSTIC_FROZEN_POOL_INPUT_CONTRACT,
        "pool500_candidates_path": input_validation.get("pool500_candidates_path"),
        "candidate_manifest_path": input_validation.get("candidate_manifest_path"),
        "expected_candidate_hash": input_validation.get("expected_candidate_hash"),
        "computed_candidate_hash": input_validation.get("computed_candidate_hash"),
        "expected_manifest_hash": input_validation.get("expected_manifest_hash"),
        "computed_manifest_hash": input_validation.get("computed_manifest_hash"),
        "candidate_row_count": input_validation.get("candidate_row_count"),
        "user_count": input_validation.get("user_count"),
        "candidate_count_distribution": input_validation.get("candidate_count_distribution"),
        "underfilled_user_count": input_validation.get("underfilled_user_count"),
        "underfilled_user_ratio": input_validation.get("underfilled_user_ratio"),
        "per_user_candidate_count": input_validation.get("per_user_candidate_count"),
        "source_coverage": input_validation.get("source_coverage"),
        "category_coverage": input_validation.get("category_coverage"),
        "multi_source_item_ratio": input_validation.get("multi_source_item_ratio"),
        "metadata_missing_rate": input_validation.get("metadata_missing_rate"),
        "category_missing_rate": input_validation.get("category_missing_rate"),
        "top_category_ratio": input_validation.get("top_category_ratio"),
        "interpretation_label": input_validation.get("interpretation_label"),
        "source_artifact_gate_decision_observed": (source_artifact_gate_result or {}).get("decision"),
        "source_shadow_evidence_decision_observed": (source_shadow_evidence_validation or {}).get("status"),
        "shadow_metrics": dict(shadow_metrics),
        "fallback_exposure_topk_ratio": shadow_metrics.get("fallback_exposure_topk_ratio"),
        "topk_source_mix": shadow_metrics.get("topk_source_mix", {}),
        "repaired_user_topk_stats": shadow_metrics.get("repaired_user_topk_stats", {}),
        "label_metrics_available": label_context.get("label_metrics_available", shadow_metrics.get("label_metrics_available", False)),
        "label_adjacent_metrics": label_context.get("label_adjacent_metrics", shadow_metrics.get("label_adjacent_metrics", {})),
        "label_state": label_context.get("label_state"),
        "label_discovery_policy": label_context.get("label_discovery_policy"),
        "label_artifact_metadata": label_context.get("label_artifact_metadata"),
        "label_blockers": label_context.get("label_blockers", []),
        "config_delta_vs_B0": _config_delta_vs_b0(shadow_metrics.get("config", {})) if isinstance(shadow_metrics.get("config"), dict) else {},
        "input_validation_status": PASS if not input_validation.get("blockers") else STOP,
        **DIAGNOSTIC_ONLY_FLAGS,
        **SHADOW_REPORT_BOUNDARY_FLAGS,
        "generated_at": generated_at,
    }


def validate_pool500_diagnostic_frozen_pool_ranking_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if evidence.get("schema_version") != DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_SCHEMA_VERSION_MISMATCH", {"schema_version": evidence.get("schema_version")}))
    if evidence.get("schema_version") == SCHEMA_VERSION:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_FORMAL_SCHEMA_FORBIDDEN", {"schema_version": evidence.get("schema_version")}))
    if evidence.get("input_contract") != DIAGNOSTIC_FROZEN_POOL_INPUT_CONTRACT:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_INPUT_CONTRACT_REQUIRED", {"input_contract": evidence.get("input_contract")}))
    for field, expected in DIAGNOSTIC_ONLY_FLAGS.items():
        if evidence.get(field) is not expected:
            blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_DIAGNOSTIC_FLAG_REQUIRED", {"field": field, "value": evidence.get(field), "required": expected}))
    for field, expected in SHADOW_REPORT_BOUNDARY_FLAGS.items():
        if evidence.get(field) is not expected:
            blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_BOUNDARY_FLAG_REQUIRED", {"field": field, "value": evidence.get(field), "required": expected}))
    for field in ("pool500_candidates_path", "candidate_manifest_path", "expected_candidate_hash", "computed_candidate_hash", "expected_manifest_hash", "computed_manifest_hash"):
        if not evidence.get(field):
            blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_LINEAGE_REQUIRED", {"field": field, "value": evidence.get(field)}))
    if evidence.get("expected_candidate_hash") != evidence.get("computed_candidate_hash"):
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_CANDIDATE_HASH_MISMATCH", {"expected": evidence.get("expected_candidate_hash"), "computed": evidence.get("computed_candidate_hash")}))
    if evidence.get("expected_manifest_hash") != evidence.get("computed_manifest_hash"):
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_MANIFEST_HASH_MISMATCH", {"expected": evidence.get("expected_manifest_hash"), "computed": evidence.get("computed_manifest_hash")}))
    if evidence.get("source_artifact_gate_decision") == FULL_POOL500_READY or evidence.get("source_artifact_gate_decision_observed") == FULL_POOL500_READY:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_FULL_READY_FORBIDDEN", {"source_artifact_gate_decision": evidence.get("source_artifact_gate_decision"), "source_artifact_gate_decision_observed": evidence.get("source_artifact_gate_decision_observed")}))
    if evidence.get("label_state") == "blocked":
        blockers.append(_blocker("POOL500_DIAGNOSTIC_LABEL_BLOCKED", {"label_state": evidence.get("label_state"), "label_blockers": evidence.get("label_blockers", [])}))
    blockers.extend(_validate_diagnostic_required_aggregations(evidence))
    blockers.extend(_validate_forbidden_source_labels(evidence))
    blockers.extend(_validate_forbidden_semantics(evidence))
    interpretation_label = "blocked" if blockers else _diagnostic_interpretation_label(evidence)
    return {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "decision": PASS if not blockers else STOP,
        "status": PASS if not blockers else STOP,
        **DIAGNOSTIC_ONLY_FLAGS,
        **SHADOW_REPORT_BOUNDARY_FLAGS,
        "interpretation_label": interpretation_label,
        "blockers": blockers,
    }


def validate_pool500_shadow_ranking_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if evidence.get("schema_version") != SCHEMA_VERSION:
        blockers.append(_blocker("POOL500_SHADOW_RANKING_SCHEMA_VERSION_MISMATCH", {"schema_version": evidence.get("schema_version")}))
    for field, expected in DIAGNOSTIC_ONLY_FLAGS.items():
        if evidence.get(field) is not expected:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_DIAGNOSTIC_FLAG_REQUIRED", {"field": field, "value": evidence.get(field), "required": expected}))
    for field, expected in SHADOW_REPORT_BOUNDARY_FLAGS.items():
        if evidence.get(field) is not expected:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_BOUNDARY_FLAG_REQUIRED", {"field": field, "value": evidence.get(field), "required": expected}))
    if not evidence.get("diagnostic_method_id"):
        blockers.append(_blocker("POOL500_SHADOW_RANKING_METHOD_ID_REQUIRED", {"diagnostic_method_id": evidence.get("diagnostic_method_id")}))
    if not evidence.get("comparison_group"):
        blockers.append(_blocker("POOL500_SHADOW_RANKING_COMPARISON_GROUP_REQUIRED", {"comparison_group": evidence.get("comparison_group")}))
    if not isinstance(evidence.get("shadow_metrics"), dict):
        blockers.append(_blocker("POOL500_SHADOW_RANKING_METRICS_REQUIRED", {"shadow_metrics_type": type(evidence.get("shadow_metrics")).__name__}))
    blockers.extend(_validate_hard_gate_fields(evidence))
    artifact_decision = evidence.get("source_artifact_gate_decision")
    if artifact_decision is not None and artifact_decision != FULL_POOL500_READY:
        blockers.append(_blocker("POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY", {"source_artifact_gate_decision": artifact_decision, "required": FULL_POOL500_READY}))
    shadow_decision = evidence.get("source_shadow_evidence_decision")
    if shadow_decision is not None and shadow_decision != PASS:
        blockers.append(_blocker("POOL500_SOURCE_SHADOW_EVIDENCE_NOT_PASS", {"source_shadow_evidence_decision": shadow_decision, "required": PASS}))
    blockers.extend(_validate_forbidden_semantics(evidence))
    return {
        "schema_version": SCHEMA_VERSION,
        "decision": PASS if not blockers else STOP,
        "status": PASS if not blockers else STOP,
        **DIAGNOSTIC_ONLY_FLAGS,
        **SHADOW_REPORT_BOUNDARY_FLAGS,
        "blockers": blockers,
    }


def _validate_hard_gate_fields(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for field in ("lineage_hash", "baseline_artifact_hash", "failure_recovery_strategy", "cleanup_strategy"):
        value = evidence.get(field)
        if not isinstance(value, str) or not value.strip():
            blockers.append(_blocker("POOL500_SHADOW_RANKING_HARD_GATE_FIELD_REQUIRED", {"field": field, "value": value}))
    resource_budget = evidence.get("resource_budget")
    if not isinstance(resource_budget, dict) or not resource_budget:
        blockers.append(_blocker("POOL500_SHADOW_RANKING_RESOURCE_BUDGET_REQUIRED", {"resource_budget": resource_budget}))
        return blockers
    cap_fields = [field for field in resource_budget if field.startswith("max_")]
    positive_caps = [field for field in cap_fields if _is_positive_number(resource_budget.get(field))]
    if not positive_caps:
        blockers.append(_blocker("POOL500_SHADOW_RANKING_RESOURCE_BUDGET_CAP_REQUIRED", {"resource_budget": resource_budget, "required_prefix": "max_"}))
    invalid_caps = [field for field in cap_fields if not _is_positive_number(resource_budget.get(field))]
    for field in invalid_caps:
        blockers.append(_blocker("POOL500_SHADOW_RANKING_RESOURCE_BUDGET_CAP_INVALID", {"field": field, "value": resource_budget.get(field)}))
    return blockers


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def _preflight_blockers(
    artifact_gate_result: dict[str, Any],
    recall_shadow_evidence_validation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    artifact_decision = artifact_gate_result.get("decision") if isinstance(artifact_gate_result, dict) else None
    artifact_status = artifact_gate_result.get("status") if isinstance(artifact_gate_result, dict) else None
    if artifact_decision != FULL_POOL500_READY or artifact_status not in {None, PASS}:
        blockers.append(_blocker("POOL500_SOURCE_ARTIFACT_GATE_NOT_FULL_READY", {"source_artifact_gate_decision": artifact_decision, "source_artifact_gate_status": artifact_status, "required_decision": FULL_POOL500_READY, "required_status": PASS}))
    if recall_shadow_evidence_validation is not None and recall_shadow_evidence_validation.get("status") != PASS:
        blockers.append(_blocker("POOL500_SOURCE_SHADOW_EVIDENCE_NOT_PASS", {"source_shadow_evidence_decision": recall_shadow_evidence_validation.get("decision"), "source_shadow_evidence_status": recall_shadow_evidence_validation.get("status"), "required": PASS}))
    return blockers


def _stop_result(
    *,
    diagnostic_method_id: str,
    comparison_group: str,
    artifact_gate_result: dict[str, Any],
    recall_shadow_evidence_validation: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
    adapter_result: dict[str, Any] | None,
    top_k: int,
) -> dict[str, Any]:
    evidence = build_pool500_shadow_ranking_evidence(
        diagnostic_method_id=diagnostic_method_id,
        comparison_group=comparison_group,
        shadow_metrics={"user_count": 0, "top_k": top_k, "stopped_before_ranking": True},
        source_artifact_gate_result=artifact_gate_result,
        source_shadow_evidence_validation=recall_shadow_evidence_validation,
    )
    validation = validate_pool500_shadow_ranking_evidence(evidence)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STOP,
        "decision": STOP,
        "evidence": evidence,
        "validation": validation,
        "ranking_results": {},
        "adapter_result": _adapter_summary(adapter_result),
        "blockers": [*blockers, *validation["blockers"]],
        "diagnostics": [],
    }


def _run_pool500_ranking_core(
    *,
    candidates_by_user: dict[str, list[MergedCandidate]] | None,
    rows: Iterable[dict[str, Any]] | None,
    config: dict[str, Any],
    top_k: int,
    extra_allowed_sources: set[str] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    adapter_result: dict[str, Any] | None = None
    if candidates_by_user is None:
        if rows is None:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_INPUT_REQUIRED", {"required": "candidates_by_user or rows"}))
            candidates_by_user = {}
        else:
            adapter_result = adapt_pool500_rows_to_candidates(rows, extra_allowed_sources=extra_allowed_sources)
            candidates_by_user = adapter_result["candidates_by_user"]
            if adapter_result.get("status") != PASS:
                blockers.extend(adapter_result.get("blockers", []))
    if blockers:
        return {
            "status": STOP,
            "ranking_results": {},
            "shadow_metrics": {"user_count": 0, "top_k": top_k, "stopped_before_ranking": True},
            "adapter_result": adapter_result,
            "blockers": blockers,
            "diagnostics": adapter_result.get("diagnostics", []) if isinstance(adapter_result, dict) else [],
        }

    ranking_results: dict[str, list[dict[str, Any]]] = {}
    for user_id in sorted(candidates_by_user):
        run_top_k = len(candidates_by_user[user_id]) if _uses_shadow_local_rerank(config) else top_k
        ranking = rank_candidates(user_id, candidates_by_user[user_id], config, top_k=run_top_k)
        candidate_by_item = {candidate.item_id: candidate for candidate in candidates_by_user[user_id]}
        ranked_items = [_attach_shadow_candidate_metadata(_ranking_item_payload(item), candidate_by_item) for item in ranking.items]
        ranked_items = _apply_shadow_local_diagnostic_rerank(ranked_items, config, top_k)
        ranking_results[user_id] = ranked_items
    shadow_metrics = _shadow_metrics(candidates_by_user, ranking_results, top_k)
    shadow_metrics["config"] = dict(config)
    return {
        "status": PASS,
        "ranking_results": ranking_results,
        "shadow_metrics": shadow_metrics,
        "adapter_result": adapter_result,
        "blockers": [],
        "diagnostics": adapter_result.get("diagnostics", []) if isinstance(adapter_result, dict) else [],
    }


def _validate_diagnostic_frozen_pool_input(
    *,
    pool500_candidates_path: str | Path,
    candidate_manifest_path: str | Path,
    expected_candidate_hash: str,
    expected_manifest_hash: str,
    diagnostic_input_contract: str,
    source_artifact_gate_result: dict[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    candidate_path = Path(pool500_candidates_path)
    manifest_path = Path(candidate_manifest_path)
    if diagnostic_input_contract != DIAGNOSTIC_FROZEN_POOL_INPUT_CONTRACT:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_INPUT_CONTRACT_REQUIRED", {"input_contract": diagnostic_input_contract}))
    for field, path in (("pool500_candidates_path", candidate_path), ("candidate_manifest_path", manifest_path)):
        path_text = str(path)
        if _path_uses_inferred_artifact(path_text):
            blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_INFERRED_PATH_FORBIDDEN", {"field": field, "path": path_text}))
        if not path_text or not path.exists() or path.is_dir():
            blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_PATH_REQUIRED", {"field": field, "path": path_text}))
    if not expected_candidate_hash:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_HASH_REQUIRED", {"field": "expected_candidate_hash"}))
    if not expected_manifest_hash:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_HASH_REQUIRED", {"field": "expected_manifest_hash"}))

    computed_candidate_hash = _sha256_file(candidate_path) if candidate_path.exists() and not candidate_path.is_dir() else None
    computed_manifest_hash = _sha256_file(manifest_path) if manifest_path.exists() and not manifest_path.is_dir() else None
    if expected_candidate_hash and computed_candidate_hash and expected_candidate_hash != computed_candidate_hash:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_CANDIDATE_HASH_MISMATCH", {"expected": expected_candidate_hash, "computed": computed_candidate_hash}))
    if expected_manifest_hash and computed_manifest_hash and expected_manifest_hash != computed_manifest_hash:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_MANIFEST_HASH_MISMATCH", {"expected": expected_manifest_hash, "computed": computed_manifest_hash}))

    manifest: dict[str, Any] = {}
    if manifest_path.exists() and not manifest_path.is_dir():
        manifest = read_json(manifest_path)
        blockers.extend(_diagnostic_manifest_blockers(manifest))
    if source_artifact_gate_result and source_artifact_gate_result.get("decision") == FULL_POOL500_READY:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_FULL_READY_FORBIDDEN", {"source_artifact_gate_decision": source_artifact_gate_result.get("decision")}))
    stats = _candidate_file_stats(candidate_path) if candidate_path.exists() and not candidate_path.is_dir() else {}
    stats["interpretation_label"] = _diagnostic_interpretation_label({**stats, "blockers": blockers}) if stats else None
    return {
        "status": PASS if not blockers else STOP,
        "blockers": blockers,
        "pool500_candidates_path": str(candidate_path),
        "candidate_manifest_path": str(manifest_path),
        "expected_candidate_hash": expected_candidate_hash,
        "computed_candidate_hash": computed_candidate_hash,
        "expected_manifest_hash": expected_manifest_hash,
        "computed_manifest_hash": computed_manifest_hash,
        **stats,
    }


def _build_pool500_label_context(
    *,
    candidate_path: Path,
    manifest_path: Path,
    explicit_label_artifact_path: str | Path | None,
    evaluator_enabled: bool,
    ranking_results: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    discovered = _discover_pool500_label_artifact(candidate_path, manifest_path, explicit_label_artifact_path)
    metadata = None
    if discovered.get("source") in {"explicit", "manifest"} and discovered.get("path"):
        metadata = _label_artifact_metadata(discovered["path"], ranking_results)
    blockers = list(discovered.get("blockers", []))
    if metadata is not None:
        blockers.extend(metadata.get("blockers", []))
    state = _pool500_label_state(evaluator_enabled, metadata, blockers, discovered.get("source"))
    return {
        "label_discovery_policy": "explicit_label_path > manifest_declared_label_path > known_output_directory_read_only_discovery",
        "label_artifact_source": discovered.get("source"),
        "label_artifact_metadata": metadata,
        "label_state": state,
        "label_metrics_available": state == "label_comparable",
        "label_adjacent_metrics": _label_artifact_adjacent_metrics(metadata) if state == "label_comparable" else {},
        "label_blockers": blockers,
    }


def _discover_pool500_label_artifact(candidate_path: Path, manifest_path: Path, explicit_label_artifact_path: str | Path | None) -> dict[str, Any]:
    if explicit_label_artifact_path is not None:
        path = Path(explicit_label_artifact_path)
        return {"source": "explicit", "path": path if path.exists() and not path.is_dir() else None, "blockers": [] if path.exists() and not path.is_dir() else [_blocker("POOL500_LABEL_EXPLICIT_ARTIFACT_MISSING", {"path": str(path)})]}
    manifest = read_json(manifest_path) if manifest_path.exists() and not manifest_path.is_dir() else {}
    manifest_label_artifact = manifest.get("label_artifact")
    manifest_label_path = manifest.get("label_artifact_path") or manifest.get("label_path")
    if manifest_label_path is None and isinstance(manifest_label_artifact, dict):
        manifest_label_path = manifest_label_artifact.get("path")
    if manifest_label_path:
        path = Path(manifest_label_path)
        if not path.is_absolute():
            path = manifest_path.parent / path
        return {"source": "manifest", "path": path if path.exists() and not path.is_dir() else None, "blockers": [] if path.exists() and not path.is_dir() else [_blocker("POOL500_LABEL_MANIFEST_ARTIFACT_MISSING", {"path": str(path)})]}
    known_path = candidate_path.parent / "pool500_labels.jsonl"
    return {"source": "known_output_directory_read_only", "path": known_path if known_path.exists() and not known_path.is_dir() else None, "blockers": []}


def _label_artifact_metadata(
    path: Path,
    ranking_results: dict[str, list[dict[str, Any]]] | None,
    *,
    candidate_pairs: set[tuple[str, str]] | None = None,
    full_pool_candidate_pairs: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    row_count = 0
    positive_count = 0
    label_pairs: set[tuple[str, str]] = set()
    positive_pairs: set[tuple[str, str]] = set()
    label_users: set[str] = set()
    positive_users: set[str] = set()
    ranked_positions = _ranking_result_positions(ranking_results)
    evaluated_pairs = set(candidate_pairs) if candidate_pairs is not None else set(ranked_positions)
    full_pool_pairs = set(full_pool_candidate_pairs) if full_pool_candidate_pairs is not None else set(evaluated_pairs)
    candidate_users = {user_id for user_id, _ in evaluated_pairs}
    schema_version: str | None = None
    join_key: str | None = None
    for row in iter_jsonl(path):
        row_count += 1
        if schema_version is None:
            schema_version = str(row.get("schema_version") or "pool500_label_artifact_v1")
        user_id = str(row.get("user_id") or "")
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not user_id or not item_id:
            blockers.append(_blocker("POOL500_LABEL_JOIN_KEY_INVALID", {"row_number": row_count, "user_id": user_id, "item_id": item_id}))
            continue
        pair = (user_id, item_id)
        label_pairs.add(pair)
        label_users.add(user_id)
        if join_key is None:
            join_key = "user_id,parent_asin" if row.get("parent_asin") is not None else "user_id,item_id"
        try:
            positive = _label_row_positive(row)
        except ValueError as exc:
            blockers.append(_blocker("POOL500_LABEL_VALUE_INVALID", {"row_number": row_count, "error": str(exc)}))
            continue
        if positive:
            positive_count += 1
            positive_pairs.add(pair)
            positive_users.add(user_id)
    topk_union_candidate_coverage = round(len(evaluated_pairs & label_pairs) / len(evaluated_pairs), 6) if evaluated_pairs else 0.0
    full_pool_candidate_coverage = round(len(full_pool_pairs & label_pairs) / len(full_pool_pairs), 6) if full_pool_pairs else 0.0
    user_label_coverage = round(len(candidate_users & label_users) / len(candidate_users), 6) if candidate_users else 0.0
    positive_user_coverage = round(len(candidate_users & positive_users) / len(candidate_users), 6) if candidate_users else 0.0
    failed_thresholds = [
        name
        for name, threshold in STRICT_LABEL_GATE_THRESHOLDS.items()
        if {
            "topk_union_candidate_coverage": topk_union_candidate_coverage,
            "user_label_coverage": user_label_coverage,
            "positive_user_coverage": positive_user_coverage,
        }[name]
        < threshold
    ]
    if row_count == 0:
        blockers.append(_blocker("POOL500_LABEL_SCHEMA_INVALID", {"path": str(path), "reason": "empty_label_artifact"}))
    if schema_version not in {None, "pool500_label_artifact_v1"}:
        blockers.append(_blocker("POOL500_LABEL_SCHEMA_INVALID", {"path": str(path), "schema_version": schema_version}))
    if join_key not in {None, "user_id,parent_asin", "user_id,item_id"}:
        blockers.append(_blocker("POOL500_LABEL_JOIN_KEY_INVALID", {"join_key": join_key}))
    return {
        "path": str(path),
        "hash": _sha256_file(path),
        "row_count": row_count,
        "schema_version": schema_version,
        "join_key": join_key,
        "candidate_coverage": topk_union_candidate_coverage,
        "user_coverage": user_label_coverage,
        "positive_coverage": positive_user_coverage,
        "topk_union_candidate_coverage": topk_union_candidate_coverage,
        "user_label_coverage": user_label_coverage,
        "positive_user_coverage": positive_user_coverage,
        "full_pool_candidate_coverage_diagnostic": full_pool_candidate_coverage,
        "positive_count": positive_count,
        "positive_pairs": sorted(positive_pairs),
        "positive_pairs_by_user": _pairs_by_user(positive_pairs),
        "eligible_user_count": len(candidate_users & positive_users),
        "ranked_positive_positions": {f"{user_id}\t{item_id}": rank for (user_id, item_id), rank in ranked_positions.items() if (user_id, item_id) in positive_pairs},
        "coverage_thresholds": dict(STRICT_LABEL_GATE_THRESHOLDS),
        "failed_thresholds": failed_thresholds,
        "blockers": blockers,
    }


def _pairs_by_user(pairs: set[tuple[str, str]]) -> dict[str, list[str]]:
    by_user: dict[str, list[str]] = {}
    for user_id, item_id in sorted(pairs):
        by_user.setdefault(user_id, []).append(item_id)
    return by_user


def _ranking_result_positions(ranking_results: dict[str, list[dict[str, Any]]] | None) -> dict[tuple[str, str], int]:
    if not ranking_results:
        return {}
    positions: dict[tuple[str, str], int] = {}
    for user_id, items in ranking_results.items():
        for index, item in enumerate(items, start=1):
            if item.get("parent_asin"):
                positions[(str(user_id), str(item.get("parent_asin")))] = int(item.get("final_rank") or index)
    return positions


def _label_row_positive(row: dict[str, Any]) -> bool:
    for field in ("label_binary", "label", "holdout_hit", "is_hit", "clicked", "purchased"):
        if field in row:
            return _strict_positive_value(row.get(field))
    if "rating" in row:
        return float(row.get("rating") or 0.0) > 0.0
    return False


def _strict_positive_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) > 0.0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "positive"}:
            return True
        if normalized in {"0", "false", "no", "n", "negative", ""}:
            return False
        raise ValueError(f"Unsupported label value: {value!r}")
    return bool(value)


def _pool500_label_state(evaluator_enabled: bool, metadata: dict[str, Any] | None, blockers: list[dict[str, Any]], artifact_source: str | None) -> str:
    if blockers and all(blocker.get("code") in {"POOL500_LABEL_EXPLICIT_ARTIFACT_MISSING", "POOL500_LABEL_MANIFEST_ARTIFACT_MISSING"} for blocker in blockers):
        return "pending_label" if evaluator_enabled else "mechanism_only"
    if not evaluator_enabled:
        return "mechanism_only"
    if artifact_source not in {"explicit", "manifest"}:
        return "pending_label"
    if metadata is None:
        return "pending_label"
    if metadata.get("blockers") or not metadata.get("schema_version") or not metadata.get("join_key"):
        return "label_invalid"
    if not metadata.get("row_count") or metadata.get("failed_thresholds"):
        return "label_insufficient"
    return "label_comparable"


def _label_artifact_adjacent_metrics(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {
        "label_metric_definition_version": LABEL_METRIC_DEFINITION_VERSION,
        "label_row_count": metadata.get("row_count"),
        "label_positive_count": metadata.get("positive_count"),
        "candidate_coverage": metadata.get("candidate_coverage"),
        "user_coverage": metadata.get("user_coverage"),
        "positive_coverage": metadata.get("positive_coverage"),
        **_label_artifact_topk_metrics(metadata, {}, 20),
    }


def _label_artifact_metrics_for_ranking(metadata: dict[str, Any] | None, ranking_results: Any, k: int) -> dict[str, Any]:
    if not metadata or not isinstance(ranking_results, dict):
        return {}
    return {
        "label_metric_definition_version": LABEL_METRIC_DEFINITION_VERSION,
        "label_row_count": metadata.get("row_count"),
        "label_positive_count": metadata.get("positive_count"),
        "candidate_coverage": metadata.get("candidate_coverage"),
        "user_coverage": metadata.get("user_coverage"),
        "positive_coverage": metadata.get("positive_coverage"),
        **_label_artifact_topk_metrics(metadata, ranking_results, k),
    }


def _label_artifact_topk_metrics(metadata: dict[str, Any], ranking_results: dict[str, list[dict[str, Any]]], k: int) -> dict[str, Any]:
    positive_by_user = {str(user_id): set(items) for user_id, items in dict(metadata.get("positive_pairs_by_user", {})).items()}
    eligible_users = sorted(positive_by_user)
    if not eligible_users:
        return {"eligible_user_count": 0, f"hit_at_{k}": 0.0, f"ndcg_at_{k}": 0.0, f"mrr_at_{k}": 0.0, f"recall_at_{k}": 0.0}
    user_hit: list[float] = []
    user_ndcg: list[float] = []
    user_mrr: list[float] = []
    user_recall: list[float] = []
    for user_id in eligible_users:
        positives = positive_by_user[user_id]
        ranked_items = [str(item.get("parent_asin")) for item in ranking_results.get(user_id, [])[:k] if isinstance(item, dict) and item.get("parent_asin")]
        hit_positions = [rank for rank, item_id in enumerate(ranked_items, start=1) if item_id in positives]
        user_hit.append(1.0 if hit_positions else 0.0)
        dcg = sum(1.0 / log2(position + 1) for position in hit_positions)
        ideal_dcg = sum(1.0 / log2(index + 2) for index in range(min(len(positives), k)))
        user_ndcg.append(dcg / ideal_dcg if ideal_dcg else 0.0)
        user_mrr.append(1.0 / hit_positions[0] if hit_positions else 0.0)
        user_recall.append(len(hit_positions) / len(positives) if positives else 0.0)
    return {
        "eligible_user_count": len(eligible_users),
        f"hit_at_{k}": round(mean(user_hit), 6),
        f"ndcg_at_{k}": round(mean(user_ndcg), 6),
        f"mrr_at_{k}": round(mean(user_mrr), 6),
        f"recall_at_{k}": round(mean(user_recall), 6),
    }


def _shadow_metrics(
    candidates_by_user: dict[str, list[MergedCandidate]],
    ranking_results: dict[str, list[dict[str, Any]]],
    top_k: int,
) -> dict[str, Any]:
    pool_sizes = [len(candidates) for candidates in candidates_by_user.values()]
    ranked_items = [item for items in ranking_results.values() for item in items]
    candidate_items = [candidate for candidates in candidates_by_user.values() for candidate in candidates]
    topk_source_counts = _topk_source_contribution(ranked_items)
    user_count = len(candidates_by_user)
    label_metrics_available = any(_candidate_has_label_metric(candidate) for candidate in candidate_items)
    fallback_exposure_topk_ratio = _fallback_exposure_topk_ratio(ranked_items)
    metrics = {
        "user_count": user_count,
        "top_k": top_k,
        "input_pool_size_distribution": _distribution(pool_sizes),
        "underfilled_user_count": sum(1 for size in pool_sizes if size < top_k),
        "stage_trace_coverage": _stage_trace_coverage(ranked_items),
        "topk_source_contribution": dict(sorted(topk_source_counts.items())),
        "fallback_exposure_topk_ratio": fallback_exposure_topk_ratio,
        "metadata_missing_rate": _candidate_metadata_missing_rate(candidate_items),
        "category_missing_rate": _candidate_category_missing_rate(candidate_items),
        "top_category_ratio": _top_category_ratio(candidate_items),
        "topk_source_mix": _topk_source_mix(topk_source_counts, len(ranked_items)),
        "repaired_user_topk_stats": _repaired_user_topk_stats(ranking_results),
        "label_metrics_available": label_metrics_available,
        "label_adjacent_metrics": _label_adjacent_metrics(ranked_items) if label_metrics_available else {},
        "interpretation_label": "comparable",
    }
    if fallback_exposure_topk_ratio is None or _quality_guard_triggered(metrics):
        metrics["interpretation_label"] = "mechanism_only"
    return metrics


def _attach_shadow_candidate_metadata(item: dict[str, Any], candidate_by_item: dict[str, MergedCandidate]) -> dict[str, Any]:
    candidate = candidate_by_item.get(str(item.get("parent_asin")))
    if candidate is not None:
        item["metadata"] = dict(candidate.metadata)
    return item


def _uses_shadow_local_rerank(config: dict[str, Any]) -> bool:
    return bool(config.get("fallback_heavy_topk_cap", {}).get("enabled") or config.get("source_diversity_constrained_rerank", {}).get("enabled"))


def _apply_shadow_local_diagnostic_rerank(items: list[dict[str, Any]], config: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
    if not _uses_shadow_local_rerank(config):
        return items[:top_k]
    reranked = list(items)
    cap_policy = config.get("fallback_heavy_topk_cap", {})
    if cap_policy.get("enabled"):
        reranked = _cap_fallback_heavy_items(reranked, top_k, float(cap_policy.get("max_topk_ratio", 0.5)))
    diversity_policy = config.get("source_diversity_constrained_rerank", {})
    if diversity_policy.get("enabled"):
        reranked = _constrain_topk_source_diversity(reranked, top_k, float(diversity_policy.get("max_per_source_topk_ratio", 0.5)))
    return _renumber_final_ranks(reranked[:top_k])


def _cap_fallback_heavy_items(items: list[dict[str, Any]], top_k: int, max_ratio: float) -> list[dict[str, Any]]:
    cap = max(1, int(top_k * max_ratio))
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    fallback_count = 0
    for item in items:
        if _is_fallback_heavy_item(item):
            if fallback_count < cap:
                selected.append(item)
                fallback_count += 1
            else:
                deferred.append(item)
        else:
            selected.append(item)
    return [*selected, *deferred]


def _constrain_topk_source_diversity(items: list[dict[str, Any]], top_k: int, max_ratio: float) -> list[dict[str, Any]]:
    cap = max(1, int(top_k * max_ratio))
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    for item in items:
        dominant_source = _dominant_source(item)
        if source_counts[dominant_source] < cap:
            selected.append(item)
            source_counts[dominant_source] += 1
        else:
            deferred.append(item)
    return [*selected, *deferred]


def _renumber_final_ranks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for rank, item in enumerate(items, start=1):
        previous_rank = item.get("final_rank", rank)
        item["final_rank"] = rank
        item["rank_movement"] = dict(item.get("rank_movement", {}))
        item["rank_movement"]["diagnostic_shadow_local"] = int(previous_rank) - rank if isinstance(previous_rank, int) else 0
    return items


def _dominant_source(item: dict[str, Any]) -> str:
    sources = [str(source) for source in item.get("sources", [])]
    if any(source in {"itemcf_weak", "itemcf_strong"} for source in sources):
        return "itemcf"
    return sources[0] if sources else "unknown"


def _is_fallback_heavy_item(item: dict[str, Any]) -> bool:
    sources = {str(source) for source in item.get("sources", [])}
    if "co_visit_fallback_repair" in sources:
        return True
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return _metadata_has_fallback_marker(metadata)


def _metadata_has_fallback_marker(metadata: dict[str, Any]) -> bool:
    marker_keys = {"fallback_used", "fallback", "repair", "repaired", "repair_marker", "fallback_lineage", "repair_lineage"}
    for key, value in metadata.items():
        lowered = str(key).lower()
        if lowered in marker_keys and value:
            return True
        if any(marker in lowered for marker in ("fallback", "repair", "repaired")) and value:
            return True
    return False


def _candidate_metadata_missing_rate(candidates: list[MergedCandidate]) -> float:
    if not candidates:
        return 0.0
    missing = sum(1 for candidate in candidates if not candidate.metadata)
    return round(missing / len(candidates), 6)


def _candidate_category_missing_rate(candidates: list[MergedCandidate]) -> float:
    if not candidates:
        return 0.0
    missing = sum(1 for candidate in candidates if not candidate.category)
    return round(missing / len(candidates), 6)


def _top_category_ratio(candidates: list[MergedCandidate]) -> float:
    if not candidates:
        return 0.0
    counts = Counter(candidate.category for candidate in candidates if candidate.category)
    return round(max(counts.values(), default=0) / len(candidates), 6)


def _fallback_exposure_topk_ratio(items: list[dict[str, Any]]) -> float | None:
    if not items:
        return 0.0
    if not any(_item_has_lineage(item) for item in items):
        return None
    return round(sum(1 for item in items if _is_fallback_heavy_item(item)) / len(items), 6)


def _item_has_lineage(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata")
    return isinstance(metadata, dict) and bool(metadata.get(POOL500_LINEAGE_KEY) or metadata.get("pool500_source_metadata"))


def _topk_source_mix(source_counts: Counter[str], topk_count: int) -> dict[str, float]:
    if not topk_count:
        return {}
    return {source: round(count / topk_count, 6) for source, count in sorted(source_counts.items())}


def _repaired_user_topk_stats(ranking_results: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    repaired_counts = [sum(1 for item in items if _is_fallback_heavy_item(item)) for items in ranking_results.values()]
    return {
        "user_count": len(repaired_counts),
        "users_with_repaired_topk": sum(1 for count in repaired_counts if count > 0),
        "repaired_topk_count_distribution": _distribution(repaired_counts),
    }


def _candidate_has_label_metric(candidate: MergedCandidate) -> bool:
    return any(key in candidate.metadata for key in ("label", "labels", "holdout_hit", "is_hit", "clicked", "purchased", "rating"))


def _label_adjacent_metrics(items: list[dict[str, Any]]) -> dict[str, float | int]:
    if not items:
        return {"topk_labeled_count": 0, "topk_positive_label_rate": 0.0}
    labeled = [item for item in items if _item_label_value(item) is not None]
    positives = sum(1 for item in labeled if bool(_item_label_value(item)))
    return {
        "topk_labeled_count": len(labeled),
        "topk_positive_label_rate": round(positives / len(labeled), 6) if labeled else 0.0,
    }


def _item_label_value(item: dict[str, Any]) -> Any:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    for key in ("label", "holdout_hit", "is_hit", "clicked", "purchased"):
        if key in metadata:
            return metadata[key]
    labels = metadata.get("labels")
    if isinstance(labels, dict):
        return any(bool(value) for value in labels.values())
    if "rating" in metadata:
        return float(metadata["rating"] or 0.0) > 0.0
    return None


def _quality_guard_triggered(metrics: dict[str, Any]) -> bool:
    for field, threshold in QUALITY_GUARD_THRESHOLDS.items():
        value = metrics.get(field)
        if value is not None and float(value or 0.0) > threshold:
            return True
    return False


def _config_delta_vs_b0(config: dict[str, Any]) -> dict[str, Any]:
    baseline = {
        "top_k": FIXED_COMPARISON_TOP_K,
        "rank_weights": BASELINE_DIAGNOSTIC_UNIFORM_RANK_WEIGHTS,
        "normalized_additive_ranking": {"enabled": False},
    }
    return {key: value for key, value in config.items() if baseline.get(key) != value}


def _diagnostic_frozen_pool_result(
    evidence: dict[str, Any],
    validation: dict[str, Any],
    ranking_results: dict[str, list[dict[str, Any]]],
    adapter_result: dict[str, Any] | None,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": DIAGNOSTIC_FROZEN_POOL_SCHEMA_VERSION,
        "status": STOP,
        "decision": STOP,
        "evidence": evidence,
        "validation": validation,
        "ranking_results": ranking_results,
        "adapter_result": _adapter_summary(adapter_result),
        "blockers": blockers,
        "diagnostics": adapter_result.get("diagnostics", []) if isinstance(adapter_result, dict) else [],
    }


def _diagnostic_manifest_blockers(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for field, expected in DIAGNOSTIC_ONLY_FLAGS.items():
        if field == "diagnostic_only":
            continue
        if manifest.get(field) is not expected:
            blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_PROMOTION_FORBIDDEN", {"field": field, "value": manifest.get(field), "required": expected}))
    if manifest.get("final_pool500_ready_claimed") is True or manifest.get("full_pool500_ready_declared") is True:
        blockers.append(_blocker("POOL500_DIAGNOSTIC_RANKING_FULL_READY_FORBIDDEN", {"final_pool500_ready_claimed": manifest.get("final_pool500_ready_claimed"), "full_pool500_ready_declared": manifest.get("full_pool500_ready_declared")}))
    return blockers


def _iter_diagnostic_frozen_pool_rows(path: Path):
    for row in iter_jsonl(path):
        normalized = dict(row)
        source = str(normalized.get("source", ""))
        if "score" not in normalized:
            source_scores = normalized.get("source_scores")
            if not isinstance(source_scores, dict):
                source_scores = normalized.get("metadata", {}).get("source_scores") if isinstance(normalized.get("metadata"), dict) else None
            if isinstance(source_scores, dict) and source in source_scores:
                normalized["score"] = source_scores[source]
        if "metadata" not in normalized or not isinstance(normalized.get("metadata"), dict):
            normalized["metadata"] = {}
        if "category" in normalized and "category" not in normalized["metadata"]:
            normalized["metadata"]["category"] = normalized.get("category")
        yield normalized


def _candidate_file_stats(path: Path) -> dict[str, Any]:
    per_user_items: dict[str, set[str]] = {}
    source_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    user_item_sources: dict[tuple[str, str], set[str]] = {}
    row_count = 0
    metadata_missing_count = 0
    category_missing_count = 0
    forbidden_sources: set[str] = set()
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if not user_id or not item_id:
            continue
        row_count += 1
        per_user_items.setdefault(user_id, set()).add(item_id)
        raw_source = row.get("source", "")
        source = canonicalize_source_label(raw_source)
        normalized_source = str(raw_source).strip().lower().replace("-", "_")
        if normalized_source in FORBIDDEN_SOURCE_LABELS or source in FORBIDDEN_SOURCE_LABELS:
            forbidden_sources.add(normalized_source or source)
        source_counts[source] += 1
        user_item_sources.setdefault((user_id, item_id), set()).add(source)
        metadata = row.get("metadata")
        if not isinstance(metadata, dict) or not metadata:
            metadata_missing_count += 1
            metadata = {}
        category = str(row.get("category") or metadata.get("category") or "")
        if category:
            category_counts[category] += 1
        else:
            category_missing_count += 1
    candidate_counts = {user_id: len(items) for user_id, items in sorted(per_user_items.items())}
    values = sorted(candidate_counts.values())
    user_count = len(candidate_counts)
    underfilled_user_count = sum(1 for count in values if count < 500)
    unique_user_item_count = len(user_item_sources)
    multi_source_item_count = sum(1 for sources in user_item_sources.values() if len(sources) > 1)
    top_category_count = max(category_counts.values(), default=0)
    return {
        "candidate_row_count": row_count,
        "user_count": user_count,
        "candidate_count_distribution": _distribution(values),
        "per_user_candidate_count": candidate_counts,
        "underfilled_user_count": underfilled_user_count,
        "underfilled_user_ratio": round(underfilled_user_count / user_count, 6) if user_count else 0.0,
        "source_coverage": dict(sorted(source_counts.items())),
        "category_coverage": dict(sorted(category_counts.items())),
        "multi_source_item_ratio": round(multi_source_item_count / unique_user_item_count, 6) if unique_user_item_count else 0.0,
        "metadata_missing_rate": round(metadata_missing_count / row_count, 6) if row_count else 0.0,
        "category_missing_rate": round(category_missing_count / row_count, 6) if row_count else 0.0,
        "top_category_ratio": round(top_category_count / row_count, 6) if row_count else 0.0,
        "observed_canonical_sources": sorted(source_counts),
        "forbidden_source_labels_observed": sorted(forbidden_sources),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_uses_inferred_artifact(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    return any(marker in lowered for marker in ("*", "?", "[", "/latest", "latest/"))


def _distribution(values: list[int]) -> dict[str, float | int | None]:
    if not values:
        return {"min": None, "p50": None, "avg": None, "max": None}
    ordered = sorted(values)
    return {"min": ordered[0], "p50": ordered[len(ordered) // 2], "avg": round(mean(ordered), 6), "max": ordered[-1]}


def _stage_trace_coverage(items: list[dict[str, Any]]) -> dict[str, float]:
    stages = ("coarse", "fine", "rerank")
    if not items:
        return {stage: 0.0 for stage in stages}
    coverage: dict[str, float] = {}
    for stage in stages:
        covered = sum(1 for item in items if any(trace.get("stage") == stage for trace in item.get("score_trace", [])))
        coverage[stage] = round(covered / len(items), 6)
    return coverage


def _topk_source_contribution(items: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for item in items:
        for source in item.get("sources", []):
            counts[str(source)] += 1
    return counts


def _ranking_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "parent_asin",
        "score",
        "base_score",
        "coarse_score",
        "agent_boost",
        "fine_score",
        "rerank_score",
        "final_score",
        "score_trace",
        "sources",
        "category",
        "feature_score",
        "normalized_additive_score",
        "item_features",
        "score_components",
        "ltr_score",
        "rerank_events",
        "coarse_rank",
        "fine_rank",
        "final_rank",
        "rank_movement",
    }
    return {key: item[key] for key in keys if key in item}


def _adapter_summary(adapter_result: dict[str, Any] | None) -> dict[str, Any] | None:
    if adapter_result is None:
        return None
    return {
        "schema_version": adapter_result.get("schema_version"),
        "status": adapter_result.get("status"),
        "decision": adapter_result.get("decision"),
        "candidate_pool_limit": adapter_result.get("candidate_pool_limit"),
        "blockers": adapter_result.get("blockers", []),
        "diagnostics": adapter_result.get("diagnostics", []),
    }


def _validate_diagnostic_required_aggregations(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    required_fields = (
        "source_coverage",
        "category_coverage",
        "multi_source_item_ratio",
        "metadata_missing_rate",
        "category_missing_rate",
        "top_category_ratio",
        "interpretation_label",
        "underfilled_user_count",
    )
    return [
        _blocker("POOL500_DIAGNOSTIC_AGGREGATION_REQUIRED", {"field": field, "value": evidence.get(field)})
        for field in required_fields
        if evidence.get(field) is None
    ]


def _validate_forbidden_source_labels(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    forbidden = set(evidence.get("forbidden_source_labels_observed") or [])
    source_coverage = evidence.get("source_coverage")
    if isinstance(source_coverage, dict):
        forbidden.update(source for source in source_coverage if source in FORBIDDEN_SOURCE_LABELS)
    return [_blocker("POOL500_DIAGNOSTIC_FORBIDDEN_SOURCE_LABEL", {"sources": sorted(forbidden)})] if forbidden else []


def _diagnostic_interpretation_label(evidence: dict[str, Any]) -> str:
    if evidence.get("blockers"):
        return "blocked"
    user_count = int(evidence.get("user_count") or 0)
    underfilled_user_count = int(evidence.get("underfilled_user_count") or 0)
    source_coverage = evidence.get("source_coverage") or {}
    observed_sources = set(source_coverage) if isinstance(source_coverage, dict) else set(evidence.get("observed_canonical_sources") or [])
    if underfilled_user_count > int(user_count * 0.02):
        return "mechanism_only"
    if observed_sources != CANONICAL_SOURCES:
        return "mechanism_only"
    if "fallback_exposure_topk_ratio" in evidence and evidence.get("fallback_exposure_topk_ratio") is None:
        return "mechanism_only"
    if _quality_guard_triggered(evidence):
        return "mechanism_only"
    if float(evidence.get("multi_source_item_ratio") or 0.0) == 0.0:
        return "mechanism_only"
    return "comparable"


def _validate_forbidden_semantics(payload: Any) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for key, value in _walk(payload):
        leaf = key.rsplit(".", 1)[-1]
        if leaf in FORBIDDEN_FIELDS:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_FORBIDDEN_FIELD", {"field": key, "value": value}))
        if leaf == "run_kind" and str(value) in FORBIDDEN_RUN_KINDS:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_FORBIDDEN_RUN_KIND", {"field": key, "value": value}))
        if isinstance(value, str) and value in FORBIDDEN_READY_VALUES:
            blockers.append(_blocker("POOL500_SHADOW_RANKING_FORBIDDEN_READY_SEMANTIC", {"field": key, "value": value}))
    return blockers


def _validate_fixed_report_summary_ready_semantics(payload: Any) -> list[dict[str, Any]]:
    return [
        _blocker("POOL500_SHADOW_RANKING_FORBIDDEN_READY_SEMANTIC", {"field": key, "value": value})
        for key, value in _walk(payload)
        if value == FULL_POOL500_READY
    ]


def _walk(payload: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(payload, dict):
        items: list[tuple[str, Any]] = []
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_walk(value, path))
        return items
    if isinstance(payload, list):
        items = []
        for index, value in enumerate(payload):
            items.extend(_walk(value, f"{prefix}[{index}]"))
        return items
    return [(prefix, payload)]


def _blocker(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "evidence": evidence}
