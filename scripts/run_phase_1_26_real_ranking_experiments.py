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
from rs_core.recsys.evaluation import (
    build_ranking_experiment_registry_entry,
    build_ranking_feature_contract,
    build_ranking_gpu_resource_summary,
    build_ranking_method_registry_entry,
    compare_frozen_candidate_signatures,
    inspect_ranking_run_artifacts,
    strict_ranking_promotion_status,
)
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.ltr_training import train_ltr_ranker
from scripts.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift

_PHASE = "phase_1_26_real_ranking_experiments"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_26_real_ranking_experiments"
DEFAULT_SEED = 20260513
LTR_FEATURE_CONFIG = {"version": "ltr_v2"}
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
LEARNED_VARIANTS = [
    {
        "name": "pointwise_logistic_fine_ranker_lopo",
        "method_family": "pointwise_logistic_fine_ranker",
        "model_type": "pointwise_logistic",
        "train": {"epochs": 3, "learning_rate": 0.1, "positive_weight": 1.0, "negative_weight": 1.0},
    },
    {
        "name": "pairwise_perceptron_fine_ranker_lopo",
        "method_family": "pairwise_perceptron_fine_ranker",
        "model_type": "pairwise_perceptron",
        "train": {"epochs": 3, "learning_rate": 0.1, "negative_sample_per_positive": 3, "margin": 1.0},
    },
]
TREE_METHODS = [
    {"method_id": "sklearn_gbdt_fine_ranker", "method_family": "gbdt", "dependency": "sklearn", "gpu_required": False},
    {"method_id": "xgboost_lambdamart_fine_ranker", "method_family": "lambdamart", "dependency": "xgboost", "gpu_required": True},
    {"method_id": "lightgbm_lambdamart_fine_ranker", "method_family": "lambdamart", "dependency": "lightgbm", "gpu_required": True},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.26 real ranking experiments on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 1.26 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in training artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_1_26_real_ranking_experiments(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_1_26_real_ranking_experiments(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users, seed)
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
    rows = [baseline_row]
    training_results = {}
    for run_index, variant in enumerate(LEARNED_VARIANTS, start=1):
        training_result = _train_ltr_variant(output_dir, limit_users, variant, seed)
        training_results[str(variant["name"])] = _public_training_result(training_result) | {
            "seed": seed,
            "training_config_path": training_result["training_config_path"],
            "training_log_path": training_result["training_log_path"],
            "diagnostic_only": True,
            "promotion_eligible": False,
            "reasons": ["lopo_training_diagnostic_only", "ltr_enabled_gate_diagnostic_only", "valid_test_promotion_gate_adr_missing"],
        }
        rows.append(_run_ltr_variant(output_dir, limit_users, feature_contract, baseline_row, variant, training_result, run_id, run_index, command_text))
    public_rows = [_public_run_row(row) for row in rows]
    method_registry = [_method_registry_row(row) for row in rows] + _tree_method_registry_rows()
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "seed": seed,
        "candidate_pool_size": 200,
        "top_k": 5,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "architecture": {
            "target_layers": ["recall", "coarse_rank", "fine_rank", "rerank"],
            "current_physical_scope": "frozen_pool200_to_learned_fine_ranker_to_bounded_rerank_trace",
            "coarse_rank_current_state": "diagnostic_score_trace_only_no_pool_shrink",
        },
        "promotion_policy": {
            "frozen_pool200_required": True,
            "candidate_pool_size": 200,
            "top_k": 5,
            "ltr_enabled_variants_diagnostic_only": True,
            "gate_or_smoke_forbidden_as_real_training": True,
            "online_metrics_forbidden_as_current_offline_evidence": True,
        },
        "real_training": training_results,
        "tree_lambdamart_status": _tree_dependency_status(),
        "artifact_inspection": inspect_ranking_run_artifacts(rows) | {"phase_1_26_scope": "real_lightweight_learned_training_plus_truthful_tree_blocks_on_frozen_pool200"},
        "final_decision": {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "learned_ltr_variants_are_diagnostic_only_and_tree_rankers_are_blocked_until_real_adapter_exists"},
        "method_registry": method_registry,
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in rows],
        "runs": public_rows,
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
    return _variant_row(_BASELINE_VARIANT, "baseline", 0, run_id, command_text, result, metrics, frozen_rows, frozen_rows, _freeze_values(metrics), strict_status, registry_entry)


def _train_ltr_variant(output_dir: Path, limit_users: int | None, variant: dict[str, Any], seed: int) -> dict[str, Any]:
    variant_output_dir = output_dir / "real_training" / str(variant["name"])
    training_config = {
        "seed": seed,
        "evaluation_mode": "leave_one_positive_out",
        "model_type": variant["model_type"],
        "features": LTR_FEATURE_CONFIG,
        "write_candidate_rows": True,
        "max_candidate_rows": 10000,
        "train": variant["train"],
    }
    training_config_path = variant_output_dir / "training_config.json"
    write_json(training_config_path, training_config)
    result = train_ltr_ranker(
        BASELINE_CONFIG,
        output_dir=variant_output_dir,
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
    training_log = {
        "seed": seed,
        "variant_name": variant["name"],
        "model_type": variant["model_type"],
        "metrics_path": result["metrics_path"],
        "model_path": result["model_path"],
        "candidate_rows_path": result.get("candidate_rows_path"),
        "metrics": result["metrics"],
    }
    training_log_path = variant_output_dir / "training_log.json"
    write_json(training_log_path, training_log)
    return result | {"training_config_path": str(training_config_path), "training_log_path": str(training_log_path)}


def _run_ltr_variant(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], baseline_row: dict[str, Any], variant: dict[str, Any], training_result: dict[str, Any], run_id: str, run_index: int, command_text: str) -> dict[str, Any]:
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
    frozen_comparison = compare_frozen_candidate_signatures(baseline_row["frozen_rows"], frozen_rows)
    strict_status = strict_ranking_promotion_status(
        baseline_row["raw_metrics"],
        metrics,
        frozen_comparison,
        ltr_enabled=True,
        feature_contract_gate_summary=_training_feature_contract_gate(training_result),
        leakage_gate_summary=_training_leakage_gate(training_result),
    )
    strict_status = strict_status | {
        "promotable": False,
        "diagnostic_only": True,
        "reasons": sorted(set([*strict_status.get("reasons", []), "lopo_training_diagnostic_only", "ltr_enabled_gate_diagnostic_only", "valid_test_promotion_gate_adr_missing"])),
    }
    case_diff_path = _write_case_diff(output_dir / "case_diffs" / f"{variant_name}.json", baseline_row, result)
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:{variant_name}",
        config=_registry_config(metrics, variant_name),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=strict_status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=_training_feature_contract_gate(training_result),
        leakage_gate_summary=_training_leakage_gate(training_result),
    )
    row = _variant_row(variant_name, str(variant["method_family"]), run_index, run_id, command_text, result, metrics, frozen_rows, baseline_row["frozen_rows"], baseline_row["freeze"], strict_status, registry_entry)
    row["real_training"] = {
        "model_path": training_result["model_path"],
        "metrics_path": training_result["metrics_path"],
        "candidate_rows_path": training_result.get("candidate_rows_path"),
        "training_config_path": training_result["training_config_path"],
        "training_log_path": training_result["training_log_path"],
    }
    row["case_diff_path"] = str(case_diff_path)
    return row


