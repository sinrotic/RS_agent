from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
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

_PHASE = "phase_1_26_real_learned_gbdt_ranker"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_26_real_learned_gbdt_ranker"
DEFAULT_SEED = 20260513
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
LEARNED_VARIANTS = [
    {
        "name": "pointwise_logistic_lopo_diagnostic",
        "model_type": "pointwise_logistic",
        "method_family": "pointwise_logistic",
        "train": {"epochs": 3, "learning_rate": 0.1, "positive_weight": 1.0, "negative_weight": 1.0},
    },
    {
        "name": "pairwise_perceptron_lopo_diagnostic",
        "model_type": "pairwise_perceptron",
        "method_family": "pairwise_perceptron",
        "train": {"epochs": 3, "learning_rate": 0.1, "negative_sample_per_positive": 3, "margin": 1.0},
    },
]
TREE_METHODS = [
    {"name": "sklearn_gbdt_diagnostic", "method_family": "gbdt", "lane": "diagnostic", "dependency": "sklearn", "gpu_required": False},
    {"name": "xgboost_lambdamart_gpu", "method_family": "lambdamart", "lane": "blocked", "dependency": "xgboost", "gpu_required": True},
    {"name": "lightgbm_lambdamart_gpu", "method_family": "lambdamart", "lane": "blocked", "dependency": "lightgbm", "gpu_required": True},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.26 real learned/GBDT diagnostics on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 1.26 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic training seed recorded in artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_1_26_real_learned_gbdt_ranker(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_1_26_real_learned_gbdt_ranker(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users, seed)
    dependency_status = _dependency_status()
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
    run_rows = [baseline_row]
    learned_training: dict[str, Any] = {}
    for variant in LEARNED_VARIANTS:
        training_result = _train_ltr_variant(output_dir, limit_users, variant, seed)
        variant_name = str(variant["name"])
        learned_training[variant_name] = _public_training_result(training_result) | {
            "seed": seed,
            "training_config_path": training_result["training_config_path"],
            "training_log_path": training_result["training_log_path"],
            "diagnostic_only": True,
            "promotion_eligible": False,
            "reasons": ["lopo_training_diagnostic_only", "ltr_enabled_gate_diagnostic_only", "valid_test_promotion_gate_adr_missing"],
        }
        run_rows.append(_run_ltr_variant(output_dir, limit_users, feature_contract, run_id, command_text, baseline_row, variant, training_result))
    tree_training = _run_tree_training(output_dir, learned_training, dependency_status, seed)
    method_registry = [_method_registry_row(row) for row in run_rows]
    method_registry.extend(_tree_method_registry_rows(tree_training, dependency_status))
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "seed": seed,
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
        "lanes": {
            "promotion": {"candidate_types": ["baseline"], "promotion_eligible": True},
            "diagnostic": {"candidate_types": ["pointwise_logistic", "pairwise_perceptron", "sklearn_gbdt"], "promotion_eligible": False},
            "blocked": {"candidate_types": ["xgboost_lambdamart", "lightgbm_lambdamart"], "promotion_eligible": False},
        },
        "promotion_policy": {
            "candidate_pool_regeneration_forbidden": True,
            "frozen_pool_contract": {"candidate_pool_size": 200, "top_k": 5},
            "learned_ltr_enabled_gate": "diagnostic_only_until_gate_adr_exists",
            "valid_test_training_required_for_promotion": True,
            "tree_serving_adapter_required_for_promotion": True,
        },
        "artifact_inspection": inspect_ranking_run_artifacts(run_rows) | {"phase_1_26_scope": "real_learned_training_and_tree_diagnostics_on_frozen_pool200"},
        "final_decision": {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "learned_ltr_and_tree_rankers_are_diagnostic_or_blocked_without_valid_promotion_gate"},
        "learned_training": learned_training,
        "tree_training": tree_training,
        "method_registry": method_registry,
        "gpu_resource_strategy": _gpu_resource_strategy(dependency_status),
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in run_rows],
        "runs": [_public_run_row(row) for row in run_rows],
    }


