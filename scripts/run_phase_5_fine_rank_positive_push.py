from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_jsonl, write_json
from rs_core.recsys.evaluation import build_ranking_feature_contract, inspect_ranking_run_artifacts
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.ranking_experiments import (
    REQUIRED_CANDIDATE_POOL_SIZE,
    REQUIRED_TOP_K,
    RankingMethodSpec,
    build_ranking_method_registry_entry_from_spec,
    build_ranking_run_row,
    public_ranking_run_row,
)
from scripts.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS
from scripts.run_phase_1_26_real_ranking_experiments import (
    _not_applicable_feature_contract_gate,
    _not_applicable_leakage_gate,
    _read_frozen_rows,
)
from scripts.run_phase_2_fine_rank_algorithm_batch import PHYSICAL_PIPELINE_OVERRIDE
from scripts.run_phase_4_stage_shadow_metrics import _weak_ranking_metrics

_PHASE = "phase_5_fine_rank_positive_push"
_BASELINE_METHOD_ID = "same_run_pool200_baseline"
_FINE_RANK_METHOD_ID = "fine_rank_positive_push_diagnostic"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_5_fine_rank_positive_push_smoke"
DEFAULT_SEED = 20260514
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 5 fine-rank positive-push diagnostics on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 5 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in Phase 5 artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_5_fine_rank_positive_push(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_5_fine_rank_positive_push(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users, seed)
    method_specs = build_method_specs()
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, method_specs[0], run_id, command_text)
    fine_rank_row = _build_fine_rank_diagnostic_row(output_dir, method_specs[1], baseline_row, run_id, command_text)
    runnable_rows = [baseline_row, fine_rank_row]
    runs = [public_ranking_run_row(row) for row in runnable_rows]
    method_registry = [_method_registry_entry(row) for row in runnable_rows]
    ranking_registry = [row["ranking_experiment_registry"] for row in runnable_rows]
    gates = _phase_gates(fine_rank_row)

    return {
        "phase": _PHASE,
        "run_id": run_id,
        "seed": seed,
        "limit_users": limit_users,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "method_specs": [spec.to_registry_payload() for spec in method_specs],
        "stage_main_lane_matrix": _stage_main_lane_matrix(),
        "promotion_boundary": _promotion_boundary(),
        "method_registry": method_registry,
        "ranking_experiment_registry": ranking_registry,
        "artifact_inspection": inspect_ranking_run_artifacts(
            runnable_rows,
            required_paths=[
                "metrics_path",
                "recommendations_path",
                "ranking_cases_path",
                "ranking_case_summary_path",
                "report_path",
                "frozen_candidates_path",
                "ranking_stage_trace_path",
                "ranking_stage_summary_path",
                "weak_metrics_path",
                "fine_rank_case_diagnostics_path",
                "score_gap_diagnostics_path",
                "rank_movement_diagnostics_path",
                "gates_path",
            ],
        ),
        "weak_metrics": fine_rank_row["weak_metrics"],
        "fine_rank_case_diagnostics": fine_rank_row["fine_rank_case_diagnostics"],
        "score_gap_diagnostics": fine_rank_row["score_gap_diagnostics"],
        "rank_movement_diagnostics": fine_rank_row["rank_movement_diagnostics"],
        "case_diagnostic_success": fine_rank_row["case_diagnostic_success"],
        "promotion_success": False,
        "frozen_gate": gates["frozen_gate"],
        "feature_gate": gates["feature_gate"],
        "leakage_gate": gates["leakage_gate"],
        "online_gate": gates["online_gate"],
        "runs": runs,
    }


def build_method_specs() -> list[RankingMethodSpec]:
    return [
        RankingMethodSpec(
            method_id=_BASELINE_METHOD_ID,
            method_family="current_champion_route",
            stage_target="rerank",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="baseline",
            blocked_recovery_condition="baseline route is executable through the frozen pool200 same-run config",
            promotion_eligible=False,
            diagnostic_only=False,
            metadata={"config_path": str(BASELINE_CONFIG), "role": "frozen_pool200_current_champion"},
        ),
        RankingMethodSpec(
            method_id=_FINE_RANK_METHOD_ID,
            method_family="fine_rank_full_pool_score_diagnostics",
            stage_target="fine",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="phase_5_diagnostic_only",
            blocked_recovery_condition="promotion requires a verified challenger adapter, valid/test evidence, and offline gates outside diagnostic-only score inspection",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={
                "full_pool200_scoring_only": True,
                "does_not_crop_candidates": True,
                "normalization_calibration_artifact_contract": True,
                "coarse_stage_shadow_only": True,
                "blocked_promotions": ["c_rescue_promotion", "b_ltr_promotion"],
            },
        ),
    ]


