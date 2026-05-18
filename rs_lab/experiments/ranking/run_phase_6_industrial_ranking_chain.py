from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json
from rs_core.recsys.evaluation import build_ranking_feature_contract, inspect_ranking_run_artifacts, strict_ranking_promotion_status
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.ranking_experiments import (
    REQUIRED_CANDIDATE_POOL_SIZE,
    REQUIRED_TOP_K,
    RankingMethodSpec,
    build_blocked_ranking_run_row,
    build_ranking_method_registry_entry_from_spec,
    build_ranking_run_row,
    public_ranking_run_row,
)
from rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS
from rs_lab.experiments.ranking.run_phase_1_26_real_ranking_experiments import _not_applicable_feature_contract_gate, _not_applicable_leakage_gate, _read_frozen_rows

_PHASE = "phase_6_industrial_ranking_chain"
_BASELINE_METHOD_ID = "same_run_pool200_baseline"
_INDUSTRIAL_METHOD_ID = "industrial_coarse_fine_rerank_chain_diagnostic"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
CURRENT_RECALL_MAINLINE_CONFIG = ROOT / "configs/recall/phase_1_21/phase_1_21_recall_coverage_pool200_experimental.yaml"
CURRENT_RECALL_MAINLINE_ID = "source_balanced_pool200_hybrid_recall"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_6_industrial_ranking_chain"
DEFAULT_SEED = 20260513
PHYSICAL_PIPELINE_OVERRIDE = {
    "enabled": True,
    "mode": "pass_through",
    "stages": ["coarse", "fine", "rerank"],
    "promotion_claim": "none",
}
INDUSTRIAL_CHAIN_CONFIG: dict[str, Any] = {
    "rank_weights": {
        "itemcf": 1.0,
        "semantic": 0.86,
        "two_tower": 0.92,
        "popular": 0.45,
        "recent": 0.18,
        "verified": 0.12,
        "time_decay": 0.1,
    },
    "normalized_additive_ranking": {
        "enabled": True,
        "weights": {
            "source_signal": 0.2,
            "item_feature": 0.2,
            "freshness_quality": 0.1,
            "near_miss_tiebreak_strength": 0.05,
        },
    },
    "source_aware_fusion": {
        "enabled": True,
        "itemcf_multi_source_boost": 0.06,
        "two_tower_itemcf_source_boost": 0.05,
        "two_tower_semantic_source_boost": 0.04,
        "semantic_only_penalty": 0.04,
        "popular_only_penalty": 0.08,
    },
    "item_feature_rerank": {
        "enabled": True,
        "weights": {
            "multi_source": 0.07,
            "two_tower_itemcf_source": 0.05,
            "two_tower_semantic_source": 0.04,
            "popular_only": -0.08,
            "semantic_only": -0.03,
        },
    },
    "topk_source_minimums": {"itemcf": 1},
    "ltr_model": {"enabled": False},
    "ranking_v2": {"enabled": False},
}
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6 industrial coarse→fine→rerank chain on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 6 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_6_industrial_ranking_chain(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_6_industrial_ranking_chain(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users, seed)
    method_specs = build_method_specs()
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, method_specs[0], run_id, command_text)
    industrial_row = _run_industrial_chain(output_dir, limit_users, feature_contract, method_specs[1], baseline_row, run_id, command_text)
    blocked_rows = _blocked_rows(method_specs[2:], run_id, command_text)
    runnable_rows = [baseline_row, industrial_row]

    return {
        "phase": _PHASE,
        "run_id": run_id,
        "seed": seed,
        "limit_users": limit_users,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "baseline_config_path": str(BASELINE_CONFIG),
        "current_recall_mainline": _current_recall_mainline_summary(),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "industrial_chain": _industrial_chain_summary(),
        "stage_assignment_summary": _stage_assignment_summary(method_specs),
        "promotion_boundary": _promotion_boundary(),
        "method_specs": [spec.to_registry_payload() for spec in method_specs],
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
            ],
        ),
        "method_registry": [_method_registry_entry(row) for row in runnable_rows] + [row["method_registry_entry"] for row in blocked_rows],
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in runnable_rows],
        "runs": [public_ranking_run_row(row) for row in runnable_rows] + blocked_rows,
        "final_decision": {
            "selected_route": _INDUSTRIAL_METHOD_ID,
            "status": "DIAGNOSTIC_DEFAULT_CHAIN_READY",
            "reason": "industrial-style coarse/fine/rerank algorithms are wired for use on frozen pool200 without claiming offline promotion",
        },
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
            metadata={
                "config_path": str(BASELINE_CONFIG),
                "fixed_recall_config_path": str(CURRENT_RECALL_MAINLINE_CONFIG),
                "current_recall_mainline_id": CURRENT_RECALL_MAINLINE_ID,
                "role": "frozen_pool200_current_champion_on_source_balanced_recall",
            },
        ),
        RankingMethodSpec(
            method_id=_INDUSTRIAL_METHOD_ID,
            method_family="industrial_coarse_fine_rerank_chain",
            stage_target="rerank",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="phase_6_diagnostic_default_chain",
            blocked_recovery_condition="multi-run valid/test evidence and explicit promotion gate are required before replacing the champion",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={
                "stage_algorithms": _industrial_chain_summary(),
                "config_override": INDUSTRIAL_CHAIN_CONFIG,
                "fixed_recall_config_path": str(CURRENT_RECALL_MAINLINE_CONFIG),
                "current_recall_mainline_id": CURRENT_RECALL_MAINLINE_ID,
                "frozen_pool200_only": True,
                "does_not_crop_candidates": True,
                "ltr_enabled": False,
            },
        ),
        RankingMethodSpec(
            method_id="gbdt_lambdamart_fine_rank_future_challenger_blocked",
            method_family="tree_ltr_future_challenger",
            stage_target="fine",
            requires_training=True,
            requires_gpu=True,
            dependency="xgboost_or_lightgbm",
            promotion_lane="blocked",
            blocked_recovery_condition="implement real train/valid/test fine-rank adapter, group objective, serving adapter, and promotion gates",
            promotion_eligible=False,
            diagnostic_only=False,
            metadata={"deterministic_stand_in": False, "future_route": "fine_rank_tree_ltr"},
        ),
        RankingMethodSpec(
            method_id="neural_sequence_agent_online_future_route_blocked",
            method_family="neural_sequence_agent_online_ranker",
            stage_target="rerank",
            requires_training=True,
            requires_gpu=True,
            dependency="torch",
            promotion_lane="blocked",
            blocked_recovery_condition="requires sequence coverage, online/replay labels, safe adapter, and future-online metric contract",
            promotion_eligible=False,
            diagnostic_only=False,
            metadata={"future_route": "DIN/BST/Agent feedback rerank", "online_metrics_current_evidence": False},
        ),
    ]