def _train_ltr_variant(output_dir: Path, limit_users: int | None, variant: dict[str, Any], seed: int) -> dict[str, Any]:
    variant_name = str(variant["name"])
    training_dir = output_dir / "learned_training" / variant_name
    training_dir.mkdir(parents=True, exist_ok=True)
    training_config = {
        "phase": _PHASE,
        "variant": variant_name,
        "seed": seed,
        "config_path": str(BASELINE_CONFIG),
        "evaluation_mode": "leave_one_positive_out",
        "candidate_pool_size": 200,
        "top_k": 5,
        "ltr_training": {"model_type": variant["model_type"], "features": LTR_FEATURE_CONFIG, "write_candidate_rows": True, "max_candidate_rows": 20000, "train": variant["train"]},
    }
    config_path = training_dir / "training_config.json"
    write_json(config_path, training_config)
    training_result = train_ltr_ranker(
        BASELINE_CONFIG,
        output_dir=training_dir,
        limit_users=limit_users,
        config_overrides={
            "evaluation_mode": "leave_one_positive_out",
            "ltr_training": training_config["ltr_training"],
        },
    )
    training_log = {
        "phase": _PHASE,
        "variant": variant_name,
        "seed": seed,
        "model_path": training_result["model_path"],
        "metrics_path": training_result["metrics_path"],
        "candidate_rows_path": training_result.get("candidate_rows_path"),
        "metrics": training_result["metrics"],
        "status": "diagnostic",
        "reasons": ["lopo_training_diagnostic_only", "valid_test_promotion_gate_adr_missing"],
    }
    log_path = training_dir / "training_log.json"
    write_json(log_path, training_log)
    return training_result | {"training_config_path": str(config_path), "training_log_path": str(log_path), "seed": seed}


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
    return _variant_row(_BASELINE_VARIANT, "baseline", "promotion", True, False, run_id, command_text, result, metrics, frozen_rows, frozen_rows, _freeze_values(metrics), _baseline_status(), registry_entry)


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
    strict_status = strict_status | {
        "promotable": False,
        "diagnostic_only": True,
        "reasons": sorted(set([*strict_status.get("reasons", []), "lopo_training_diagnostic_only", "ltr_enabled_gate_diagnostic_only", "valid_test_promotion_gate_adr_missing"])),
    }
    if strict_status.get("status") == "Promote":
        strict_status = strict_status | {"status": "PARTIAL diagnostic-only"}
    status, drift = _status_and_drift(_freeze_values(metrics), baseline_row["freeze"])
    if status == "INVALID" and "freeze_metric_drift" not in strict_status["reasons"]:
        strict_status = strict_status | {"status": "INVALID/STOP", "reasons": [*strict_status["reasons"], "freeze_metric_drift"]}
    case_diff_path = _write_case_diff(output_dir / "case_diffs" / f"{variant_name}.json", baseline_row, result)
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
    row = _variant_row(variant_name, str(variant["method_family"]), "diagnostic", False, True, run_id, command_text, result, metrics, frozen_rows, baseline_row["frozen_rows"], baseline_row["freeze"], strict_status, registry_entry)
    row["status"] = status
    row["drift"] = drift
    row["ltr_training"] = {"model_path": training_result["model_path"], "metrics_path": training_result["metrics_path"], "candidate_rows_path": training_result.get("candidate_rows_path"), "training_config_path": training_result["training_config_path"], "training_log_path": training_result["training_log_path"], "seed": training_result["seed"]}
    row["case_diff_path"] = str(case_diff_path)
    return row


def _run_tree_training(output_dir: Path, learned_training: dict[str, Any], dependency_status: dict[str, bool], seed: int) -> dict[str, Any]:
    rows_path = _first_candidate_rows_path(learned_training)
    results: dict[str, Any] = {}
    for method in TREE_METHODS:
        method_name = str(method["name"])
        if method["gpu_required"]:
            results[method_name] = _blocked_tree_result(method, dependency_status, ["gpu_unavailable", "tree_serving_adapter_missing", "valid_test_promotion_gate_adr_missing"])
            continue
        if not dependency_status[str(method["dependency"])] or not rows_path:
            reasons = []
            if not dependency_status[str(method["dependency"])]:
                reasons.append(f"dependency_missing:{method['dependency']}")
            if not rows_path:
                reasons.append("candidate_rows_missing")
            results[method_name] = _blocked_tree_result(method, dependency_status, [*reasons, "tree_serving_adapter_missing"])
            continue
        results[method_name] = _train_sklearn_gbdt(output_dir / "tree_training" / method_name, Path(rows_path), seed)
    return results


