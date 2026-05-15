from __future__ import annotations

import argparse
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

_PHASE = "phase_7_8_future_online_gate"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_7_8_future_online_gate"
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
PHASE_7_METHODS = [
    ("esmm_ctr_cvr_ranker", "esmm"),
    ("mmoe_multi_task_ranker", "mmoe"),
    ("ple_multi_task_ranker", "ple"),
    ("multi_task_learning_ranker", "multi_task_learning"),
    ("diversity_novelty_calibration_objective", "diversity_novelty_calibration"),
    ("constrained_ranking_policy", "constrained_ranking"),
]
PHASE_8_METHODS = [
    ("contextual_bandit_ranker", "contextual_bandit"),
    ("thompson_ucb_exploration_policy", "bandit_exploration"),
    ("learning_to_rank_from_feedback", "ltr_from_feedback"),
    ("rl_grpo_preference_ranker", "rl_grpo"),
    ("conversational_rerank_policy", "conversational_rerank"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 7/8 future-online boundary gate on frozen pool200 baseline artifacts.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 7/8 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_7_8_future_online_gate(output_dir=output_dir, limit_users=args.limit_users)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_7_8_future_online_gate(output_dir: Path, limit_users: int | None = None) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users)
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "candidate_pool_size": 200,
        "top_k": 5,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "future_online_readiness": _future_online_readiness(),
        "lanes": {
            "promotion": {"candidate_types": ["baseline"], "promotion_eligible": True},
            "future-online": {"candidate_types": [family for _, family in PHASE_7_METHODS], "promotion_eligible": False},
            "future-agent-online": {"candidate_types": [family for _, family in PHASE_8_METHODS], "promotion_eligible": False},
        },
        "promotion_policy": {
            "offline_frozen_pool200_current_scope": True,
            "online_metrics_current_promotion_forbidden": True,
            "ctr_cvr_gmv_labels_required_for_phase_7": True,
            "safe_exploration_and_replay_required_for_phase_8": True,
            "serving_monitoring_contract_required": True,
        },
        "artifact_inspection": inspect_ranking_run_artifacts([baseline_row]) | {"phase_7_8_scope": "future_online_boundary_only_on_frozen_pool200_baseline"},
        "final_decision": {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "phase_7_8_methods_are_future_online_only"},
        "method_registry": [_method_registry_row(baseline_row), *_future_method_registry_rows()],
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


def _future_method_registry_rows() -> list[dict[str, Any]]:
    rows = []
    for method_id, family in PHASE_7_METHODS:
        rows.append(_blocked_future_method(method_id, family, "future-online", ["business_label_missing", "online_or_quasi_online_evaluation_missing", "serving_monitoring_contract_missing", "online_metrics_forbidden_as_current_offline_evidence"]))
    for method_id, family in PHASE_8_METHODS:
        rows.append(_blocked_future_method(method_id, family, "future-agent-online", ["interaction_log_missing", "safe_exploration_policy_missing", "offline_replay_or_ab_test_missing", "feedback_reward_schema_required", "online_metrics_forbidden_as_current_offline_evidence"]))
    return rows


def _blocked_future_method(method_id: str, family: str, lane: str, reasons: list[str]) -> dict[str, Any]:
    gpu_required = family in {"mmoe", "ple", "multi_task_learning", "rl_grpo"}
    return build_ranking_method_registry_entry(
        method_id=method_id,
        method_family=family,
        lane=lane,
        state="blocked",
        promotion_eligible=False,
        diagnostic_only=False,
        reasons=reasons,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=gpu_required, gpu_available=None, dependency_status="future-online-not-checked"),
    )


def _future_online_readiness() -> dict[str, Any]:
    return {
        "schema_version": "future_online_ranking_readiness_v1",
        "phase_7": {
            "state": "future-online",
            "business_labels_available": False,
            "online_or_quasi_online_eval_available": False,
            "serving_monitoring_contract_available": False,
            "current_offline_promotion_eligible": False,
            "blocked_reasons": ["ctr_cvr_gmv_labels_missing", "online_or_quasi_online_evaluation_missing", "serving_monitoring_contract_missing"],
        },
        "phase_8": {
            "state": "future-agent-online",
            "interaction_logs_available": False,
            "safe_exploration_policy_available": False,
            "offline_replay_or_ab_test_available": False,
            "current_offline_promotion_eligible": False,
            "blocked_reasons": ["interaction_log_missing", "safe_exploration_policy_missing", "offline_replay_or_ab_test_missing"],
        },
        "forbidden_current_evidence": ["ctr", "cvr", "gmv", "p95", "slo", "ab_uplift"],
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


def _baseline_status() -> dict[str, Any]:
    return {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}}


def _not_applicable_feature_contract_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["future_online_methods_not_trained"]}


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "reasons": ["future_online_methods_not_trained"]}


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _command_text(output_dir: Path, limit_users: int | None) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/run_phase_7_8_future_online_gate.py", "--output-dir", str(output_dir)]
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
        "# Phase 7/8 Future Online Gate",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: future-online boundary only; no current offline promotion from online metrics.",
        "",
        "## Method registry",
        "",
        "| method | family | lane | state | reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in comparison["method_registry"]:
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["lane"], row["state"], ", ".join(row.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