def _variant_row(variant_name: str, candidate_type: str, run_index: int, run_id: str, command_text: str, result: dict[str, Any], metrics: dict[str, Any], frozen_rows: list[dict[str, Any]], baseline_frozen_rows: list[dict[str, Any]], baseline_freeze: dict[str, Any], strict_status: dict[str, Any], registry_entry: dict[str, Any]) -> dict[str, Any]:
    freeze = _freeze_values(metrics)
    status, drift = _status_and_drift(freeze, baseline_freeze)
    return {
        "run_id": run_id,
        "run_index": run_index,
        "candidate_id": variant_name,
        "candidate_type": candidate_type,
        "lane": "promotion" if variant_name == _BASELINE_VARIANT else "diagnostic",
        "promotion_eligible": variant_name == _BASELINE_VARIANT,
        "diagnostic_only": variant_name != _BASELINE_VARIANT,
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
    is_baseline = row["candidate_id"] == _BASELINE_VARIANT
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane="promotion" if is_baseline else "diagnostic",
        state="champion" if is_baseline else "diagnostic",
        promotion_eligible=bool(row["promotion_eligible"]),
        diagnostic_only=bool(row["diagnostic_only"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_VARIANT if is_baseline else None,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _tree_method_registry_rows() -> list[dict[str, Any]]:
    rows = []
    dependency_status = _tree_dependency_status()
    for method in TREE_METHODS:
        dependency = str(method["dependency"])
        available = bool(dependency_status[dependency]["available"])
        reasons = ["real_tree_serving_adapter_missing", "not_run_as_gate_or_smoke", "blocked_until_candidate_level_tree_model_adapter_exists"]
        if not available:
            reasons.append("dependency_missing")
        if method["gpu_required"]:
            reasons.append("gpu_required_not_verified")
        rows.append(
            build_ranking_method_registry_entry(
                method_id=str(method["method_id"]),
                method_family=str(method["method_family"]),
                lane="blocked",
                state="blocked",
                promotion_eligible=False,
                diagnostic_only=False,
                reasons=reasons,
                gpu_resource=build_ranking_gpu_resource_summary(gpu_required=bool(method["gpu_required"]), gpu_available=None, dependency_status="available" if available else "missing"),
            )
        )
    return rows


def _tree_dependency_status() -> dict[str, dict[str, Any]]:
    return {
        dependency: {"available": importlib.util.find_spec(dependency) is not None, "checked_by": "importlib.util.find_spec"}
        for dependency in sorted({str(method["dependency"]) for method in TREE_METHODS})
    }


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


def _not_applicable_feature_contract_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["ltr_model_disabled"]}


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "reasons": ["ltr_model_disabled"]}


def _baseline_status() -> dict[str, Any]:
    return {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}}


