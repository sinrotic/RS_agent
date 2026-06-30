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

from rs_core.common.io import read_jsonl, write_json
from rs_core.offline.evaluation.ranking import build_ranking_experiment_registry_entry, build_ranking_feature_contract, build_ranking_gpu_resource_summary, build_ranking_method_registry_entry, compare_frozen_candidate_signatures, inspect_ranking_run_artifacts, strict_ranking_promotion_status
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift
from rs_lab.experiments.ranking.run_phase_1_28_lightweight_learned_ranker import LTR_FEATURE_CONFIG, _public_training_result, _training_feature_contract_gate, _training_leakage_gate, train_ltr_ranker

_PHASE = "phase_2_shallow_learned_ranker"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_2_shallow_learned_ranker"
MINIMUM_RUNS = 1
REQUIRED_CONSISTENT_RUNS = 1
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
SHALLOW_LTR_VARIANTS = [
    {
        "name": "pointwise_logistic_lopo_diagnostic",
        "model_type": "pointwise_logistic",
        "method_family": "pointwise_logistic",
        "lane": "diagnostic",
        "train": {"epochs": 3, "learning_rate": 0.1, "positive_weight": 1.0, "negative_weight": 1.0},
    },
    {
        "name": "pairwise_perceptron_lopo_diagnostic",
        "model_type": "pairwise_perceptron",
        "method_family": "pairwise_perceptron",
        "lane": "diagnostic",
        "train": {"epochs": 3, "learning_rate": 0.1, "negative_sample_per_positive": 3, "margin": 1.0},
    },
]
BLOCKED_METHODS = [
    {
        "name": "linear_ranker_valid_test_promotion",
        "method_family": "linear_ranker",
        "lane": "promotion",
        "state": "blocked",
        "reasons": ["no_independent_valid_test_training_split_for_promotion", "existing_ltr_training_is_lopo_diagnostic_only"],
    }
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 2 shallow learned-ranker diagnostics on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 2 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_2_shallow_learned_ranker(output_dir=output_dir, limit_users=args.limit_users)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_2_shallow_learned_ranker(output_dir: Path, limit_users: int | None = None) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users)
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
    run_rows = [baseline_row]
    training_results = {}
    for variant in SHALLOW_LTR_VARIANTS:
        training_result = _train_ltr_variant(output_dir, limit_users, variant)
        training_results[str(variant["name"])] = _public_training_result(training_result)
        run_rows.append(_run_ltr_variant(output_dir, limit_users, feature_contract, run_id, command_text, baseline_row, variant, training_result))
    method_registry = [_method_registry_row(row) for row in run_rows]
    method_registry.extend(_blocked_method_registry_rows())
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "minimum_runs": MINIMUM_RUNS,
        "required_consistent_runs": REQUIRED_CONSISTENT_RUNS,
        "actual_runs": 1,
        "candidate_pool_size": 200,
        "top_k": 5,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "lanes": {
            "promotion": {"candidate_types": ["baseline", "linear_ranker"], "promotion_eligible": True},
            "diagnostic": {"candidate_types": ["pointwise_logistic", "pairwise_perceptron", "lopo"], "promotion_eligible": False},
        },
        "blocked_methods": BLOCKED_METHODS,
        "promotion_policy": {"lopo_training": "diagnostic_only", "valid_test_training_required_for_promotion": True},
        "artifact_inspection": inspect_ranking_run_artifacts(run_rows) | {"phase_2_scope": "shallow_learned_ranker_on_frozen_pool200"},
        "final_decision": {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "phase_2_lopo_learned_rankers_are_diagnostic_only"},
        "ltr_training": training_results,
        "method_registry": method_registry,
        "gpu_resource_strategy": _gpu_resource_strategy(),
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in run_rows],
        "runs": [_public_run_row(row) for row in run_rows],
    }


