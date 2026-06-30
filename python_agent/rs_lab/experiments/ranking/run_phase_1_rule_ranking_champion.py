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

_PHASE = "phase_1_rule_ranking_champion"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_rule_ranking_champion"
MINIMUM_RUNS = 3
REQUIRED_CONSISTENT_RUNS = 2
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
RULE_VARIANTS = [
    {
        "name": "normalized_additive_balanced",
        "method_family": "normalized_additive",
        "description": "Balanced normalized additive source/item rule baseline on frozen pool200 candidates.",
        "overrides": {
            "normalized_additive_ranking": {
                "enabled": True,
                "weights": {"source_signal": 0.2, "item_feature": 0.2, "freshness_quality": 0.1, "near_miss_tiebreak_strength": 0.05},
            }
        },
    },
    {
        "name": "source_aware_itemcf_protection",
        "method_family": "source_aware_fusion",
        "description": "Explainable source-aware rule that protects itemcf/multi-source candidates without changing recall.",
        "overrides": {
            "source_aware_fusion": {
                "enabled": True,
                "itemcf_source_boost": 0.2,
                "itemcf_multi_source_boost": 0.4,
                "semantic_only_penalty": 0.2,
                "popular_only_penalty": 0.1,
            }
        },
    },
    {
        "name": "item_feature_multi_source_rescue",
        "method_family": "item_feature_rerank",
        "description": "Explainable item-feature rerank emphasizing multi-source and two-tower/itemcf overlap features.",
        "overrides": {
            "item_feature_rerank": {
                "enabled": True,
                "weights": {"multi_source": 0.2, "two_tower_itemcf_source": 0.2, "two_tower_semantic_source": 0.2, "popular_only": -0.2},
            }
        },
    },
    {
        "name": "coordinate_rule_combo_conservative",
        "method_family": "finite_grid_rules",
        "description": "Conservative coordinate-style combination of normalized additive, source-aware, and item-feature signals.",
        "overrides": {
            "normalized_additive_ranking": {
                "enabled": True,
                "weights": {"source_signal": 0.2, "item_feature": 0.2, "freshness_quality": 0.1, "near_miss_tiebreak_strength": 0.05},
            },
            "source_aware_fusion": {
                "enabled": True,
                "itemcf_source_boost": 0.2,
                "itemcf_multi_source_boost": 0.2,
                "semantic_only_penalty": 0.2,
            },
            "item_feature_rerank": {
                "enabled": True,
                "weights": {"multi_source": 0.2, "two_tower_itemcf_source": 0.2, "popular_only": -0.2},
            },
        },
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1 explainable rule-ranking champion/challenger comparison on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 1 rule-ranking artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--runs", type=int, default=MINIMUM_RUNS, help="Number of same-run repetitions for stability evidence.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_1_rule_ranking(output_dir=output_dir, limit_users=args.limit_users, runs=args.runs)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_1_rule_ranking(output_dir: Path, limit_users: int | None = None, runs: int = MINIMUM_RUNS) -> dict[str, Any]:
    run_count = max(1, int(runs))
    feature_contract = build_ranking_feature_contract()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    command_text = _command_text(output_dir, limit_users, run_count)
    run_rows: list[dict[str, Any]] = []
    for run_index in range(run_count):
        run_dir = output_dir / f"run_{run_index + 1}"
        baseline_row = _run_variant(run_dir, limit_users, feature_contract, run_id, run_index, command_text, _baseline_variant(), None)
        run_rows.append(baseline_row)
        for variant in RULE_VARIANTS:
            run_rows.append(_run_variant(run_dir, limit_users, feature_contract, run_id, run_index, command_text, variant, baseline_row))
    summary = _stability_summary(run_rows)
    final_decision = _final_decision(summary)
    return {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "minimum_runs": MINIMUM_RUNS,
        "required_consistent_runs": REQUIRED_CONSISTENT_RUNS,
        "actual_runs": run_count,
        "candidate_pool_size": 200,
        "top_k": 5,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "lanes": {"promotion": {"candidate_types": ["baseline", "normalized_additive", "source_aware_fusion", "item_feature_rerank", "finite_grid_rules"], "promotion_eligible": True}},
        "promotion_thresholds": _promotion_thresholds(),
        "artifact_inspection": _artifact_inspection(run_rows),
        "stability_summary": summary,
        "final_decision": final_decision,
        "method_registry": [_method_registry_row(row, summary) for row in run_rows],
        "gpu_resource_strategy": _gpu_resource_strategy(),
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in run_rows],
        "runs": [_public_run_row(row) for row in run_rows],
    }


def _baseline_variant() -> dict[str, Any]:
    return {"name": _BASELINE_VARIANT, "method_family": "baseline", "description": "Same-run frozen pool200 baseline.", "overrides": {}}


def _run_variant(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, run_index: int, command_text: str, variant: dict[str, Any], baseline_row: dict[str, Any] | None) -> dict[str, Any]:
    variant_name = str(variant["name"])
    variant_output_dir = output_dir / variant_name
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "strategy_name": f"{_PHASE}_{variant_name}_run_{run_index + 1}",
            **variant["overrides"],
        },
    )
    metrics = result["metrics"]
    frozen_path = result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path")
    if not frozen_path or not Path(frozen_path).exists():
        raise ValueError(f"{variant_name} did not export frozen candidates")
    frozen_rows = read_jsonl(frozen_path)
    if baseline_row is None:
        freeze_comparison = compare_frozen_candidate_signatures(frozen_rows, frozen_rows)
        strict_status = _baseline_status()
        baseline_freeze = _freeze_values(metrics)
    else:
        freeze_comparison = compare_frozen_candidate_signatures(baseline_row["frozen_rows"], frozen_rows)
        strict_status = strict_ranking_promotion_status(
            baseline_row["raw_metrics"],
            metrics,
            freeze_comparison,
            feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
            leakage_gate_summary=_not_applicable_leakage_gate(),
        )
        baseline_freeze = baseline_row["freeze"]
    freeze = _freeze_values(metrics)
    status, drift = _status_and_drift(freeze, baseline_freeze)
    if status == "INVALID" and "freeze_metric_drift" not in strict_status["reasons"]:
        strict_status = strict_status | {"status": "INVALID/STOP", "promotable": False, "diagnostic_only": True, "reasons": [*strict_status["reasons"], "freeze_metric_drift"]}
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:run_{run_index + 1}:{variant_name}",
        config=_registry_config(metrics, variant_name),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=strict_status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
    )
    return {
        "run_id": run_id,
        "run_index": run_index,
        "candidate_id": variant_name,
        "candidate_type": str(variant["method_family"]),
        "lane": "promotion",
        "promotion_eligible": True,
        "diagnostic_only": False,
        "description": str(variant["description"]),
        "status": status,
        "strict_status": strict_status,
        "ranking_experiment_registry": registry_entry,
        "drift": drift,
        "frozen_candidate_comparison": freeze_comparison,
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(variant_output_dir),
        "command_text": command_text,
        "metrics_path": result["metrics_path"],
        "recommendations_path": result["recommendations_path"],
        "ranking_cases_path": result["ranking_cases_path"],
        "ranking_case_summary_path": result["ranking_case_summary_path"],
        "report_path": result["report_path"],
        "frozen_candidates_path": frozen_path,
        "frozen_candidates_exported": True,
        "metrics": {key: metrics.get(key) for key in METRIC_FIELDS},
        "raw_metrics": metrics,
        "frozen_rows": frozen_rows,
        "freeze": freeze,
    }


