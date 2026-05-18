from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, write_json
from rs_core.recsys.evaluation import (
    build_ranking_feature_contract,
    compare_frozen_candidate_signatures,
    inspect_physical_ranking_pipeline_artifacts,
    inspect_ranking_run_artifacts,
    strict_ranking_promotion_status,
)
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.ltr_training import train_ltr_ranker
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

_PHASE = "phase_1_31_ranking_algorithm_scaffold"
_BASELINE_METHOD_ID = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_31_ranking_algorithm_scaffold"
DEFAULT_SEED = 20260513
PHYSICAL_PIPELINE_OVERRIDE = {
    "enabled": True,
    "mode": "pass_through",
    "stages": ["coarse", "fine", "rerank"],
    "promotion_claim": "none",
}
RULE_VARIANT_CONFIG = {
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
        "itemcf_multi_source_boost": 0.05,
        "two_tower_itemcf_source_boost": 0.05,
        "semantic_only_penalty": 0.05,
        "popular_only_penalty": 0.05,
    },
    "item_feature_rerank": {
        "enabled": True,
        "weights": {
            "multi_source": 0.05,
            "two_tower_itemcf_source": 0.05,
            "two_tower_semantic_source": 0.05,
            "popular_only": -0.05,
        },
    },
}
LTR_FEATURE_CONFIG = {"version": "ltr_v2"}
LTR_VARIANT = {
    "model_type": "pointwise_logistic",
    "train": {"epochs": 3, "learning_rate": 0.1, "positive_weight": 1.0, "negative_weight": 1.0},
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
    parser = argparse.ArgumentParser(description="Run Phase 1.31 ranking algorithm scaffold on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 1.31 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in scaffold artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_1_31_ranking_algorithm_scaffold(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_1_31_ranking_algorithm_scaffold(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users, seed)
    method_specs = build_method_specs()
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, method_specs[0], run_id, command_text)
    rule_row = _run_rule_variant(output_dir, limit_users, feature_contract, method_specs[1], baseline_row, run_id, command_text)
    learned_row = _run_ltr_variant(output_dir, limit_users, feature_contract, method_specs[2], baseline_row, run_id, command_text, seed)
    blocked_rows = _blocked_rows(method_specs[3:], run_id, command_text)
    runnable_rows = [baseline_row, rule_row, learned_row]
    physical_pipeline_summary = _physical_pipeline_summary(baseline_row)
    method_registry = [
        _method_registry_entry(row, run_kind=str(row["run_kind"]))
        for row in runnable_rows
    ] + [row["method_registry_entry"] for row in blocked_rows]
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "seed": seed,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "method_specs": [spec.to_registry_payload() for spec in method_specs],
        "architecture": {
            "target_layers": ["recall", "coarse_rank", "fine_rank", "rerank"],
            "current_physical_scope": "frozen_pool200_algorithm_scaffold_with_pass_through_stage_artifacts",
            "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
            "promotion_boundary": "scaffold_only_no_tree_neural_gpu_promotion",
        },
        "promotion_policy": {
            "frozen_pool200_required": True,
            "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
            "top_k": REQUIRED_TOP_K,
            "lo_po_gate_smoke_stage_trace_not_promotion_evidence": True,
            "online_metrics_forbidden_as_current_offline_evidence": True,
            "gpu_required_methods_blocked_without_verified_gpu": True,
        },
        "dependency_checks": _dependency_checks(method_specs),
        "gpu_check": _gpu_check(),
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
        "physical_pipeline_inspection": physical_pipeline_summary["inspection"],
        "physical_pipeline_summary": physical_pipeline_summary["summary"],
        "final_decision": {
            "selected_route": _BASELINE_METHOD_ID,
            "status": "BASELINE_FINAL_ROUTE",
            "reason": "phase_1_31_establishes_algorithm_scaffold_contract_and_blocks_unready_methods_without_claiming_promotion",
        },
        "method_registry": method_registry,
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in runnable_rows],
        "runs": [public_ranking_run_row(row) for row in runnable_rows] + blocked_rows,
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
            metadata={"config_path": str(BASELINE_CONFIG), "role": "baseline_current_champion"},
        ),
        RankingMethodSpec(
            method_id="normalized_additive_source_aware_rule_rerank",
            method_family="rule_based_rerank",
            stage_target="rerank",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="diagnostic",
            blocked_recovery_condition="valid/test multi-run terminal promotion evidence is required before this executable rule variant can challenge the champion",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"config_override": RULE_VARIANT_CONFIG, "evidence_scope": "same_run_diagnostic_only"},
        ),
        RankingMethodSpec(
            method_id="pointwise_logistic_fine_ranker_lopo",
            method_family="shallow_learned_fine_ranker",
            stage_target="fine",
            requires_training=True,
            requires_gpu=False,
            dependency=None,
            promotion_lane="diagnostic",
            blocked_recovery_condition="replace LOPO diagnostic training with valid/test promotion evidence before challenger or promotion use",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"model_type": LTR_VARIANT["model_type"], "features": LTR_FEATURE_CONFIG, "evidence_scope": "lopo_training_diagnostic_only"},
        ),
        RankingMethodSpec(
            method_id="sklearn_gbdt_fine_ranker_prepare",
            method_family="tree_gbdt",
            stage_target="fine",
            requires_training=True,
            requires_gpu=False,
            dependency="sklearn",
            promotion_lane="blocked",
            blocked_recovery_condition="sklearn is importable and a candidate-level GBDT training/inference adapter plus valid/test evidence are implemented",
            metadata={"preparation_scope": "dependency_check_only_no_tree_promotion"},
        ),
        RankingMethodSpec(
            method_id="xgboost_lambdamart_fine_ranker_prepare",
            method_family="lambdamart",
            stage_target="fine",
            requires_training=True,
            requires_gpu=True,
            dependency="xgboost",
            promotion_lane="blocked",
            blocked_recovery_condition="xgboost and a verified GPU plus candidate-level LambdaMART adapter and valid/test evidence are available",
            metadata={"preparation_scope": "dependency_gpu_check_only_no_lambdamart_promotion"},
        ),
        RankingMethodSpec(
            method_id="lightgbm_lambdamart_fine_ranker_prepare",
            method_family="lambdamart",
            stage_target="fine",
            requires_training=True,
            requires_gpu=True,
            dependency="lightgbm",
            promotion_lane="blocked",
            blocked_recovery_condition="lightgbm and a verified GPU plus candidate-level LambdaMART adapter and valid/test evidence are available",
            metadata={"preparation_scope": "dependency_gpu_check_only_no_lambdamart_promotion"},
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
    variant_output_dir = output_dir / _BASELINE_METHOD_ID
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "export_ranking_stage_artifacts": True,
            "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
            "strategy_name": f"{_PHASE}_{_BASELINE_METHOD_ID}",
        },
    )
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(_BASELINE_METHOD_ID, result, metrics)
    artifact_paths = _artifact_paths(variant_output_dir, result, metrics)
    row = build_ranking_run_row(
        run_id=f"{_PHASE}:{run_id}",
        run_index=0,
        run_kind="baseline",
        method_spec=method_spec,
        config=_registry_config(metrics, _BASELINE_METHOD_ID),
        frozen_rows=frozen_rows,
        metrics={key: metrics.get(key) for key in METRIC_FIELDS},
        strict_status={"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline", "scaffold_contract_baseline"], "metric_delta": {}},
        artifact_paths=artifact_paths,
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
        command_text=command_text,
    )
    row["raw_metrics"] = metrics
    row["frozen_rows"] = frozen_rows
    return row