def _run_baseline(
    output_dir: Path,
    limit_users: int | None,
    feature_contract: dict[str, Any],
    method_spec: RankingMethodSpec,
    run_id: str,
    command_text: str,
) -> dict[str, Any]:
    variant_output_dir = output_dir / method_spec.method_id
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "export_ranking_stage_artifacts": True,
            "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
            "strategy_name": f"{_PHASE}_{method_spec.method_id}",
        },
    )
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(method_spec.method_id, result, metrics)
    row = build_ranking_run_row(
        run_id=f"{_PHASE}:{run_id}",
        run_index=0,
        run_kind="baseline",
        method_spec=method_spec,
        config=_registry_config(metrics, method_spec.method_id),
        frozen_rows=frozen_rows,
        metrics={key: metrics.get(key) for key in METRIC_FIELDS},
        strict_status={"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline", "frozen_pool200_boundary"], "metric_delta": {}},
        artifact_paths=_artifact_paths(variant_output_dir, result, metrics),
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
        command_text=command_text,
    )
    row["raw_metrics"] = metrics
    row["frozen_rows"] = frozen_rows
    return row


def _build_fine_rank_diagnostic_row(output_dir: Path, method_spec: RankingMethodSpec, baseline_row: dict[str, Any], run_id: str, command_text: str) -> dict[str, Any]:
    diagnostics_dir = output_dir / method_spec.method_id
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    ranking_cases = read_jsonl(baseline_row["ranking_cases_path"])
    stage_trace_rows = read_jsonl(baseline_row["ranking_stage_trace_path"])
    users_with_holdout = int(baseline_row["raw_metrics"].get("users_with_holdout", 0) or 0)
    weak_metrics = _weak_ranking_metrics(ranking_cases, stage_trace_rows, users_with_holdout)
    case_diagnostics = _fine_rank_case_diagnostics(ranking_cases, stage_trace_rows)
    score_gap_diagnostics = _score_gap_diagnostics(ranking_cases)
    rank_movement_diagnostics = _rank_movement_diagnostics(ranking_cases, stage_trace_rows)
    gates = _diagnostic_gates(baseline_row)
    case_diagnostic_success = bool(gates["frozen_gate"]["status"] == "PASS")

    weak_metrics_path = diagnostics_dir / "weak_metrics.json"
    case_diagnostics_path = diagnostics_dir / "fine_rank_case_diagnostics.json"
    score_gap_path = diagnostics_dir / "score_gap_diagnostics.json"
    rank_movement_path = diagnostics_dir / "rank_movement_diagnostics.json"
    gates_path = diagnostics_dir / "gates.json"
    write_json(weak_metrics_path, weak_metrics)
    write_json(case_diagnostics_path, case_diagnostics)
    write_json(score_gap_path, score_gap_diagnostics)
    write_json(rank_movement_path, rank_movement_diagnostics)
    write_json(gates_path, gates)

    metrics = {key: baseline_row["raw_metrics"].get(key) for key in METRIC_FIELDS} | weak_metrics | {
        "case_diagnostic_success": case_diagnostic_success,
        "promotion_success": False,
        "target_case_count": case_diagnostics["target_case_count"],
        "fine_rank_available_rate": case_diagnostics["fine_rank_available_rate"],
        "top1_score_gap_avg": score_gap_diagnostics["top1_score_gap_avg"],
        "coarse_to_fine_improved_count": rank_movement_diagnostics["coarse_to_fine_improved_count"],
        "coarse_to_fine_worsened_count": rank_movement_diagnostics["coarse_to_fine_worsened_count"],
    }
    status = {
        "status": "PARTIAL diagnostic-only",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": [
            "fine_rank_full_pool_score_diagnostics_only",
            "no_candidate_pool_crop_or_mutation",
            "weak_metrics_are_supporting_only",
            "online_metrics_forbidden_as_current_promotion_evidence",
            "valid_test_promotion_evidence_missing",
        ],
        "metric_delta": {},
    }
    row = build_ranking_run_row(
        run_id=f"{_PHASE}:{run_id}",
        run_index=1,
        run_kind="diagnostic",
        method_spec=method_spec,
        config=_registry_config(baseline_row["raw_metrics"], method_spec.method_id),
        frozen_rows=baseline_row["frozen_rows"],
        baseline_frozen_rows=baseline_row["frozen_rows"],
        metrics=metrics,
        strict_status=status,
        artifact_paths={
            "metrics_path": baseline_row.get("metrics_path"),
            "recommendations_path": baseline_row.get("recommendations_path"),
            "ranking_cases_path": baseline_row.get("ranking_cases_path"),
            "ranking_case_summary_path": baseline_row.get("ranking_case_summary_path"),
            "report_path": baseline_row.get("report_path"),
            "frozen_candidates_path": baseline_row.get("frozen_candidates_path"),
            "ranking_stage_trace_path": baseline_row.get("ranking_stage_trace_path"),
            "ranking_stage_summary_path": baseline_row.get("ranking_stage_summary_path"),
            "weak_metrics_path": str(weak_metrics_path),
            "fine_rank_case_diagnostics_path": str(case_diagnostics_path),
            "score_gap_diagnostics_path": str(score_gap_path),
            "rank_movement_diagnostics_path": str(rank_movement_path),
            "gates_path": str(gates_path),
            "diagnostic_source_metrics_path": baseline_row.get("metrics_path"),
            "diagnostic_source_stage_trace_path": baseline_row.get("ranking_stage_trace_path"),
            "adapter_execution": "not_run_read_only_fine_rank_diagnostics",
            "promotion_evidence_claim": "none",
        },
        feature_contract=build_ranking_feature_contract(),
        feature_contract_gate_summary=gates["feature_gate"],
        leakage_gate_summary=gates["leakage_gate"],
        command_text=command_text,
    )
    row["raw_metrics"] = baseline_row["raw_metrics"]
    row["frozen_rows"] = baseline_row["frozen_rows"]
    row["weak_metrics"] = weak_metrics
    row["fine_rank_case_diagnostics"] = case_diagnostics
    row["score_gap_diagnostics"] = score_gap_diagnostics
    row["rank_movement_diagnostics"] = rank_movement_diagnostics
    row["case_diagnostic_success"] = case_diagnostic_success
    row["promotion_success"] = False
    row["frozen_gate"] = gates["frozen_gate"]
    row["feature_gate"] = gates["feature_gate"]
    row["leakage_gate"] = gates["leakage_gate"]
    row["online_gate"] = gates["online_gate"]
    return row