def _stability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["candidate_id"], []).append(row)
    summary = {}
    for candidate_id, candidate_rows in grouped.items():
        if candidate_id == _BASELINE_VARIANT:
            summary[candidate_id] = {"lane": "promotion", "candidate_type": "baseline", "runs": len(candidate_rows), "consistent_runs": len(candidate_rows), "status": "BASELINE", "promotable": False, "diagnostic_only": False, "no_promote_reasons": ["same_run_baseline"]}
            continue
        consistent_rows = [row for row in candidate_rows if row.get("strict_status", {}).get("status") == "Promote" and row.get("promotion_eligible")]
        no_promote_reasons = [reason for row in candidate_rows for reason in (row.get("strict_status", {}).get("reasons") or [str(row.get("strict_status", {}).get("status", "not_promotable"))])]
        required_runs_met = len(candidate_rows) >= MINIMUM_RUNS
        consistency_met = len(consistent_rows) >= REQUIRED_CONSISTENT_RUNS
        promotable = required_runs_met and consistency_met
        summary[candidate_id] = {
            "lane": "promotion",
            "candidate_type": candidate_rows[0]["candidate_type"],
            "runs": len(candidate_rows),
            "consistent_runs": len(consistent_rows),
            "required_runs_met": required_runs_met,
            "consistency_met": consistency_met,
            "status": "Promote" if promotable else "NO_PROMOTE",
            "promotable": promotable,
            "diagnostic_only": False,
            "no_promote_reasons": sorted(set(no_promote_reasons or ["promotion_thresholds_not_met"])),
        }
    return summary


