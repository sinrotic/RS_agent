from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_jsonl, write_json
from rs_core.offline.evaluation.ranking import (
    build_ranking_feature_contract,
    inspect_ranking_run_artifacts,
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
from rs_lab.experiments.ranking.run_phase_1_26_real_ranking_experiments import (
    LTR_FEATURE_CONFIG,
    _not_applicable_feature_contract_gate,
    _not_applicable_leakage_gate,
    _read_frozen_rows,
)
from rs_lab.experiments.ranking.run_phase_2_fine_rank_algorithm_batch import PHYSICAL_PIPELINE_OVERRIDE

_PHASE = "phase_3_tree_ranking_experiments"
_BASELINE_METHOD_ID = "same_run_pool200_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_3_tree_ranking_experiments"
DEFAULT_SEED = 20260513
TREE_DIAGNOSTIC_BOUNDARY = "tree_training_diagnostic_only_no_serving_adapter_or_valid_test_promotion_gate"
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 3 tree/GBDT/LambdaMART diagnostics on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 3 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in training artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_3_tree_ranking_experiments(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_3_tree_ranking_experiments(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users, seed)
    method_specs = build_method_specs()
    dependency_checks = _dependency_checks(method_specs)
    gpu_check = _gpu_check()

    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, method_specs[0], run_id, command_text)
    candidate_rows_result = _prepare_candidate_rows(output_dir, limit_users, seed)
    sklearn_row = _run_sklearn_gbdt_diagnostic(
        output_dir,
        method_specs[1],
        baseline_row,
        candidate_rows_result,
        dependency_checks[method_specs[1].method_id],
        run_id,
        command_text,
        seed,
    )
    blocked_rows = _blocked_lambdamart_rows(method_specs[2:], run_id, command_text, dependency_checks, gpu_check)
    runnable_rows = [baseline_row]
    if sklearn_row["run_kind"] == "diagnostic":
        runnable_rows.append(sklearn_row)
        sklearn_public_row = public_ranking_run_row(sklearn_row)
    else:
        sklearn_public_row = sklearn_row
    runs = [public_ranking_run_row(baseline_row), sklearn_public_row, *blocked_rows]
    method_registry = [_method_registry_entry(row, dependency_checks, gpu_check) for row in runnable_rows]
    method_registry.extend(row["method_registry_entry"] for row in blocked_rows)
    ranking_registry = [row["ranking_experiment_registry"] for row in runnable_rows if "ranking_experiment_registry" in row]

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
        "dependency_checks": dependency_checks,
        "gpu_check": gpu_check,
        "method_registry": method_registry,
        "ranking_experiment_registry": ranking_registry,
        "ranking_experiment_registry_note": "sklearn GBDT is trained on candidate-level rows but not served into rank_candidates until a verified adapter exists; LambdaMART rows stay blocked without verified GPU/objective/adapter.",
        "candidate_training_data": candidate_rows_result,
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
        "training_artifact_inspection": _training_artifact_inspection(candidate_rows_result, sklearn_row),
        "promotion_boundary": _promotion_boundary(),
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
            method_id="sklearn_gbdt_pointwise_fine_rank_diagnostic",
            method_family="tree_gbdt",
            stage_target="fine",
            requires_training=True,
            requires_gpu=False,
            dependency="sklearn",
            promotion_lane="phase_3_tree_diagnostic_only",
            blocked_recovery_condition="candidate-level rows, sklearn dependency, serving adapter, and full valid/test promotion gate are required before challenger promotion",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={"tree_objective": "pointwise_binary_relevance", "diagnostic_boundary": TREE_DIAGNOSTIC_BOUNDARY, "deterministic_stand_in": False},
        ),
        RankingMethodSpec(
            method_id="xgboost_lambdamart_fine_rank_blocked",
            method_family="lambdamart",
            stage_target="fine",
            requires_training=True,
            requires_gpu=True,
            dependency="xgboost",
            promotion_lane="blocked",
            blocked_recovery_condition="xgboost dependency, verified GPU, rank:ndcg objective, candidate group labels, serving adapter, and valid/test promotion gate are all required",
            promotion_eligible=False,
            diagnostic_only=False,
            metadata={"tree_objective": "rank:ndcg", "deterministic_stand_in": False},
        ),
        RankingMethodSpec(
            method_id="lightgbm_lambdamart_fine_rank_blocked",
            method_family="lambdamart",
            stage_target="fine",
            requires_training=True,
            requires_gpu=True,
            dependency="lightgbm",
            promotion_lane="blocked",
            blocked_recovery_condition="lightgbm dependency, verified GPU, lambdarank objective, candidate group labels, serving adapter, and valid/test promotion gate are all required",
            promotion_eligible=False,
            diagnostic_only=False,
            metadata={"tree_objective": "lambdarank", "deterministic_stand_in": False},
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


def _prepare_candidate_rows(output_dir: Path, limit_users: int | None, seed: int) -> dict[str, Any]:
    training_dir = output_dir / "candidate_training_data"
    training_config = {
        "phase": _PHASE,
        "seed": seed,
        "config_path": str(BASELINE_CONFIG),
        "evaluation_mode": "leave_one_positive_out",
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "ltr_training": {
            "model_type": "pointwise_logistic",
            "features": LTR_FEATURE_CONFIG,
            "write_candidate_rows": True,
            "max_candidate_rows": 20000,
            "train": {"epochs": 1, "learning_rate": 0.05, "positive_weight": 1.0, "negative_weight": 1.0},
        },
    }
    write_json(training_dir / "training_config.json", training_config)
    result = train_ltr_ranker(
        BASELINE_CONFIG,
        output_dir=training_dir,
        limit_users=limit_users,
        config_overrides={
            "evaluation_mode": "leave_one_positive_out",
            "ltr_training": training_config["ltr_training"],
        },
    )
    rows = read_jsonl(result["candidate_rows_path"]) if result.get("candidate_rows_path") else []
    labels = Counter(int(row.get("label", 0)) for row in rows)
    groups = Counter(str(row.get("user_id", "")) for row in rows)
    summary = {
        "schema_version": "phase_3_candidate_training_data_v1",
        "status": "PASS" if rows and labels.get(1, 0) > 0 and labels.get(0, 0) > 0 else "BLOCKED",
        "seed": seed,
        "evaluation_mode": "leave_one_positive_out",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "reasons": ["lopo_training_diagnostic_only", "candidate_rows_for_tree_training_only", "valid_test_promotion_gate_missing"],
        "candidate_rows_path": result.get("candidate_rows_path"),
        "metrics_path": result["metrics_path"],
        "model_path": result["model_path"],
        "training_config_path": str(training_dir / "training_config.json"),
        "row_count": len(rows),
        "positive_rows": labels.get(1, 0),
        "negative_rows": labels.get(0, 0),
        "group_count": len(groups),
        "min_group_size": min(groups.values()) if groups else 0,
        "max_group_size": max(groups.values()) if groups else 0,
        "feature_contract_gate": result["metrics"].get("feature_contract_gate"),
        "leakage_gate": result["metrics"].get("leakage_gate"),
    }
    write_json(training_dir / "candidate_training_data_summary.json", summary)
    summary["summary_path"] = str(training_dir / "candidate_training_data_summary.json")
    return summary


def _run_sklearn_gbdt_diagnostic(
    output_dir: Path,
    method_spec: RankingMethodSpec,
    baseline_row: dict[str, Any],
    candidate_rows_result: dict[str, Any],
    dependency_check: dict[str, Any],
    run_id: str,
    command_text: str,
    seed: int,
) -> dict[str, Any]:
    if dependency_check.get("available") is not True:
        return build_blocked_ranking_run_row(
            run_id=f"{_PHASE}:{run_id}",
            run_index=1,
            method_spec=method_spec,
            dependency_available=dependency_check.get("available"),
            gpu_available=None,
            blocked_reason=["sklearn_dependency_missing_or_unverified", "candidate_level_tree_training_not_run"],
            command_text=command_text,
        )
    if candidate_rows_result.get("status") != "PASS" or not candidate_rows_result.get("candidate_rows_path"):
        return build_blocked_ranking_run_row(
            run_id=f"{_PHASE}:{run_id}",
            run_index=1,
            method_spec=method_spec,
            dependency_available=True,
            gpu_available=None,
            blocked_reason=["candidate_rows_missing_or_single_class", "candidate_level_tree_training_not_run"],
            command_text=command_text,
        )
    training_result = _train_sklearn_gbdt(output_dir / "tree_training" / method_spec.method_id, Path(candidate_rows_result["candidate_rows_path"]), seed)
    status = {
        "status": "PARTIAL diagnostic-only",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": sorted(set([*training_result["reasons"], TREE_DIAGNOSTIC_BOUNDARY])),
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
        metrics={key: baseline_row["raw_metrics"].get(key) for key in METRIC_FIELDS},
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
            "diagnostic_source_metrics_path": baseline_row.get("metrics_path"),
            "diagnostic_source_frozen_candidates_path": baseline_row.get("frozen_candidates_path"),
            "tree_training": training_result,
            "tree_training_metrics_path": training_result.get("metrics_path"),
            "tree_training_model_path": training_result.get("model_path"),
            "adapter_execution": "not_run_no_verified_tree_serving_adapter",
            "promotion_evidence_claim": "none",
        },
        feature_contract=build_ranking_feature_contract(),
        feature_contract_gate_summary=candidate_rows_result.get("feature_contract_gate"),
        leakage_gate_summary=candidate_rows_result.get("leakage_gate"),
        command_text=command_text,
    )
    row["raw_metrics"] = baseline_row["raw_metrics"]
    row["frozen_rows"] = baseline_row["frozen_rows"]
    row["tree_training"] = training_result
    return row