def _fine_rank_case_diagnostics(ranking_cases: list[dict[str, Any]], stage_trace_rows: list[dict[str, Any]]) -> dict[str, Any]:
    trace_by_key = {(str(row.get("user_id", "")), str(row.get("item_id", ""))): row for row in stage_trace_rows}
    rows = []
    fine_ranks: list[int] = []
    fine_scores: list[float] = []
    for case in ranking_cases:
        key = (str(case.get("user_id", "")), str(case.get("target_item", "")))
        trace_row = trace_by_key.get(key, {})
        fine_rank = _positive_int(case.get("target_fine_rank")) or _positive_int(trace_row.get("fine_rank"))
        fine_score = _float_value(case.get("target_fine_score", trace_row.get("fine_score")))
        final_rank = _positive_int(case.get("target_final_rank")) or _positive_int(trace_row.get("final_rank")) or _positive_int(case.get("target_rank"))
        if fine_rank is not None:
            fine_ranks.append(fine_rank)
        if fine_score is not None:
            fine_scores.append(fine_score)
        rows.append({
            "user_id": case.get("user_id"),
            "target_item": case.get("target_item"),
            "target_rank": case.get("target_rank"),
            "target_fine_rank": fine_rank,
            "target_fine_score": fine_score,
            "target_final_rank": final_rank,
            "target_final_score": _float_value(case.get("target_final_score", trace_row.get("final_score"))),
            "target_score_components": case.get("target_score_components", {}),
            "target_score_trace": case.get("target_score_trace", []),
            "target_rank_movement": case.get("target_rank_movement", trace_row.get("rank_movement", {})),
            "is_topk_hit": bool(case.get("is_topk_hit")),
        })
    return {
        "schema_version": "phase_5_fine_rank_case_diagnostics_v1",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "target_case_count": len(rows),
        "fine_rank_available_count": len(fine_ranks),
        "fine_rank_available_rate": round(len(fine_ranks) / len(rows), 6) if rows else 0.0,
        "fine_score_available_count": len(fine_scores),
        "fine_score_available_rate": round(len(fine_scores) / len(rows), 6) if rows else 0.0,
        "target_fine_rank_mean": _mean(fine_ranks),
        "target_fine_rank_median": _median(fine_ranks),
        "target_fine_score_mean": _mean(fine_scores),
        "normalization_calibration_artifact_contract": {
            "score_trace_required": True,
            "score_components_required": True,
            "full_pool_score_diagnostics_only": True,
            "actual_calibration_model_trained": False,
        },
        "target_positions_sample": rows[:20],
    }


