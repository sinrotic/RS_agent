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

from rs_core.common.io import read_json, write_json
from rs_core.recsys.evaluation import (
    build_ranking_experiment_registry_entry,
    build_ranking_feature_contract,
    build_ranking_gpu_resource_summary,
    build_ranking_method_registry_entry,
    compare_frozen_candidate_signatures,
    inspect_physical_ranking_pipeline_artifacts,
    inspect_ranking_run_artifacts,
)
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift
from rs_lab.experiments.ranking.run_phase_1_28_lightweight_learned_ranker import _not_applicable_feature_contract_gate, _not_applicable_leakage_gate, _read_frozen_rows

_PHASE = "phase_1_30_physical_ranking_pipeline"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_30_physical_ranking_pipeline"
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
PHYSICAL_PIPELINE_OVERRIDE = {
    "enabled": True,
    "mode": "pass_through",
    "stages": ["coarse", "fine", "rerank"],
    "promotion_claim": "none",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.30 physical ranking pipeline inspection on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 1.30 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_1_30_physical_ranking_pipeline(output_dir=output_dir, limit_users=args.limit_users)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_1_30_physical_ranking_pipeline(output_dir: Path, limit_users: int | None = None) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users)
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
    runs = [baseline_row]
    public_runs = [_public_run_row(row) for row in runs]
    physical_pipeline_summary = _physical_pipeline_summary(baseline_row)
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "candidate_pool_size": 200,
        "top_k": 5,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "architecture": {
            "target_layers": ["recall", "coarse_rank", "fine_rank", "rerank"],
            "current_physical_scope": "frozen_pool200_to_physical_coarse_fine_rerank_pass_through_trace",
            "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
            "promotion_boundary": "inspection_only_no_candidate_promotion",
        },
        "promotion_policy": {
            "frozen_pool200_required": True,
            "candidate_pool_size": 200,
            "top_k": 5,
            "physical_pipeline_pass_through_only": True,
            "no_method_promotion_claim": True,
            "online_metrics_forbidden_as_current_offline_evidence": True,
        },
        "final_decision": {
            "selected_route": _BASELINE_VARIANT,
            "status": "BASELINE_FINAL_ROUTE",
            "reason": "phase_1_30_inspects_physical_coarse_fine_rerank_artifacts_without_claiming_ranking_lift_or_promotion",
        },
        "artifact_inspection": inspect_ranking_run_artifacts(runs, required_paths=["metrics_path", "recommendations_path", "ranking_cases_path", "ranking_case_summary_path", "report_path", "frozen_candidates_path", "ranking_stage_trace_path", "ranking_stage_summary_path"]),
        "physical_pipeline_inspection": physical_pipeline_summary["inspection"],
        "physical_pipeline_summary": physical_pipeline_summary["summary"],
        "method_registry": [_method_registry_row(baseline_row)],
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in runs],
        "runs": public_runs,
    }


def _run_baseline(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, command_text: str) -> dict[str, Any]:
    variant_output_dir = output_dir / _BASELINE_VARIANT
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "export_ranking_stage_artifacts": True,
            "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
            "strategy_name": f"{_PHASE}_{_BASELINE_VARIANT}",
        },
    )
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(_BASELINE_VARIANT, result, metrics)
    strict_status = _baseline_status()
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:{_BASELINE_VARIANT}",
        config=_registry_config(metrics, _BASELINE_VARIANT),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=strict_status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
    )
    return _variant_row(_BASELINE_VARIANT, "physical_pipeline_baseline", run_id, command_text, result, metrics, frozen_rows, strict_status, registry_entry)


