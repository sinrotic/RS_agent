from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_jsonl, write_json
from rs_core.recsys.evaluation import build_ranking_experiment_registry_entry, build_ranking_feature_contract, build_ranking_gpu_resource_summary, build_ranking_method_registry_entry, compare_frozen_candidate_signatures, inspect_ranking_run_artifacts
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from scripts.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift

_PHASE = "phase_5_sequence_attention_ranker"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_5_sequence_attention_ranker"
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
SEQUENCE_METHODS = [
    {"name": "session_aware_reranker_short_history_diagnostic", "method_family": "session_aware_reranker", "state_if_ready": "diagnostic", "reasons": ["short_history_diagnostic_only", "serving_adapter_missing", "promotion_adr_required"]},
    {"name": "attention_over_user_history_diagnostic", "method_family": "attention_history", "state_if_ready": "diagnostic", "reasons": ["short_history_diagnostic_only", "serving_adapter_missing", "promotion_adr_required"]},
    {"name": "din_sequence_ranker", "method_family": "din", "state_if_ready": "blocked", "reasons": ["long_sequence_data_insufficient", "item_embedding_sequence_adapter_missing", "serving_adapter_missing"]},
    {"name": "dien_sequence_ranker", "method_family": "dien", "state_if_ready": "blocked", "reasons": ["long_sequence_data_insufficient", "interest_evolution_adapter_missing", "serving_adapter_missing"]},
    {"name": "bst_sequence_ranker", "method_family": "bst", "state_if_ready": "blocked", "reasons": ["long_sequence_data_insufficient", "transformer_sequence_adapter_missing", "serving_adapter_missing"]},
    {"name": "sim_sequence_ranker", "method_family": "sim", "state_if_ready": "blocked", "reasons": ["long_sequence_data_insufficient", "multi_stage_sequence_retrieval_adapter_missing", "serving_adapter_missing"]},
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 5 sequence/attention ranker data-readiness gates on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 5 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_5_sequence_ranker(output_dir=output_dir, limit_users=args.limit_users)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_5_sequence_ranker(output_dir: Path, limit_users: int | None = None) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users)
    data_readiness = _sequence_data_readiness(limit_users)
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, run_id, command_text)
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
        "data_readiness": data_readiness,
        "lanes": {
            "promotion": {"candidate_types": ["baseline"], "promotion_eligible": True},
            "diagnostic": {"candidate_types": ["session_aware_reranker", "attention_history"], "promotion_eligible": False},
            "blocked": {"candidate_types": ["din", "dien", "bst", "sim"], "promotion_eligible": False},
        },
        "promotion_policy": {"sequence_rankers_require_reliable_ordered_history": True, "long_sequence_models_blocked_until_data_ready": True, "future_interactions_forbidden": True, "serving_adapter_required_for_promotion": True},
        "artifact_inspection": inspect_ranking_run_artifacts([baseline_row]) | {"phase_5_scope": "sequence_attention_data_readiness_on_frozen_pool200"},
        "final_decision": {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "sequence_rankers_are_blocked_or_diagnostic_only"},
        "method_registry": [_method_registry_row(baseline_row), *_sequence_method_registry_rows(data_readiness)],
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