def _run_rule_variant(
    output_dir: Path,
    limit_users: int | None,
    feature_contract: dict[str, Any],
    method_spec: RankingMethodSpec,
    baseline_row: dict[str, Any],
    run_id: str,
    command_text: str,
) -> dict[str, Any]:
    return _run_hybrid_variant(
        output_dir=output_dir,
        limit_users=limit_users,
        feature_contract=feature_contract,
        method_spec=method_spec,
        baseline_row=baseline_row,
        run_id=run_id,
        run_index=1,
        command_text=command_text,
        config_overrides=RULE_VARIANT_CONFIG,
        strict_reason_overrides=["same_run_rule_variant_diagnostic_only", "valid_test_promotion_evidence_missing"],
        ltr_enabled=False,
    )


def _run_ltr_variant(
    output_dir: Path,
    limit_users: int | None,
    feature_contract: dict[str, Any],
    method_spec: RankingMethodSpec,
    baseline_row: dict[str, Any],
    run_id: str,
    command_text: str,
    seed: int,
) -> dict[str, Any]:
    training_result = _train_ltr_variant(output_dir, limit_users, seed)
    row = _run_hybrid_variant(
        output_dir=output_dir,
        limit_users=limit_users,
        feature_contract=feature_contract,
        method_spec=method_spec,
        baseline_row=baseline_row,
        run_id=run_id,
        run_index=2,
        command_text=command_text,
        config_overrides={"ltr_model": {"enabled": True, "model_path": training_result["model_path"], "score_scale": 1.0, "features": LTR_FEATURE_CONFIG}},
        strict_reason_overrides=["lopo_training_diagnostic_only", "ltr_enabled_gate_diagnostic_only", "valid_test_promotion_gate_adr_missing"],
        ltr_enabled=True,
        feature_contract_gate_summary=_training_feature_contract_gate(training_result),
        leakage_gate_summary=_training_leakage_gate(training_result),
    )
    row["real_training"] = {
        "model_path": training_result["model_path"],
        "metrics_path": training_result["metrics_path"],
        "candidate_rows_path": training_result.get("candidate_rows_path"),
        "training_config_path": training_result["training_config_path"],
        "training_log_path": training_result["training_log_path"],
    }
    return row