def _train_sklearn_gbdt(output_dir: Path, rows_path: Path, seed: int) -> dict[str, Any]:
    from sklearn.ensemble import GradientBoostingClassifier

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(rows_path)
    feature_names = sorted({name for row in rows for name in (row.get("features") or {})})
    usable_rows = [row for row in rows if row.get("label") in {0, 1}]
    if len({int(row["label"]) for row in usable_rows}) < 2:
        result = {"state": "blocked", "status": "blocked", "promotion_eligible": False, "diagnostic_only": False, "reasons": ["training_rows_need_both_classes"], "candidate_rows_path": str(rows_path)}
        write_json(output_dir / "training_log.json", result)
        return result
    train_rows, valid_rows, test_rows = _split_rows(usable_rows, seed)
    model = GradientBoostingClassifier(random_state=seed, n_estimators=30, max_depth=2)
    model.fit(_matrix(train_rows, feature_names), [int(row["label"]) for row in train_rows])
    model_path = output_dir / "sklearn_gbdt_model.pkl"
    with model_path.open("wb") as file:
        pickle.dump({"model": model, "feature_names": feature_names, "seed": seed}, file)
    metrics = {
        "schema_version": "tree_training_metrics_v1",
        "model_type": "sklearn_gradient_boosting_classifier",
        "seed": seed,
        "feature_count": len(feature_names),
        "candidate_rows_path": str(rows_path),
        "train": _classification_metrics(model, train_rows, feature_names),
        "valid": _classification_metrics(model, valid_rows, feature_names),
        "test": _classification_metrics(model, test_rows, feature_names),
        "promotion_eligible": False,
        "diagnostic_only": True,
        "reasons": ["tree_serving_adapter_missing", "valid_test_promotion_gate_adr_missing", "diagnostic_tree_training_only"],
    }
    metrics_path = output_dir / "metrics.json"
    config_path = output_dir / "training_config.json"
    log_path = output_dir / "training_log.json"
    write_json(config_path, {"model_type": "sklearn_gradient_boosting_classifier", "seed": seed, "n_estimators": 30, "max_depth": 2, "feature_names": feature_names})
    write_json(metrics_path, metrics)
    write_json(log_path, metrics | {"model_path": str(model_path), "metrics_path": str(metrics_path), "training_config_path": str(config_path), "state": "diagnostic", "status": "diagnostic"})
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


def _split_rows(rows: list[dict[str, Any]], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: (str(row.get("user_id", "")), str(row.get("item_id", ""))))
    buckets = {"train": [], "valid": [], "test": []}
    for index, row in enumerate(ordered):
        bucket = (index + seed) % 10
        if bucket < 7:
            buckets["train"].append(row)
        elif bucket < 9:
            buckets["valid"].append(row)
        else:
            buckets["test"].append(row)
    if len({int(row["label"]) for row in buckets["train"]}) < 2:
        buckets["train"] = ordered
    return buckets["train"], buckets["valid"], buckets["test"]


def _classification_metrics(model: Any, rows: list[dict[str, Any]], feature_names: list[str]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "positive_rows": 0, "accuracy": None, "average_probability": None}
    labels = [int(row["label"]) for row in rows]
    probabilities = [float(pair[1]) for pair in model.predict_proba(_matrix(rows, feature_names))]
    predictions = [1 if value >= 0.5 else 0 for value in probabilities]
    correct = sum(int(pred == label) for pred, label in zip(predictions, labels, strict=True))
    return {
        "rows": len(rows),
        "positive_rows": sum(labels),
        "negative_rows": len(labels) - sum(labels),
        "accuracy": round(correct / len(labels), 6),
        "average_probability": round(sum(probabilities) / len(probabilities), 6),
    }


def _matrix(rows: list[dict[str, Any]], feature_names: list[str]) -> list[list[float]]:
    return [[float((row.get("features") or {}).get(name, 0.0) or 0.0) for name in feature_names] for row in rows]


def _blocked_tree_result(method: dict[str, Any], dependency_status: dict[str, bool], reasons: list[str]) -> dict[str, Any]:
    dependency = str(method["dependency"])
    return {
        "state": "blocked",
        "status": "blocked-gpu-unavailable" if method["gpu_required"] else "blocked",
        "dependency": dependency,
        "dependency_available": dependency_status[dependency],
        "gpu_required": bool(method["gpu_required"]),
        "promotion_eligible": False,
        "diagnostic_only": False,
        "reasons": sorted(set(reasons)),
        "minimal_dependency_list": [dependency, "candidate_rows", "tree_serving_adapter", "valid_test_promotion_gate_adr"],
    }