def _train_sklearn_gbdt(output_dir: Path, rows_path: Path, seed: int) -> dict[str, Any]:
    from sklearn.ensemble import GradientBoostingClassifier

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [row for row in read_jsonl(rows_path) if row.get("label") in {0, 1}]
    feature_names = sorted({name for row in rows for name in (row.get("features") or {})})
    if len({int(row["label"]) for row in rows}) < 2:
        result = {"state": "blocked", "status": "blocked", "promotion_eligible": False, "diagnostic_only": False, "reasons": ["training_rows_need_both_classes"], "candidate_rows_path": str(rows_path)}
        write_json(output_dir / "training_log.json", result)
        return result
    train_rows, valid_rows, test_rows = _split_rows_by_user(rows, seed)
    model = GradientBoostingClassifier(random_state=seed, n_estimators=30, max_depth=2)
    model.fit(_matrix(train_rows, feature_names), [int(row["label"]) for row in train_rows])
    model_path = output_dir / "sklearn_gbdt_model.pkl"
    with model_path.open("wb") as file:
        pickle.dump({"model": model, "feature_names": feature_names, "seed": seed}, file)
    metrics = {
        "schema_version": "phase_3_tree_training_metrics_v1",
        "model_type": "sklearn_gradient_boosting_classifier",
        "objective": "pointwise_binary_relevance",
        "seed": seed,
        "candidate_rows_path": str(rows_path),
        "feature_count": len(feature_names),
        "group_count": len({str(row.get("user_id", "")) for row in rows}),
        "train": _classification_metrics(model, train_rows, feature_names),
        "valid": _classification_metrics(model, valid_rows, feature_names),
        "test": _classification_metrics(model, test_rows, feature_names),
        "promotion_eligible": False,
        "diagnostic_only": True,
        "reasons": ["sklearn_gbdt_real_training_complete", "tree_serving_adapter_missing", "valid_test_promotion_gate_missing", "lopo_training_diagnostic_only"],
    }
    config = {"model_type": "sklearn_gradient_boosting_classifier", "objective": "pointwise_binary_relevance", "seed": seed, "n_estimators": 30, "max_depth": 2, "feature_names": feature_names}
    metrics_path = output_dir / "metrics.json"
    config_path = output_dir / "training_config.json"
    log_path = output_dir / "training_log.json"
    write_json(config_path, config)
    write_json(metrics_path, metrics)
    write_json(log_path, metrics | {"state": "diagnostic", "status": "diagnostic", "model_path": str(model_path), "metrics_path": str(metrics_path), "training_config_path": str(config_path)})
    return {
        "state": "diagnostic",
        "status": "diagnostic",
        "model_path": str(model_path),
        "metrics_path": str(metrics_path),
        "training_config_path": str(config_path),
        "training_log_path": str(log_path),
        "candidate_rows_path": str(rows_path),
        "metrics": metrics,
        "promotion_eligible": False,
        "diagnostic_only": True,
        "reasons": metrics["reasons"],
    }