def _run_hybrid_variant(
    *,
    output_dir: Path,
    limit_users: int | None,
    feature_contract: dict[str, Any],
    method_spec: RankingMethodSpec,
    baseline_row: dict[str, Any],
    run_id: str,
    run_index: int,
    command_text: str,
    config_overrides: dict[str, Any],
    strict_reason_overrides: list[str],
    ltr_enabled: bool,
    feature_contract_gate_summary: dict[str, Any] | None = None,
    leakage_gate_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    variant_output_dir = output_dir / method_spec.method_id
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            **config_overrides,
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
    frozen_comparison = compare_frozen_candidate_signatures(baseline_row["frozen_rows"], frozen_rows)
    status = strict_ranking_promotion_status(
        baseline_row["raw_metrics"],
        metrics,
        frozen_comparison,
        ltr_enabled=ltr_enabled,
        feature_contract_gate_summary=feature_contract_gate_summary,
        leakage_gate_summary=leakage_gate_summary,
    )
    status = status | {
        "status": "INVALID/STOP" if status.get("status") == "INVALID/STOP" else "PARTIAL diagnostic-only",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": sorted(set([*status.get("reasons", []), *strict_reason_overrides])),
    }
    artifact_paths = _artifact_paths(variant_output_dir, result, metrics)
    row = build_ranking_run_row(
        run_id=f"{_PHASE}:{run_id}",
        run_index=run_index,
        run_kind="diagnostic",
        method_spec=method_spec,
        config=_registry_config(metrics, method_spec.method_id),
        frozen_rows=frozen_rows,
        baseline_frozen_rows=baseline_row["frozen_rows"],
        metrics={key: metrics.get(key) for key in METRIC_FIELDS},
        strict_status=status,
        artifact_paths=artifact_paths,
        feature_contract=feature_contract,
        feature_contract_gate_summary=feature_contract_gate_summary or _not_applicable_feature_contract_gate(),
        leakage_gate_summary=leakage_gate_summary or _not_applicable_leakage_gate(),
        command_text=command_text,
    )
    row["raw_metrics"] = metrics
    row["frozen_rows"] = frozen_rows
    return row


def _train_ltr_variant(output_dir: Path, limit_users: int | None, seed: int) -> dict[str, Any]:
    training_output_dir = output_dir / "real_training" / "pointwise_logistic_fine_ranker_lopo"
    training_config = {
        "seed": seed,
        "evaluation_mode": "leave_one_positive_out",
        "model_type": LTR_VARIANT["model_type"],
        "features": LTR_FEATURE_CONFIG,
        "write_candidate_rows": True,
        "max_candidate_rows": 10000,
        "train": LTR_VARIANT["train"],
    }
    training_config_path = training_output_dir / "training_config.json"
    write_json(training_config_path, training_config)
    result = train_ltr_ranker(
        BASELINE_CONFIG,
        output_dir=training_output_dir,
        limit_users=limit_users,
        config_overrides={
            "evaluation_mode": "leave_one_positive_out",
            "ltr_training": {
                "model_type": LTR_VARIANT["model_type"],
                "features": LTR_FEATURE_CONFIG,
                "write_candidate_rows": True,
                "max_candidate_rows": 10000,
                "train": LTR_VARIANT["train"],
            },
        },
    )
    training_log = {
        "seed": seed,
        "variant_name": "pointwise_logistic_fine_ranker_lopo",
        "model_type": LTR_VARIANT["model_type"],
        "metrics_path": result["metrics_path"],
        "model_path": result["model_path"],
        "candidate_rows_path": result.get("candidate_rows_path"),
        "metrics": result["metrics"],
        "diagnostic_only": True,
        "promotion_eligible": False,
        "reasons": ["lopo_training_diagnostic_only", "valid_test_promotion_gate_adr_missing"],
    }
    training_log_path = training_output_dir / "training_log.json"
    write_json(training_log_path, training_log)
    return result | {"training_config_path": str(training_config_path), "training_log_path": str(training_log_path)}


def _blocked_rows(method_specs: list[RankingMethodSpec], run_id: str, command_text: str) -> list[dict[str, Any]]:
    dependency_checks = _dependency_checks(method_specs)
    gpu = _gpu_check()
    rows = []
    for run_index, spec in enumerate(method_specs, start=1):
        dependency_available = dependency_checks.get(spec.method_id, {}).get("available")
        gpu_available = gpu["available"] if spec.requires_gpu else None
        reasons = ["not_run_as_phase_1_31_scaffold", "adapter_or_evidence_not_ready"]
        if spec.method_family in {"tree_gbdt", "lambdamart"}:
            reasons.append("tree_lambdamart_preparation_only")
        rows.append(
            build_blocked_ranking_run_row(
                run_id=f"{_PHASE}:{run_id}",
                run_index=run_index,
                method_spec=spec,
                dependency_available=dependency_available,
                gpu_available=gpu_available,
                blocked_reason=reasons,
                command_text=command_text,
            )
        )
    return rows


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
        "frozen_candidates_exported": True,
        "ranking_stage_artifacts_exported": True,
        "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
    }