def _tree_method_registry_rows(tree_training: dict[str, Any], dependency_status: dict[str, bool]) -> list[dict[str, Any]]:
    rows = []
    for method in TREE_METHODS:
        method_name = str(method["name"])
        result = tree_training[method_name]
        dependency = str(method["dependency"])
        rows.append(
            build_ranking_method_registry_entry(
                method_id=method_name,
                method_family=str(method["method_family"]),
                lane=str(method["lane"]),
                state=str(result["state"]),
                promotion_eligible=bool(result["promotion_eligible"]),
                diagnostic_only=bool(result["diagnostic_only"]),
                reasons=list(result.get("reasons", [])),
                gpu_resource=build_ranking_gpu_resource_summary(
                    gpu_required=bool(method["gpu_required"]),
                    gpu_available=False if method["gpu_required"] else None,
                    dependency_status=f"{dependency}-available" if dependency_status[dependency] else f"{dependency}-missing",
                ),
            )
        )
    return rows


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


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _write_case_diff(path: Path, baseline_row: dict[str, Any], variant_result: dict[str, Any]) -> Path:
    baseline_cases = _cases_by_key(read_jsonl(baseline_row["ranking_cases_path"]))
    variant_cases = _cases_by_key(read_jsonl(variant_result["ranking_cases_path"]))
    changed = []
    for key in sorted(set(baseline_cases) | set(variant_cases)):
        baseline_case = baseline_cases.get(key, {})
        variant_case = variant_cases.get(key, {})
        if baseline_case.get("target_rank") != variant_case.get("target_rank") or baseline_case.get("is_topk_hit") != variant_case.get("is_topk_hit"):
            changed.append({"user_id": key[0], "target_item": key[1], "baseline_rank": baseline_case.get("target_rank"), "variant_rank": variant_case.get("target_rank"), "baseline_topk_hit": baseline_case.get("is_topk_hit"), "variant_topk_hit": variant_case.get("is_topk_hit")})
    payload = {"schema_version": "ranking_case_diff_v1", "baseline": baseline_row["candidate_id"], "changed_case_count": len(changed), "changed_cases": changed[:100]}
    write_json(path, payload)
    return path


def _cases_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(str(row.get("user_id", "")), str(row.get("target_item", ""))): row for row in rows if row.get("user_id") and row.get("target_item")}


def _first_candidate_rows_path(learned_training: dict[str, Any]) -> str | None:
    for training in learned_training.values():
        path = training.get("candidate_rows_path")
        if path and Path(path).exists():
            return str(path)
    return None


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


def _dependency_status() -> dict[str, bool]:
    return {dependency: importlib.util.find_spec(dependency) is not None for dependency in ["sklearn", "xgboost", "lightgbm"]}


def _gpu_resource_strategy(dependency_status: dict[str, bool]) -> dict[str, Any]:
    return {"schema_version": "ranking_gpu_strategy_v1", "current_phase_gpu_required": False, "future_gpu_required_families": ["xgboost_lambdamart", "lightgbm_lambdamart"], "dependency_status": dependency_status, "unavailable_status": "blocked-gpu-unavailable", "cpu_smoke_status": "diagnostic-cpu-smoke", "promotion_gate": "valid_test_gate_adr_and_serving_adapter_required_before_learned_or_tree_promotion"}


def _command_text(output_dir: Path, limit_users: int | None, seed: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_1_26_real_learned_gbdt_ranker.py", "--output-dir", str(output_dir), "--seed", str(seed)]
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
        "# Phase 1.26 Real Learned / GBDT Ranker",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Seed: `{comparison['seed']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: real learned training artifacts on frozen pool200; LTR-enabled ranking and tree models remain diagnostic/blocked until promotion gates and adapters exist.",
        "",
        "| candidate | lane | type | status | strict_status | promotable | diagnostic_only | reasons |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in comparison["runs"]:
        strict_status = row.get("strict_status", {})
        lines.append("| " + " | ".join([row["candidate_id"], row["lane"], row["candidate_type"], row["status"], str(strict_status.get("status")), str(strict_status.get("promotable")), str(strict_status.get("diagnostic_only")), ", ".join(strict_status.get("reasons", []))]) + " |")
    lines.extend(["", "## Tree training", "", "| method | state | status | artifact | reasons |", "| --- | --- | --- | --- | --- |"])
    for method_name, result in comparison["tree_training"].items():
        lines.append("| " + " | ".join([method_name, str(result.get("state")), str(result.get("status")), str(result.get("model_path") or result.get("minimal_dependency_list")), ", ".join(result.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