def _sequence_data_readiness(limit_users: int | None) -> dict[str, Any]:
    config = yaml.safe_load(BASELINE_CONFIG.read_text(encoding="utf-8"))
    sequence_path = ROOT / _resolve_config_path(config["clean_dir"]) / "user_sequences.train.jsonl"
    rows = read_jsonl(sequence_path)
    if limit_users is not None:
        rows = rows[:limit_users]
    positive_lengths = [int(row.get("positive_sequence_len") or len(row.get("recent_positive_item_sequence", []))) for row in rows]
    sequence_lengths = [int(row.get("sequence_len") or len(row.get("recent_item_sequence", []))) for row in rows]
    timestamp_rows = 0
    ordered_timestamp_rows = 0
    aligned_timestamp_rows = 0
    for row in rows:
        items = row.get("recent_positive_item_sequence") or []
        timestamps = row.get("recent_positive_timestamp_sequence") or []
        if timestamps:
            timestamp_rows += 1
            if timestamps == sorted(timestamps):
                ordered_timestamp_rows += 1
            if len(items) == len(timestamps):
                aligned_timestamp_rows += 1
    users = len(rows)
    ge_2 = sum(1 for value in positive_lengths if value >= 2)
    ge_5 = sum(1 for value in positive_lengths if value >= 5)
    ge_10 = sum(1 for value in positive_lengths if value >= 10)
    timestamp_coverage_rate = timestamp_rows / users if users else 0.0
    timestamp_ordered_rate = ordered_timestamp_rows / timestamp_rows if timestamp_rows else 0.0
    long_sequence_ready = users >= 1000 and ge_10 / users >= 0.2 if users else False
    short_sequence_diagnostic_ready = users >= 100 and ge_2 / users >= 0.5 and timestamp_ordered_rate >= 0.99 if users else False
    reasons = []
    if not long_sequence_ready:
        reasons.append("long_sequence_coverage_below_threshold")
    if not short_sequence_diagnostic_ready:
        reasons.append("short_sequence_diagnostic_threshold_not_met")
    if timestamp_ordered_rate < 0.99:
        reasons.append("timestamp_ordering_not_reliable")
    return {
        "schema_version": "sequence_ranker_data_readiness_v1",
        "sequence_path": str(sequence_path),
        "users": users,
        "positive_len_min": min(positive_lengths) if positive_lengths else 0,
        "positive_len_max": max(positive_lengths) if positive_lengths else 0,
        "positive_len_avg": round(sum(positive_lengths) / users, 4) if users else 0.0,
        "sequence_len_avg": round(sum(sequence_lengths) / users, 4) if users else 0.0,
        "users_with_positive_len_ge_2": ge_2,
        "users_with_positive_len_ge_5": ge_5,
        "users_with_positive_len_ge_10": ge_10,
        "positive_len_ge_2_rate": round(ge_2 / users, 4) if users else 0.0,
        "positive_len_ge_5_rate": round(ge_5 / users, 4) if users else 0.0,
        "positive_len_ge_10_rate": round(ge_10 / users, 4) if users else 0.0,
        "timestamp_coverage_rate": round(timestamp_coverage_rate, 4),
        "timestamp_ordered_rate": round(timestamp_ordered_rate, 4),
        "timestamp_alignment_rate": round(aligned_timestamp_rows / timestamp_rows, 4) if timestamp_rows else 0.0,
        "short_sequence_diagnostic_ready": short_sequence_diagnostic_ready,
        "long_sequence_model_ready": long_sequence_ready,
        "future_interaction_policy": "leave_one_positive_out_or_train_history_only_required",
        "reasons": reasons,
    }


def _resolve_config_path(path: str | Path) -> Path:
    target = Path(path)
    return target if target.is_absolute() else target


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


def _sequence_method_registry_rows(data_readiness: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for method in SEQUENCE_METHODS:
        short_method = method["method_family"] in {"session_aware_reranker", "attention_history"}
        if short_method and data_readiness["short_sequence_diagnostic_ready"]:
            state = "diagnostic"
            reasons = method["reasons"]
        else:
            state = "blocked"
            reasons = sorted(set([*method["reasons"], *data_readiness.get("reasons", [])]))
        rows.append(
            build_ranking_method_registry_entry(
                method_id=method["name"],
                method_family=method["method_family"],
                lane="diagnostic" if state == "diagnostic" else "blocked",
                state=state,
                promotion_eligible=False,
                diagnostic_only=state == "diagnostic",
                reasons=reasons,
                gpu_resource=build_ranking_gpu_resource_summary(gpu_required=method["method_family"] in {"din", "dien", "bst", "sim"}, gpu_available=None, dependency_status="not_checked"),
            )
        )
    return rows


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
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["sequence_ranker_not_trained"]}


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "reasons": ["sequence_ranker_not_trained"]}


def _gpu_resource_strategy() -> dict[str, Any]:
    return {"schema_version": "ranking_gpu_strategy_v1", "current_phase_gpu_required": False, "future_gpu_required_families": ["din", "dien", "bst", "sim"], "unavailable_status": "blocked-gpu-unavailable", "cpu_smoke_status": "diagnostic-cpu-smoke", "promotion_gate": "sequence_models_blocked_until_long_history_session_adapter_and_no_future_leakage_are_ready"}


def _command_text(output_dir: Path, limit_users: int | None) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/run_phase_5_sequence_ranker.py", "--output-dir", str(output_dir)]
    if limit_users is not None:
        parts.extend(["--limit-users", str(limit_users)])
    return " ".join(parts)


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    readiness = comparison["data_readiness"]
    lines = [
        "# Phase 5 Sequence / Attention Ranker Gate",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: sequence data readiness and registry only; no DIN/DIEN/BST/SIM promotion claim.",
        "",
        "## Data readiness",
        "",
        f"- Users: `{readiness['users']}`",
        f"- Positive len >= 2 rate: `{readiness['positive_len_ge_2_rate']}`",
        f"- Positive len >= 10 rate: `{readiness['positive_len_ge_10_rate']}`",
        f"- Timestamp ordered rate: `{readiness['timestamp_ordered_rate']}`",
        f"- Short-sequence diagnostic ready: `{readiness['short_sequence_diagnostic_ready']}`",
        f"- Long-sequence model ready: `{readiness['long_sequence_model_ready']}`",
        "",
        "## Method registry",
        "",
        "| method | family | state | reasons |",
        "| --- | --- | --- | --- |",
    ]
    for row in comparison["method_registry"]:
        lines.append("| " + " | ".join([row["method_id"], row["method_family"], row["state"], ", ".join(row.get("reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