def _train_ltr_variant(output_dir: Path, limit_users: int | None, variant: dict[str, Any]) -> dict[str, Any]:
    variant_name = str(variant["name"])
    return train_ltr_ranker(
        BASELINE_CONFIG,
        output_dir=output_dir / "ltr_training" / variant_name,
        limit_users=limit_users,
        config_overrides={
            "evaluation_mode": "leave_one_positive_out",
            "ltr_training": {
                "model_type": variant["model_type"],
                "features": LTR_FEATURE_CONFIG,
                "write_candidate_rows": True,
                "max_candidate_rows": 10000,
                "train": variant["train"],
            },
        },
    )


def _run_baseline(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, command_text: str) -> dict[str, Any]:
    variant_output_dir = output_dir / _BASELINE_VARIANT
    result = run_hybrid_demo(BASELINE_CONFIG, limit_users=limit_users, config_overrides={"output_dir": str(variant_output_dir), "report_path": str(variant_output_dir / "report.md"), "export_frozen_candidates": True, "strategy_name": f"{_PHASE}_{_BASELINE_VARIANT}"})
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(_BASELINE_VARIANT, result, metrics)
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:{_BASELINE_VARIANT}",
        config=_registry_config(metrics, _BASELINE_VARIANT),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=_baseline_status(),
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
    )
    return _variant_row(_BASELINE_VARIANT, "baseline", "promotion", True, False, run_id, command_text, result, metrics, frozen_rows, frozen_rows, metrics, _freeze_values(metrics), _baseline_status(), registry_entry)


def _run_ltr_variant(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, command_text: str, baseline_row: dict[str, Any], variant: dict[str, Any], training_result: dict[str, Any]) -> dict[str, Any]:
    variant_name = str(variant["name"])
    variant_output_dir = output_dir / variant_name
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "strategy_name": f"{_PHASE}_{variant_name}",
            "ltr_model": {"enabled": True, "model_path": training_result["model_path"], "score_scale": 1.0, "features": LTR_FEATURE_CONFIG},
        },
    )
    metrics = dict(result["metrics"])
    metrics["ltr_training"] = training_result["metrics"]
    frozen_rows = _read_frozen_rows(variant_name, result, metrics)
    freeze_comparison = compare_frozen_candidate_signatures(baseline_row["frozen_rows"], frozen_rows)
    feature_contract_gate_summary = _training_feature_contract_gate(training_result)
    leakage_gate_summary = _training_leakage_gate(training_result)
    strict_status = strict_ranking_promotion_status(
        baseline_row["raw_metrics"],
        metrics,
        freeze_comparison,
        ltr_enabled=True,
        feature_contract_gate_summary=feature_contract_gate_summary,
        leakage_gate_summary=leakage_gate_summary,
    )
    strict_status = strict_status | {"promotable": False, "diagnostic_only": True, "reasons": sorted(set([*strict_status.get("reasons", []), "lopo_training_diagnostic_only", "phase_2_valid_test_promotion_split_missing"]))}
    if strict_status.get("status") == "Promote":
        strict_status = strict_status | {"status": "PARTIAL diagnostic-only"}
    status, drift = _status_and_drift(_freeze_values(metrics), baseline_row["freeze"])
    if status == "INVALID" and "freeze_metric_drift" not in strict_status["reasons"]:
        strict_status = strict_status | {"status": "INVALID/STOP", "reasons": [*strict_status["reasons"], "freeze_metric_drift"]}
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:{variant_name}",
        config=_registry_config(metrics, variant_name),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=strict_status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=feature_contract_gate_summary,
        leakage_gate_summary=leakage_gate_summary,
    )
    row = _variant_row(variant_name, str(variant["method_family"]), "diagnostic", False, True, run_id, command_text, result, metrics, frozen_rows, baseline_row["frozen_rows"], baseline_row["raw_metrics"], baseline_row["freeze"], strict_status, registry_entry)
    row["status"] = status
    row["drift"] = drift
    row["ltr_training"] = {"model_path": training_result["model_path"], "metrics_path": training_result["metrics_path"], "candidate_rows_path": training_result.get("candidate_rows_path")}
    return row


