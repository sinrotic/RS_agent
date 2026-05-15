from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_jsonl, write_json
from rs_core.recsys.evaluation import build_ranking_experiment_registry_entry, build_ranking_feature_contract, build_ranking_gpu_resource_summary, build_ranking_method_registry_entry, compare_frozen_candidate_signatures, inspect_ranking_run_artifacts
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from scripts.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift
from scripts.run_phase_1_28_lightweight_learned_ranker import LTR_FEATURE_CONFIG, _public_training_result, train_ltr_ranker

_PHASE = "phase_3_tree_lambdamart_ranker"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/phase_3_tree_lambdamart_ranker"
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
TREE_METHODS = [
    {
        "name": "sklearn_gbdt_valid_test_promotion",
        "method_family": "gbdt",
        "lane": "promotion",
        "dependency": "sklearn",
        "gpu_required": False,
        "reasons": ["tree_training_dependency_unavailable", "tree_ranker_adapter_missing", "no_independent_valid_test_training_split_for_promotion"],
    },
    {
        "name": "xgboost_lambdamart_gpu_promotion",
        "method_family": "lambdamart",
        "lane": "promotion",
        "dependency": "xgboost",
        "gpu_required": True,
        "reasons": ["tree_training_dependency_unavailable", "gpu_dependency_unavailable", "tree_ranker_adapter_missing", "no_independent_valid_test_training_split_for_promotion"],
    },
    {
        "name": "lightgbm_lambdamart_gpu_promotion",
        "method_family": "lambdamart",
        "lane": "promotion",
        "dependency": "lightgbm",
        "gpu_required": True,
        "reasons": ["tree_training_dependency_unavailable", "gpu_dependency_unavailable", "tree_ranker_adapter_missing", "no_independent_valid_test_training_split_for_promotion"],
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 3 tree/LambdaMART dependency and candidate-row export gates on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 3 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_3_tree_ranker(output_dir=output_dir, limit_users=args.limit_users)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_3_tree_ranker(output_dir: Path, limit_users: int | None = None) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users)
    dependency_status = _dependency_status()
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
    candidate_row_export = _export_tree_candidate_rows(output_dir, limit_users)
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
        "dependency_status": dependency_status,
        "candidate_row_export": candidate_row_export,
        "lanes": {
            "promotion": {"candidate_types": ["baseline", "gbdt", "lambdamart"], "promotion_eligible": True},
            "blocked": {"candidate_types": ["gbdt", "lambdamart"], "promotion_eligible": False},
        },
        "blocked_methods": _blocked_methods(dependency_status),
        "promotion_policy": {"tree_rankers_require_real_dependency": True, "stand_in_rankers_forbidden_as_promotion_evidence": True, "valid_test_training_required_for_promotion": True},
        "artifact_inspection": inspect_ranking_run_artifacts([baseline_row]) | {"phase_3_scope": "tree_lambdamart_dependency_gate_and_candidate_row_export_on_frozen_pool200"},
        "final_decision": {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "tree_lambdamart_dependencies_or_training_adapter_missing"},
        "method_registry": [_method_registry_row(baseline_row), *_blocked_method_registry_rows(dependency_status)],
        "gpu_resource_strategy": _gpu_resource_strategy(),
        "ranking_experiment_registry": [baseline_row["ranking_experiment_registry"]],
        "runs": [_public_run_row(baseline_row)],
    }


def _run_baseline(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, command_text: str) -> dict[str, Any]:
    variant_output_dir = output_dir / _BASELINE_VARIANT
    result = run_hybrid_demo(BASELINE_CONFIG, limit_users=limit_users, config_overrides={"output_dir": str(variant_output_dir), "report_path": str(variant_output_dir / "report.md"), "export_frozen_candidates": True, "strategy_name": f"{_PHASE}_{_BASELINE_VARIANT}"})
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
    return _variant_row(_BASELINE_VARIANT, "baseline", "promotion", True, False, run_id, command_text, result, metrics, frozen_rows, frozen_rows, _freeze_values(metrics), strict_status, registry_entry)