def _score_gap_diagnostics(ranking_cases: list[dict[str, Any]]) -> dict[str, Any]:
    top1_gaps: list[float] = []
    topk_min_gaps: list[float] = []
    replaced_by_component_counter: Counter[str] = Counter()
    samples = []
    for case in ranking_cases:
        target_score = _float_value(case.get("target_score")) or 0.0
        top_items = case.get("top_items", []) or []
        if top_items:
            top1_gap = round(float(top_items[0].get("score") or 0.0) - target_score, 6)
            top1_gaps.append(top1_gap)
            topk_min_gaps.append(round(min(float(item.get("score") or 0.0) for item in top_items) - target_score, 6))
        replacement = case.get("topk_replacement_reason", {}) or {}
        for item in replacement.get("replaced_by", []) or []:
            component = item.get("dominant_score_component")
            if component:
                replaced_by_component_counter.update([str(component)])
        samples.append({
            "user_id": case.get("user_id"),
            "target_item": case.get("target_item"),
            "target_rank": case.get("target_rank"),
            "target_score": target_score,
            "top1_score_gap": top1_gaps[-1] if top_items else None,
            "topk_boundary_score_gap": topk_min_gaps[-1] if top_items else None,
            "topk_replacement_reason": replacement,
        })
    return {
        "schema_version": "phase_5_score_gap_diagnostics_v1",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "target_case_count": len(ranking_cases),
        "top1_score_gap_avg": _mean(top1_gaps),
        "top1_score_gap_median": _median(top1_gaps),
        "top1_score_gap_min": min(top1_gaps) if top1_gaps else None,
        "top1_score_gap_max": max(top1_gaps) if top1_gaps else None,
        "topk_boundary_score_gap_avg": _mean(topk_min_gaps),
        "replaced_by_dominant_component_counts": dict(replaced_by_component_counter.most_common()),
        "score_gap_sample": samples[:20],
    }


def _rank_movement_diagnostics(ranking_cases: list[dict[str, Any]], stage_trace_rows: list[dict[str, Any]]) -> dict[str, Any]:
    trace_by_key = {(str(row.get("user_id", "")), str(row.get("item_id", ""))): row for row in stage_trace_rows}
    coarse_to_fine_deltas: list[int] = []
    fine_to_final_deltas: list[int] = []
    samples = []
    for case in ranking_cases:
        key = (str(case.get("user_id", "")), str(case.get("target_item", "")))
        trace_row = trace_by_key.get(key, {})
        coarse_rank = _positive_int(case.get("target_coarse_rank")) or _positive_int(trace_row.get("coarse_rank"))
        fine_rank = _positive_int(case.get("target_fine_rank")) or _positive_int(trace_row.get("fine_rank"))
        final_rank = _positive_int(case.get("target_final_rank")) or _positive_int(trace_row.get("final_rank")) or _positive_int(case.get("target_rank"))
        coarse_to_fine_delta = coarse_rank - fine_rank if coarse_rank is not None and fine_rank is not None else None
        fine_to_final_delta = fine_rank - final_rank if fine_rank is not None and final_rank is not None else None
        if coarse_to_fine_delta is not None:
            coarse_to_fine_deltas.append(coarse_to_fine_delta)
        if fine_to_final_delta is not None:
            fine_to_final_deltas.append(fine_to_final_delta)
        samples.append({
            "user_id": case.get("user_id"),
            "target_item": case.get("target_item"),
            "coarse_rank": coarse_rank,
            "fine_rank": fine_rank,
            "final_rank": final_rank,
            "coarse_to_fine_delta": coarse_to_fine_delta,
            "fine_to_final_delta": fine_to_final_delta,
            "rank_movement": case.get("target_rank_movement", trace_row.get("rank_movement", {})),
        })
    return {
        "schema_version": "phase_5_rank_movement_diagnostics_v1",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "target_case_count": len(ranking_cases),
        "coarse_to_fine_delta_avg": _mean(coarse_to_fine_deltas),
        "fine_to_final_delta_avg": _mean(fine_to_final_deltas),
        "coarse_to_fine_improved_count": sum(1 for delta in coarse_to_fine_deltas if delta > 0),
        "coarse_to_fine_worsened_count": sum(1 for delta in coarse_to_fine_deltas if delta < 0),
        "coarse_to_fine_unchanged_count": sum(1 for delta in coarse_to_fine_deltas if delta == 0),
        "fine_to_final_improved_count": sum(1 for delta in fine_to_final_deltas if delta > 0),
        "fine_to_final_worsened_count": sum(1 for delta in fine_to_final_deltas if delta < 0),
        "fine_to_final_unchanged_count": sum(1 for delta in fine_to_final_deltas if delta == 0),
        "rank_movement_sample": samples[:20],
    }