def _blocked_lambdamart_rows(
    method_specs: list[RankingMethodSpec],
    run_id: str,
    command_text: str,
    dependency_checks: dict[str, dict[str, Any]],
    gpu_check: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for offset, spec in enumerate(method_specs, start=2):
        dependency_available = dependency_checks.get(spec.method_id, {}).get("available")
        gpu_available = gpu_check.get("available") if spec.requires_gpu else None
        blocked_reason = ["lambda_mart_serving_adapter_missing", "valid_test_promotion_gate_missing", "no_deterministic_stand_in"]
        if spec.requires_gpu and gpu_available is not True:
            blocked_reason.append("gpu_required_not_verified")
        rows.append(
            build_blocked_ranking_run_row(
                run_id=f"{_PHASE}:{run_id}",
                run_index=offset,
                method_spec=spec,
                dependency_available=dependency_available,
                gpu_available=gpu_available,
                blocked_reason=blocked_reason,
                command_text=command_text,
            )
        )
    return rows


def _split_rows_by_user(rows: list[dict[str, Any]], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=lambda item: (str(item.get("user_id", "")), str(item.get("item_id", "")))):
        grouped.setdefault(str(row.get("user_id", "")), []).append(row)
    buckets = {"train": [], "valid": [], "test": []}
    for index, user_id in enumerate(sorted(grouped)):
        bucket = (index + seed) % 10
        target = "train" if bucket < 7 else "valid" if bucket < 9 else "test"
        buckets[target].extend(grouped[user_id])
    if len({int(row["label"]) for row in buckets["train"]}) < 2:
        buckets["train"] = rows
    return buckets["train"], buckets["valid"], buckets["test"]


def _classification_metrics(model: Any, rows: list[dict[str, Any]], feature_names: list[str]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "positive_rows": 0, "negative_rows": 0, "accuracy": None, "average_probability": None}
    labels = [int(row["label"]) for row in rows]
    probabilities = [float(pair[1]) for pair in model.predict_proba(_matrix(rows, feature_names))]
    predictions = [1 if value >= 0.5 else 0 for value in probabilities]
    correct = sum(int(prediction == label) for prediction, label in zip(predictions, labels, strict=True))
    return {
        "rows": len(rows),
        "positive_rows": sum(labels),
        "negative_rows": len(labels) - sum(labels),
        "accuracy": round(correct / len(labels), 6),
        "average_probability": round(sum(probabilities) / len(probabilities), 6),
    }


def _matrix(rows: list[dict[str, Any]], feature_names: list[str]) -> list[list[float]]:
    return [[float((row.get("features") or {}).get(name, 0.0) or 0.0) for name in feature_names] for row in rows]


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


def _method_registry_entry(row: dict[str, Any], dependency_checks: dict[str, dict[str, Any]], gpu_check: dict[str, Any]) -> dict[str, Any]:
    method_payload = {key: value for key, value in row["method_spec"].items() if key != "schema_version"}
    spec = RankingMethodSpec(**method_payload)
    dependency_status = dependency_checks.get(spec.method_id, {}).get("status", "not_checked")
    return build_ranking_method_registry_entry_from_spec(
        spec,
        run_kind=str(row["run_kind"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_METHOD_ID if row["run_kind"] == "baseline" else None,
        challenger_of=_BASELINE_METHOD_ID if row["run_kind"] != "baseline" else None,
        gpu_available=gpu_check.get("available") if spec.requires_gpu else None,
        dependency_status=dependency_status,
    )


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or REQUIRED_CANDIDATE_POOL_SIZE
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or REQUIRED_TOP_K
    config["physical_ranking_pipeline"] = PHYSICAL_PIPELINE_OVERRIDE
    config["export_ranking_stage_artifacts"] = True
    return config


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


def _training_artifact_inspection(candidate_rows_result: dict[str, Any], sklearn_row: dict[str, Any]) -> dict[str, Any]:
    required_paths = ["candidate_rows_path", "metrics_path", "training_config_path", "summary_path"]
    candidate_missing = [key for key in required_paths if not candidate_rows_result.get(key) or not Path(str(candidate_rows_result[key])).exists()]
    sklearn_training = sklearn_row.get("tree_training") or {}
    sklearn_required = ["model_path", "metrics_path", "training_config_path", "training_log_path", "candidate_rows_path"]
    sklearn_missing = [key for key in sklearn_required if not sklearn_training.get(key) or not Path(str(sklearn_training[key])).exists()]
    blocked = sklearn_row.get("run_kind") == "blocked"
    status = "PASS" if not candidate_missing and (blocked or not sklearn_missing) else "INVALID"
    return {
        "schema_version": "phase_3_training_artifact_inspection_v1",
        "status": status,
        "candidate_training_data_missing": candidate_missing,
        "sklearn_training_missing": sklearn_missing,
        "sklearn_blocked": blocked,
    }


def _promotion_boundary() -> dict[str, Any]:
    return {
        "frozen_pool200_required": True,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "recall_semantics_changed": False,
        "merge_for_user_changed": False,
        "sklearn_gbdt_training_diagnostic_only": True,
        "lambda_mart_requires_verified_dependency_gpu_objective_adapter": True,
        "lopo_gate_smoke_stage_trace_training_loss_online_metrics_not_promotion_evidence": True,
        "online_metrics_forbidden_as_current_offline_evidence": True,
        "no_deterministic_stand_in": True,
    }


def _command_text(output_dir: Path, limit_users: int | None, seed: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_3_tree_ranking_experiments.py", "--output-dir", str(output_dir), "--seed", str(seed)]
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
        "# Phase 3 Tree Ranking Experiments",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Seed: `{comparison['seed']}`",
        "- Scope: frozen pool200 / top_k=5; recall semantics and `merge_for_user()` are unchanged.",
        "- Promotion boundary: sklearn GBDT is real diagnostic training only; LambdaMART remains blocked without verified GPU/objective/adapter and valid/test promotion evidence.",
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
    lines.extend(["", "## Dependency checks", ""])
    for method_id, check in comparison["dependency_checks"].items():
        lines.append(f"- `{method_id}`: {check['status']} ({check['dependency']})")
    lines.extend(["", "## Candidate training data", ""])
    training = comparison["candidate_training_data"]
    lines.append(f"- Status: `{training['status']}`")
    lines.append(f"- Rows: `{training['row_count']}`; positives: `{training['positive_rows']}`; negatives: `{training['negative_rows']}`; groups: `{training['group_count']}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