def _export_tree_candidate_rows(output_dir: Path, limit_users: int | None) -> dict[str, Any]:
    export = train_ltr_ranker(
        BASELINE_CONFIG,
        output_dir=output_dir / "tree_candidate_rows",
        limit_users=limit_users,
        config_overrides={
            "evaluation_mode": "leave_one_positive_out",
            "ltr_training": {
                "model_type": "pointwise_logistic",
                "features": LTR_FEATURE_CONFIG,
                "write_candidate_rows": True,
                "max_candidate_rows": 20000,
                "train": {"epochs": 1, "learning_rate": 0.05, "positive_weight": 1.0, "negative_weight": 1.0},
            },
        },
    )
    public = _public_training_result(export)
    public["purpose"] = "candidate_rows_for_future_real_tree_rankers"
    public["promotion_eligible"] = False
    public["diagnostic_only"] = True
    public["reasons"] = ["candidate_row_export_only", "not_a_tree_ranker_model", "lopo_training_diagnostic_only"]
    return public


def _variant_row(variant_name: str, candidate_type: str, lane: str, promotion_eligible: bool, diagnostic_only: bool, run_id: str, command_text: str, result: dict[str, Any], metrics: dict[str, Any], frozen_rows: list[dict[str, Any]], baseline_frozen_rows: list[dict[str, Any]], baseline_freeze: dict[str, Any], strict_status: dict[str, Any], registry_entry: dict[str, Any]) -> dict[str, Any]:
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
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane=row["lane"],
        state="champion",
        promotion_eligible=bool(row["promotion_eligible"]),
        diagnostic_only=bool(row["diagnostic_only"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_VARIANT,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _blocked_method_registry_rows(dependency_status: dict[str, bool]) -> list[dict[str, Any]]:
    return [
        build_ranking_method_registry_entry(
            method_id=str(method["name"]),
            method_family=str(method["method_family"]),
            lane=str(method["lane"]),
            state="blocked",
            promotion_eligible=False,
            diagnostic_only=False,
            reasons=_blocked_reasons(method, dependency_status),
            gpu_resource=build_ranking_gpu_resource_summary(
                gpu_required=bool(method["gpu_required"]),
                gpu_available=False if method["gpu_required"] else None,
                dependency_status=_dependency_label(str(method["dependency"]), dependency_status),
            ),
        )
        for method in TREE_METHODS
    ]


def _blocked_methods(dependency_status: dict[str, bool]) -> list[dict[str, Any]]:
    return [method | {"state": "blocked", "dependency_available": dependency_status[str(method["dependency"])], "reasons": _blocked_reasons(method, dependency_status)} for method in TREE_METHODS]


def _blocked_reasons(method: dict[str, Any], dependency_status: dict[str, bool]) -> list[str]:
    reasons = [f"dependency_missing:{method['dependency']}"] if not dependency_status[str(method["dependency"])] else []
    return sorted(set([*reasons, *method["reasons"]]))


def _dependency_label(dependency: str, dependency_status: dict[str, bool]) -> str:
    return f"{dependency}-available" if dependency_status[dependency] else f"{dependency}-missing"


def _dependency_status() -> dict[str, bool]:
    return {dependency: importlib.util.find_spec(dependency) is not None for dependency in ["sklearn", "xgboost", "lightgbm"]}


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
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["tree_ranker_not_trained"]}


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "reasons": ["tree_ranker_not_trained"]}


def _gpu_resource_strategy() -> dict[str, Any]:
    return {"schema_version": "ranking_gpu_strategy_v1", "current_phase_gpu_required": False, "future_gpu_required_families": ["xgboost_lambdamart", "lightgbm_lambdamart"], "unavailable_status": "blocked-gpu-unavailable", "cpu_smoke_status": "diagnostic-cpu-smoke", "promotion_gate": "real_tree_lambdamart_dependencies_and_valid_test_training_split_required"}


def _command_text(output_dir: Path, limit_users: int | None) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/run_phase_3_tree_ranker.py", "--output-dir", str(output_dir)]
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
        "# Phase 3 Tree / LambdaMART Ranker Gate",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: dependency gate and candidate-row export only; no tree/LambdaMART promotion claim.",
        "",
        "## Dependency status",
        "",
    ]
    for dependency, available in comparison["dependency_status"].items():
        lines.append(f"- `{dependency}`: {'available' if available else 'missing'}")
    lines.extend(["", "## Method registry", "", "| method | family | state | gpu_status | reasons |", "| --- | --- | --- | --- | --- |"])
    for row in comparison["method_registry"]:
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["state"], row["gpu_resource"]["status"], ", ".join(row.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