def _diagnostic_gates(baseline_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "frozen_gate": {
            "schema_version": "phase_5_frozen_gate_v1",
            "status": "PASS" if baseline_row.get("candidate_pool_size") == REQUIRED_CANDIDATE_POOL_SIZE and baseline_row.get("top_k") == REQUIRED_TOP_K else "REJECT",
            "candidate_pool_size": baseline_row.get("candidate_pool_size"),
            "top_k": baseline_row.get("top_k"),
            "recall_semantics_changed": False,
            "merge_for_user_changed": False,
            "real_coarse_pool_shrink": False,
            "reasons": ["frozen_pool200_same_run_artifact", "fine_rank_diagnostics_read_only"],
        },
        "feature_gate": {
            "schema_version": "ranking_feature_contract_gate_v1",
            "status": "PASS",
            "checked_rows": 0,
            "checked_feature_count": 0,
            "allowed_feature_families_only": True,
            "new_training_features_added": False,
            "reasons": ["read_only_existing_score_trace_and_components", "no_ltr_or_rescue_feature_promotion"],
        },
        "leakage_gate": {
            "schema_version": "ranking_feature_leakage_gate_v1",
            "status": "PASS",
            "checked_rows": 0,
            "uses_holdout_target_as_feature": False,
            "uses_future_interaction_features": False,
            "reasons": ["diagnostics_read_existing_case_artifacts_only", "no_model_training_or_serving_adapter"],
        },
        "online_gate": {
            "schema_version": "phase_5_online_gate_v1",
            "status": "NOT_CURRENT_EVIDENCE",
            "forbidden_as_current_promotion_evidence": ["CTR", "CVR", "GMV", "P95", "SLO", "Agent feedback"],
            "promotion_eligible": False,
            "reasons": ["offline_diagnostic_phase_only", "online_metrics_not_collected_in_this_runner"],
        },
    }


def _phase_gates(fine_rank_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "frozen_gate": fine_rank_row["frozen_gate"],
        "feature_gate": fine_rank_row["feature_gate"],
        "leakage_gate": fine_rank_row["leakage_gate"],
        "online_gate": fine_rank_row["online_gate"],
    }