def _variant_row(
    variant_name: str,
    candidate_type: str,
    run_id: str,
    command_text: str,
    result: dict[str, Any],
    metrics: dict[str, Any],
    frozen_rows: list[dict[str, Any]],
    strict_status: dict[str, Any],
    registry_entry: dict[str, Any],
) -> dict[str, Any]:
    freeze = _freeze_values(metrics)
    status, drift = _status_and_drift(freeze, freeze)
    frozen_candidate_comparison = compare_frozen_candidate_signatures(frozen_rows, frozen_rows)
    ranking_stage_trace_path = result.get("ranking_stage_trace_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("trace")
    ranking_stage_summary_path = result.get("ranking_stage_summary_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("summary")
    return {
        "run_id": run_id,
        "run_index": 0,
        "candidate_id": variant_name,
        "candidate_type": candidate_type,
        "lane": "inspection",
        "promotion_eligible": False,
        "diagnostic_only": True,
        "status": status,
        "strict_status": strict_status,
        "ranking_experiment_registry": registry_entry,
        "drift": drift,
        "frozen_candidate_comparison": frozen_candidate_comparison,
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(Path(result["metrics_path"]).parent),
        "command_text": command_text,
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path"),
        "ranking_stage_trace_path": ranking_stage_trace_path,
        "ranking_stage_summary_path": ranking_stage_summary_path,
        "frozen_candidates_exported": True,
        "ranking_stage_artifacts_exported": True,
        "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
        "metrics": {key: metrics.get(key) for key in METRIC_FIELDS},
        "raw_metrics": metrics,
        "frozen_rows": frozen_rows,
        "freeze": freeze,
    }


def _physical_pipeline_summary(row: dict[str, Any]) -> dict[str, Any]:
    summary_path = row.get("ranking_stage_summary_path")
    if not summary_path or not Path(str(summary_path)).exists():
        summary = {
            "trace_path": row.get("ranking_stage_trace_path"),
            "summary_path": summary_path,
            "candidate_pool_size": row.get("ranking_experiment_registry", {}).get("candidate_pool_size"),
            "top_k": row.get("ranking_experiment_registry", {}).get("top_k"),
        }
    else:
        summary = read_json(summary_path)
    inspection = inspect_physical_ranking_pipeline_artifacts(summary)
    return {"summary": summary, "inspection": inspection}


def _method_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane="inspection",
        state="champion",
        promotion_eligible=False,
        diagnostic_only=True,
        reasons=["physical_pipeline_inspection_only", "same_run_baseline", "no_promotion_claim"],
        champion_id=_BASELINE_VARIANT,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or 200
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or 5
    config["physical_ranking_pipeline"] = PHYSICAL_PIPELINE_OVERRIDE
    config["export_ranking_stage_artifacts"] = True
    return config


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _baseline_status() -> dict[str, Any]:
    return {
        "status": "BASELINE",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": ["same_run_baseline", "physical_pipeline_inspection_only", "no_promotion_claim"],
        "metric_delta": {},
    }


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _command_text(output_dir: Path, limit_users: int | None) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_1_30_physical_ranking_pipeline.py", "--output-dir", str(output_dir)]
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
    summary = comparison["physical_pipeline_summary"]
    lines = [
        "# Phase 1.30 Physical Ranking Pipeline",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: frozen pool200 baseline inspection only; physical coarse/fine/rerank stages pass through the same candidate pool and do not claim promotion.",
        f"- Ranking stage trace: `{summary.get('trace_path')}`",
        f"- Ranking stage summary: `{summary.get('summary_path')}`",
        "",
        "## Inspection",
        "",
        f"- Artifact inspection: `{comparison['artifact_inspection']['status']}`",
        f"- Physical pipeline inspection: `{physical['status']}`",
        f"- Stage counts: `{physical.get('stage_counts')}`",
        f"- Pass-through stage failures: `{physical.get('pass_through_stage_failures')}`",
        f"- Online metric claims: `{physical.get('online_metric_claims')}`",
        "",
        "## Runs",
        "",
        "| candidate | lane | type | artifact_status | physical_status | frozen_match |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in comparison["runs"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["candidate_id"],
                    row["lane"],
                    row["candidate_type"],
                    comparison["artifact_inspection"]["status"],
                    physical["status"],
                    str(row.get("frozen_candidate_match")),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Method registry", "", "| method | family | lane | state | promotion_eligible | reasons |", "| --- | --- | --- | --- | --- | --- |"])
    for row in comparison["method_registry"]:
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["lane"], row["state"], str(row["promotion_eligible"]), ", ".join(row.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