def _method_registry_entry(row: dict[str, Any], run_kind: str) -> dict[str, Any]:
    return build_ranking_method_registry_entry_from_spec(
        RankingMethodSpec(**{key: value for key, value in row["method_spec"].items() if key != "schema_version"}),
        run_kind=run_kind,
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_METHOD_ID if run_kind == "baseline" else None,
        challenger_of=_BASELINE_METHOD_ID if run_kind != "baseline" else None,
        dependency_status="not_required",
    )


def _training_feature_contract_gate(training_result: dict[str, Any]) -> dict[str, Any]:
    summary = (training_result.get("metrics") or {}).get("feature_contract_gate")
    if isinstance(summary, dict):
        return summary
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "REJECT", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["missing_feature_contract_gate_summary"]}


def _training_leakage_gate(training_result: dict[str, Any]) -> dict[str, Any]:
    summary = (training_result.get("metrics") or {}).get("leakage_gate")
    if isinstance(summary, dict):
        return summary
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "REJECT", "checked_rows": 0, "reasons": ["missing_leakage_gate_summary"]}


def _dependency_checks(method_specs: list[RankingMethodSpec]) -> dict[str, dict[str, Any]]:
    checks = {}
    for spec in method_specs:
        if spec.dependency is None:
            checks[spec.method_id] = {"dependency": None, "available": None, "status": "not_required", "checked_by": "not_required"}
        else:
            available = importlib.util.find_spec(spec.dependency) is not None
            checks[spec.method_id] = {"dependency": spec.dependency, "available": available, "status": "available" if available else "missing", "checked_by": "importlib.util.find_spec"}
    return checks