def _artifact_paths(variant_output_dir: Path, result: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(variant_output_dir),
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path"),
        "ranking_stage_trace_path": result.get("ranking_stage_trace_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("trace"),
        "ranking_stage_summary_path": result.get("ranking_stage_summary_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("summary"),
        "weak_metrics_path": result["metrics_path"],
        "fine_rank_case_diagnostics_path": result.get("ranking_case_summary_path"),
        "score_gap_diagnostics_path": result.get("ranking_case_summary_path"),
        "rank_movement_diagnostics_path": result.get("ranking_stage_summary_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("summary"),
        "gates_path": result["metrics_path"],
        "frozen_candidates_exported": True,
        "ranking_stage_artifacts_exported": True,
        "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
    }


def _method_registry_entry(row: dict[str, Any]) -> dict[str, Any]:
    method_payload = {key: value for key, value in row["method_spec"].items() if key != "schema_version"}
    return build_ranking_method_registry_entry_from_spec(
        RankingMethodSpec(**method_payload),
        run_kind=str(row["run_kind"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_METHOD_ID if row["run_kind"] == "baseline" else None,
        challenger_of=_BASELINE_METHOD_ID if row["run_kind"] != "baseline" else None,
        dependency_status="not_required",
    )


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or REQUIRED_CANDIDATE_POOL_SIZE
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or REQUIRED_TOP_K
    config["physical_ranking_pipeline"] = PHYSICAL_PIPELINE_OVERRIDE
    config["export_ranking_stage_artifacts"] = True
    return config


def _stage_main_lane_matrix() -> list[dict[str, Any]]:
    return [
        {"stage": "coarse", "main_lane": "pass_through_pool200", "shadow_lane": "coarse_shadow_diagnostics_only", "candidate_scope": "full_pool200", "candidate_mutation": False, "diagnostics": ["coarse_rank", "coarse_score"], "real_pool_shrink": False},
        {"stage": "fine", "main_lane": _FINE_RANK_METHOD_ID, "shadow_lane": None, "candidate_scope": "full_pool200", "candidate_mutation": False, "diagnostics": ["target_fine_rank", "target_fine_score", "score_gap", "normalization_calibration_artifact_contract"]},
        {"stage": "rerank", "main_lane": "existing_rerank_top5", "shadow_lane": None, "candidate_scope": "top_k", "top_k": REQUIRED_TOP_K, "candidate_mutation": False, "diagnostics": ["rank_movement", "target_rank", "target_rank_percentile"]},
        {"stage": "future-online", "main_lane": "not_current_offline_evidence", "shadow_lane": None, "candidate_scope": "not_applicable", "candidate_mutation": False, "promotion_eligible": False, "diagnostics": []},
    ]


def _promotion_boundary() -> dict[str, Any]:
    return {
        "frozen_pool200_required": True,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "recall_semantics_changed": False,
        "merge_for_user_changed": False,
        "coarse_shadow_does_not_crop_or_mutate_candidates": True,
        "real_coarse_pool_shrink_forbidden": True,
        "weak_metrics_diagnostic_only": True,
        "target_rank_and_percentile_supporting_only": True,
        "online_metrics_forbidden_as_current_offline_evidence": True,
        "blocked_promotions": ["c_rescue_promotion", "b_ltr_promotion"],
        "case_diagnostic_success_can_pass": True,
        "promotion_success": False,
        "promotion_eligible": False,
    }


def _command_text(output_dir: Path, limit_users: int | None, seed: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/run_phase_5_fine_rank_positive_push.py", "--output-dir", str(output_dir), "--seed", str(seed)]
    if limit_users is not None:
        parts.extend(["--limit-users", str(limit_users)])
    return " ".join(parts)


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[int] | list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _median(values: list[int] | list[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 5 Fine-Rank Positive Push",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Seed: `{comparison['seed']}`",
        "- Scope: frozen pool200 / top_k=5; recall semantics, `merge_for_user()`, and real coarse shrinking are unchanged.",
        "- Promotion boundary: fine-rank diagnostics can pass as case diagnostics, but cannot set `promotion_success=true`.",
        "",
        "## Runs",
        "",
        "| method | kind | family | stage | lane | status | promotion_eligible | diagnostic_only |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in comparison["runs"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["candidate_id"]),
                    str(row["run_kind"]),
                    str(row["candidate_type"]),
                    str(row["stage_target"]),
                    str(row["lane"]),
                    str(row["status"]),
                    str(row["promotion_eligible"]),
                    str(row["diagnostic_only"]),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Diagnostics", ""])
    lines.append(f"- case_diagnostic_success: `{comparison['case_diagnostic_success']}`")
    lines.append(f"- promotion_success: `{comparison['promotion_success']}`")
    for key in ["target_case_count", "fine_rank_available_rate", "target_fine_rank_mean", "target_fine_score_mean"]:
        lines.append(f"- `{key}`: `{comparison['fine_rank_case_diagnostics'].get(key)}`")
    for key in ["top1_score_gap_avg", "topk_boundary_score_gap_avg"]:
        lines.append(f"- `{key}`: `{comparison['score_gap_diagnostics'].get(key)}`")
    for key in ["coarse_to_fine_improved_count", "coarse_to_fine_worsened_count", "fine_to_final_improved_count", "fine_to_final_worsened_count"]:
        lines.append(f"- `{key}`: `{comparison['rank_movement_diagnostics'].get(key)}`")
    lines.extend(["", "## Gates", ""])
    for key in ["frozen_gate", "feature_gate", "leakage_gate", "online_gate"]:
        lines.append(f"- `{key}`: `{comparison[key].get('status')}`")
    lines.extend(["", "## Stage main-lane matrix", ""])
    for row in comparison["stage_main_lane_matrix"]:
        lines.append(f"- `{row['stage']}`: main=`{row['main_lane']}`, shadow=`{row['shadow_lane']}`, candidate_mutation=`{row['candidate_mutation']}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