def _variant_row(variant_name: str, candidate_type: str, lane: str, promotion_eligible: bool, diagnostic_only: bool, run_id: str, command_text: str, result: dict[str, Any], metrics: dict[str, Any], frozen_rows: list[dict[str, Any]], baseline_frozen_rows: list[dict[str, Any]], baseline_metrics: dict[str, Any], baseline_freeze: dict[str, Any], strict_status: dict[str, Any], registry_entry: dict[str, Any]) -> dict[str, Any]:
    freeze = _freeze_values(metrics)
    status, drift = _status_and_drift(freeze, baseline_freeze)
    return {
        "run_id": run_id,
        "run_index": 0,
        "candidate_id": variant_name,
        "candidate_type": candidate_type,
        "lane": lane,
        "promotion_eligible": promotion_eligible,
        "diagnostic_only": diagnostic_only,
        "status": status,
        "strict_status": strict_status,
        "ranking_experiment_registry": registry_entry,
        "drift": drift,
        "frozen_candidate_comparison": compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows),
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(Path(result["metrics_path"]).parent),
        "command_text": command_text,
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path"),
        "frozen_candidates_exported": True,
        "metrics": {key: metrics.get(key) for key in METRIC_FIELDS},
        "raw_metrics": metrics,
        "frozen_rows": frozen_rows,
        "freeze": freeze,
    }


def _method_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    state = "champion" if row["candidate_id"] == _BASELINE_VARIANT else "diagnostic"
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane=row["lane"],
        state=state,
        promotion_eligible=bool(row["promotion_eligible"]),
        diagnostic_only=bool(row["diagnostic_only"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_VARIANT if state == "champion" else None,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _blocked_method_registry_rows() -> list[dict[str, Any]]:
    return [
        build_ranking_method_registry_entry(
            method_id=str(method["name"]),
            method_family=str(method["method_family"]),
            lane=str(method["lane"]),
            state=str(method["state"]),
            promotion_eligible=False,
            diagnostic_only=False,
            reasons=list(method["reasons"]),
            gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
        )
        for method in BLOCKED_METHODS
    ]


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or 200
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or 5
    return config


def _read_frozen_rows(variant_name: str, result: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    frozen_candidates_path = result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path")
    if not frozen_candidates_path or not Path(frozen_candidates_path).exists():
        raise ValueError(f"{variant_name} did not export frozen_candidates.jsonl")
    return read_jsonl(frozen_candidates_path)


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _baseline_status() -> dict[str, Any]:
    return {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}}


def _not_applicable_feature_contract_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["ltr_model_disabled"]}


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "reasons": ["ltr_model_disabled"]}


def _gpu_resource_strategy() -> dict[str, Any]:
    return {"schema_version": "ranking_gpu_strategy_v1", "current_phase_gpu_required": False, "future_gpu_required_families": ["linear_ranker_valid_test_promotion"], "unavailable_status": "blocked-gpu-unavailable", "cpu_smoke_status": "diagnostic-cpu-smoke", "promotion_gate": "lopo_shallow_learned_rankers_are_diagnostic_until_valid_test_training_split_exists"}


def _command_text(output_dir: Path, limit_users: int | None) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_2_shallow_learned_ranker.py", "--output-dir", str(output_dir)]
    if limit_users is not None:
        parts.extend(["--limit-users", str(limit_users)])
    return " ".join(parts)


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 2 Shallow Learned Ranker",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: offline frozen pool200 shallow learned ranking; LOPO training is diagnostic-only.",
        "",
        "| candidate | lane | type | status | strict_status | promotable | diagnostic_only | reasons |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in comparison["runs"]:
        strict_status = row.get("strict_status", {})
        lines.append("| " + " | ".join([row["candidate_id"], row["lane"], row["candidate_type"], row["status"], str(strict_status.get("status")), str(strict_status.get("promotable")), str(strict_status.get("diagnostic_only")), ", ".join(strict_status.get("reasons", []))]) + " |")
    lines.extend(["", "## Blocked promotion methods", ""])
    for method in comparison["blocked_methods"]:
        lines.append(f"- `{method['name']}`: {', '.join(method['reasons'])}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