def _gpu_check() -> dict[str, Any]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return {"available": False, "status": "missing", "checked_by": "shutil.which:nvidia-smi", "device": None}
    try:
        completed = subprocess.run([nvidia_smi, "--query-gpu=name", "--format=csv,noheader"], check=False, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "status": "unverified", "checked_by": "nvidia-smi", "device": None}
    devices = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return {"available": completed.returncode == 0 and bool(devices), "status": "available" if completed.returncode == 0 and devices else "unavailable", "checked_by": "nvidia-smi", "device": devices[0] if devices else None}


def _physical_pipeline_summary(row: dict[str, Any]) -> dict[str, Any]:
    summary_path = row.get("ranking_stage_summary_path")
    if summary_path and Path(str(summary_path)).exists():
        summary = read_json(summary_path)
    else:
        summary = {
            "trace_path": row.get("ranking_stage_trace_path"),
            "summary_path": summary_path,
            "candidate_pool_size": row.get("candidate_pool_size"),
            "top_k": row.get("top_k"),
        }
    return {"summary": summary, "inspection": inspect_physical_ranking_pipeline_artifacts(summary)}


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or REQUIRED_CANDIDATE_POOL_SIZE
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or REQUIRED_TOP_K
    config["physical_ranking_pipeline"] = PHYSICAL_PIPELINE_OVERRIDE
    config["export_ranking_stage_artifacts"] = True
    return config


def _command_text(output_dir: Path, limit_users: int | None, seed: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_1_31_ranking_algorithm_scaffold.py", "--output-dir", str(output_dir), "--seed", str(seed)]
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
    physical = comparison["physical_pipeline_inspection"]
    lines = [
        "# Phase 1.31 Ranking Algorithm Scaffold",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Seed: `{comparison['seed']}` (recorded for deterministic downstream methods; baseline pass-through does not use randomness)",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: frozen pool200 / top_k=5 ranking scaffold only; recall semantics are unchanged.",
        "- Boundary: tree, LambdaMART, neural, and GPU promotion are not implemented in this phase.",
        "",
        "## Inspections",
        "",
        f"- Artifact inspection: `{comparison['artifact_inspection']['status']}`",
        f"- Physical pipeline inspection: `{physical['status']}`",
        f"- Candidate pool size: `{comparison['candidate_pool_size']}`",
        f"- Top K: `{comparison['top_k']}`",
        f"- Online metric claims: `{physical.get('online_metric_claims')}`",
        "",
        "## Runs",
        "",
        "| method | kind | family | lane | status | frozen_match | blocked_reason | recovery_condition |",
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
                    str(row["lane"]),
                    str(row["status"]),
                    str((row.get("frozen_candidate_comparison") or {}).get("match")),
                    ", ".join(row.get("blocked_reason", [])),
                    str(row.get("blocked_recovery_condition", "")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Method registry", "", "| method | family | lane | state | gpu_status | dependency_status | reasons |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for row in comparison["method_registry"]:
        gpu = row.get("gpu_resource", {})
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["lane"], row["state"], str(gpu.get("status")), str(gpu.get("dependency_status")), ", ".join(row.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