def _run_baseline(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], method_spec: RankingMethodSpec, run_id: str, command_text: str) -> dict[str, Any]:
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
    return _build_executable_row(0, "baseline", method_spec, result, variant_output_dir, feature_contract, run_id, command_text, baseline_frozen_rows=None, baseline_metrics=None)


def _run_industrial_chain(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], method_spec: RankingMethodSpec, baseline_row: dict[str, Any], run_id: str, command_text: str) -> dict[str, Any]:
    variant_output_dir = output_dir / method_spec.method_id
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            **INDUSTRIAL_CHAIN_CONFIG,
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "export_ranking_stage_artifacts": True,
            "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
            "strategy_name": f"{_PHASE}_{method_spec.method_id}",
        },
    )
    row = _build_executable_row(1, "diagnostic", method_spec, result, variant_output_dir, feature_contract, run_id, command_text, baseline_frozen_rows=baseline_row["frozen_rows"], baseline_metrics=baseline_row["raw_metrics"])
    row["adapter_execution"] = "industrial_rule_chain_run_on_frozen_pool200"
    row["promotion_evidence_claim"] = "none"
    return row


def _build_executable_row(
    run_index: int,
    run_kind: str,
    method_spec: RankingMethodSpec,
    result: dict[str, Any],
    variant_output_dir: Path,
    feature_contract: dict[str, Any],
    run_id: str,
    command_text: str,
    baseline_frozen_rows: list[dict[str, Any]] | None,
    baseline_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(method_spec.method_id, result, metrics)
    if run_kind == "baseline":
        status = {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline", "frozen_pool200_boundary"], "metric_delta": {}}
    else:
        comparison = build_ranking_run_row(
            run_id=f"{_PHASE}:{run_id}:internal_comparison",
            run_index=run_index,
            run_kind="diagnostic",
            method_spec=method_spec,
            config=_registry_config(metrics, method_spec.method_id),
            frozen_rows=frozen_rows,
            baseline_frozen_rows=baseline_frozen_rows,
        )["frozen_candidate_comparison"]
        status = strict_ranking_promotion_status(baseline_metrics or metrics, metrics, comparison, ltr_enabled=False)
        status = status | {
            "status": "INVALID/STOP" if status.get("status") == "INVALID/STOP" else "PARTIAL diagnostic-only",
            "promotable": False,
            "diagnostic_only": True,
            "reasons": sorted(set([*status.get("reasons", []), "industrial_chain_diagnostic_only", "valid_test_promotion_evidence_missing"])),
        }
    row = build_ranking_run_row(
        run_id=f"{_PHASE}:{run_id}",
        run_index=run_index,
        run_kind=run_kind,
        method_spec=method_spec,
        config=_registry_config(metrics, method_spec.method_id),
        frozen_rows=frozen_rows,
        baseline_frozen_rows=baseline_frozen_rows,
        metrics={key: metrics.get(key) for key in METRIC_FIELDS},
        strict_status=status,
        artifact_paths=_artifact_paths(variant_output_dir, result, metrics),
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
        command_text=command_text,
    )
    row["raw_metrics"] = metrics
    row["frozen_rows"] = frozen_rows
    return row


def _blocked_rows(method_specs: list[RankingMethodSpec], run_id: str, command_text: str) -> list[dict[str, Any]]:
    return [
        build_blocked_ranking_run_row(
            run_id=f"{_PHASE}:{run_id}",
            run_index=offset,
            method_spec=spec,
            dependency_available=False,
            gpu_available=False if spec.requires_gpu else None,
            blocked_reason=["future_route_not_current_offline_evidence", "valid_test_promotion_evidence_missing"],
            command_text=command_text,
        )
        for offset, spec in enumerate(method_specs, start=2)
    ]


def _artifact_paths(variant_output_dir: Path, result: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "config_path": str(BASELINE_CONFIG),
        "fixed_recall_config_path": str(CURRENT_RECALL_MAINLINE_CONFIG),
        "current_recall_mainline_id": CURRENT_RECALL_MAINLINE_ID,
        "output_dir": str(variant_output_dir),
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path"),
        "ranking_stage_trace_path": result.get("ranking_stage_trace_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("trace"),
        "ranking_stage_summary_path": result.get("ranking_stage_summary_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("summary"),
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


def _current_recall_mainline_summary() -> dict[str, Any]:
    return {
        "mainline_id": CURRENT_RECALL_MAINLINE_ID,
        "config_path": str(CURRENT_RECALL_MAINLINE_CONFIG),
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "candidate_pool_strategy": "balanced_source_budget",
        "role": "fixed_phase_1_source_balanced_pool200_hybrid_recall_input_for_ranking",
        "ranking_scope": "ranking_only_on_frozen_candidates_from_current_recall_mainline",
    }


def _industrial_chain_summary() -> dict[str, Any]:
    return {
        "coarse_rank": {
            "algorithm": "source_weighted_metadata_prefilter_score",
            "execution": "shadow_pass_through_no_crop",
            "signals": ["itemcf", "semantic", "two_tower", "popular", "recent", "verified", "time_decay"],
        },
        "fine_rank": {
            "algorithm": "normalized_additive_plus_source_aware_item_feature_scoring",
            "execution": "full_pool200_scoring",
            "signals": ["source_signal", "item_feature", "freshness_quality", "near_miss_tiebreak"],
        },
        "rerank": {
            "algorithm": "topk_source_minimums_stable_tiebreak_local_constraint",
            "execution": "top5_local_adjustment_only",
            "constraints": INDUSTRIAL_CHAIN_CONFIG["topk_source_minimums"],
        },
        "blocked_future_mainline": ["GBDT/LambdaMART fine_rank", "neural sequence ranker", "Agent/online feedback rerank"],
    }


def _stage_assignment_summary(method_specs: list[RankingMethodSpec]) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {"coarse": [], "fine": [], "rerank": []}
    summary["coarse"].append(_INDUSTRIAL_METHOD_ID + ":source_weighted_metadata_shadow")
    for spec in method_specs:
        summary[spec.stage_target].append(spec.method_id)
    return summary


def _promotion_boundary() -> dict[str, Any]:
    return {
        "frozen_pool200_required": True,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "recall_mainline_id": CURRENT_RECALL_MAINLINE_ID,
        "fixed_recall_config_path": str(CURRENT_RECALL_MAINLINE_CONFIG),
        "recall_semantics_changed": False,
        "merge_for_user_changed": False,
        "real_coarse_pool_shrink": False,
        "coarse_rank_shadow_pass_through_only": True,
        "fine_rank_full_pool200_scoring": True,
        "rerank_top5_local_constraint_only": True,
        "industrial_chain_diagnostic_only": True,
        "ltr_model_currently_disabled": True,
        "online_metrics_forbidden_as_current_offline_evidence": True,
        "future_routes_blocked_until_valid_test_and_adapter_evidence": True,
        "promotion_success": False,
        "promotion_eligible": False,
    }


def _command_text(output_dir: Path, limit_users: int | None, seed: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_6_industrial_ranking_chain.py", "--output-dir", str(output_dir), "--seed", str(seed)]
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


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 6 Industrial Ranking Chain",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Seed: `{comparison['seed']}`",
        "- Scope: frozen pool200 / top_k=5; recall semantics and merge_for_user are unchanged.",
        "- Chain: coarse source-weighted metadata shadow score → fine normalized-additive/source-aware/item-feature full-pool scoring → rerank Top-5 local source constraint.",
        "- Promotion boundary: diagnostic-only until valid/test, multi-run, adapter, feature/leakage, and offline promotion gates are explicit.",
        "",
        "## Runs",
        "",
        "| method | kind | family | stage | lane | status | promotion_eligible | diagnostic_only | blocked_reason |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
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
                    ", ".join(row.get("blocked_reason", [])),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Stage assignment", ""])
    for stage, methods in comparison["stage_assignment_summary"].items():
        lines.append(f"- `{stage}`: {', '.join(methods) if methods else 'none'}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