def _public_training_result(training_result: dict[str, Any]) -> dict[str, Any]:
    return {"model_path": training_result["model_path"], "metrics_path": training_result["metrics_path"], "candidate_rows_path": training_result.get("candidate_rows_path"), "metrics": training_result["metrics"]}


def _write_case_diff(path: Path, baseline_row: dict[str, Any], variant_result: dict[str, Any]) -> Path:
    baseline_cases = _cases_by_key(read_jsonl(baseline_row["ranking_cases_path"]))
    variant_cases = _cases_by_key(read_jsonl(variant_result["ranking_cases_path"]))
    changed = []
    for key in sorted(set(baseline_cases) | set(variant_cases)):
        baseline_case = baseline_cases.get(key, {})
        variant_case = variant_cases.get(key, {})
        if baseline_case.get("target_rank") != variant_case.get("target_rank") or baseline_case.get("is_topk_hit") != variant_case.get("is_topk_hit"):
            changed.append({
                "user_id": key[0],
                "target_item": key[1],
                "baseline_rank": baseline_case.get("target_rank"),
                "variant_rank": variant_case.get("target_rank"),
                "baseline_topk_hit": baseline_case.get("is_topk_hit"),
                "variant_topk_hit": variant_case.get("is_topk_hit"),
            })
    payload = {"schema_version": "ranking_case_diff_v1", "baseline": baseline_row["candidate_id"], "changed_case_count": len(changed), "changed_cases": changed[:100]}
    write_json(path, payload)
    return path


def _cases_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(row.get("user_id", "")), str(row.get("target_item", ""))): row for row in rows if row.get("user_id") and row.get("target_item")}


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _command_text(output_dir: Path, limit_users: int | None, seed: int = DEFAULT_SEED) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/run_phase_1_26_real_ranking_experiments.py", "--output-dir", str(output_dir), "--seed", str(seed)]
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
        "# Phase 1.26 Real Ranking Experiments",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: frozen pool200 → learned fine ranker → bounded rerank trace; coarse rank is diagnostic-only and does not shrink the pool.",
        "- Tree/LambdaMART entries are blocked unless real dependency, GPU, and candidate-level adapter requirements are satisfied.",
        "",
        "## Runs",
        "",
        "| candidate | state | hit_rate_at_k | ndcg_at_k | mrr_at_k | frozen_match |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in comparison["runs"]:
        metrics = row["metrics"]
        lines.append("| " + " | ".join([row["candidate_id"], row["strict_status"]["status"], str(metrics.get("hit_rate_at_k")), str(metrics.get("ndcg_at_k")), str(metrics.get("mrr_at_k")), str(row.get("frozen_candidate_match"))]) + " |")
    lines.extend(["", "## Method registry", "", "| method | family | lane | state | gpu_status | reasons |", "| --- | --- | --- | --- | --- | --- |"])
    for row in comparison["method_registry"]:
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["lane"], row["state"], row["gpu_resource"]["status"], ", ".join(row.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