def _final_decision(summary: dict[str, Any]) -> dict[str, Any]:
    for candidate_id in [variant["name"] for variant in RULE_VARIANTS]:
        row = summary.get(candidate_id, {})
        if row.get("promotable"):
            return {"selected_route": candidate_id, "status": "Promote", "reason": "phase_1_rule_thresholds_and_stability_met", "no_promote_rationale": _no_promote_rationale(summary, selected=candidate_id)}
    return {"selected_route": _BASELINE_VARIANT, "status": "BASELINE_FINAL_ROUTE", "reason": "no_rule_candidate_met_phase_1_thresholds", "no_promote_rationale": _no_promote_rationale(summary, selected=_BASELINE_VARIANT)}


def _method_registry_row(row: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    candidate_summary = summary.get(row["candidate_id"], {})
    if row["candidate_id"] == _BASELINE_VARIANT:
        state = "champion"
    elif candidate_summary.get("promotable"):
        state = "challenger"
    else:
        state = "retired"
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane=row["lane"],
        state=state,
        promotion_eligible=True,
        diagnostic_only=False,
        reasons=candidate_summary.get("no_promote_reasons", []),
        champion_id=_BASELINE_VARIANT if state == "champion" else None,
        challenger_of=_BASELINE_VARIANT if state == "challenger" else None,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _artifact_inspection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return inspect_ranking_run_artifacts(rows) | {"phase_1_scope": "explainable_rule_ranking_on_frozen_pool200"}


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


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _baseline_status() -> dict[str, Any]:
    return {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": ["same_run_baseline"], "metric_delta": {}}


def _not_applicable_feature_contract_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_contract_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "checked_feature_count": 0, "reasons": ["rule_ranking_no_ltr_training"]}


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {"schema_version": "ranking_feature_leakage_gate_v1", "status": "NOT_APPLICABLE", "checked_rows": 0, "reasons": ["rule_ranking_no_ltr_training"]}


def _gpu_resource_strategy() -> dict[str, Any]:
    return {"schema_version": "ranking_gpu_strategy_v1", "current_phase_gpu_required": False, "future_gpu_required_families": [], "unavailable_status": "blocked-gpu-unavailable", "cpu_smoke_status": "diagnostic-cpu-smoke", "promotion_gate": "rule_ranking_uses_offline_frozen_pool200_gates_only"}


def _promotion_thresholds() -> dict[str, Any]:
    return {"minimum_runs": MINIMUM_RUNS, "required_consistent_runs": REQUIRED_CONSISTENT_RUNS, "frozen_candidate_equality": True, "candidate_pool_size": 200, "top_k": 5, "fallback_rate": "not_increased", "hit_rate_at_k_absolute_lift": 0.001, "hit_rate_at_k_relative_lift": 0.03, "candidate_hit_missed_topk_users": "reduced_by_at_least_1", "secondary_metrics": "ndcg_at_k/mrr_at_k/map_at_k_not_regressed"}


def _no_promote_rationale(summary: dict[str, Any], *, selected: str) -> dict[str, Any]:
    return {candidate_id: {"candidate_type": row.get("candidate_type"), "lane": row.get("lane"), "reasons": row.get("no_promote_reasons", [])} for candidate_id, row in summary.items() if candidate_id != selected}


def _command_text(output_dir: Path, limit_users: int | None, runs: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_1_rule_ranking_champion.py", "--output-dir", str(output_dir), "--runs", str(runs)]
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
        "# Phase 1 Rule Ranking Champion/Challenger",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: offline frozen pool200 rule ranking only; no recall, serving, frontend, or online-metric claim.",
        "",
        "| candidate | type | runs | consistent | status | promotable | reasons |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate_id, row in comparison["stability_summary"].items():
        lines.append("| " + " | ".join([candidate_id, str(row.get("candidate_type")), str(row.get("runs")), str(row.get("consistent_runs")), str(row.get("status")), str(row.get("promotable")), ", ".join(row.get("no_promote_reasons", []))]) + " |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
