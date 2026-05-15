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
from rs_core.recsys.evaluation import build_ranking_experiment_registry_entry, build_ranking_feature_contract, build_ranking_gpu_resource_summary, build_ranking_method_registry_entry, compare_frozen_candidate_signatures, inspect_ranking_run_artifacts, strict_ranking_promotion_status
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from scripts.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift
from scripts.run_phase_1_28_lightweight_learned_ranker import (
    LIGHTWEIGHT_LTR_VARIANTS,
    LTR_FEATURE_CONFIG,
    _not_applicable_feature_contract_gate,
    _not_applicable_leakage_gate,
    _public_training_result,
    _read_frozen_rows,
    _training_feature_contract_gate,
    _training_leakage_gate,
    _train_ltr_variant,
)

_PHASE = "phase_1_29_terminal_ranking_route"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/phase_1_29_terminal_ranking_route"
MINIMUM_RUNS = 3
REQUIRED_CONSISTENT_RUNS = 2
MINIMUM_SEGMENT_USERS = 30
MINIMUM_SEGMENT_POSITIVE_USERS = 5
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]
PROMOTION_VARIANTS = [
    {
        "name": "gbdt_style_stump_rules",
        "candidate_type": "gbdt",
        "description": "Dependency-free deterministic tree-style stand-in using existing normalized additive ranking components.",
        "overrides": {
            "normalized_additive_ranking": {
                "enabled": True,
                "weights": {
                    "source_signal": 0.4,
                    "item_feature": 0.2,
                    "freshness_quality": 0.1,
                    "near_miss_tiebreak_strength": 0.05,
                },
            },
        },
    },
    {
        "name": "lambdamart_style_pairwise_rules",
        "candidate_type": "lambdamart",
        "description": "Dependency-free deterministic LambdaMART-style stand-in using pairwise-inspired source and item feature boosts.",
        "overrides": {
            "source_aware_fusion": {
                "enabled": True,
                "itemcf_source_boost": 0.2,
                "itemcf_multi_source_boost": 0.4,
                "two_tower_itemcf_boost": 0.2,
                "two_tower_semantic_boost": 0.2,
                "semantic_only_penalty": 0.2,
            },
            "item_feature_rerank": {
                "enabled": True,
                "weights": {
                    "multi_source": 0.2,
                    "two_tower_itemcf_source": 0.2,
                    "two_tower_semantic_source": 0.2,
                    "popular_only": -0.2,
                },
            },
        },
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run terminal frozen pool200 ranking route comparison with promotion and diagnostic lanes.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for terminal route artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--runs", type=int, default=MINIMUM_RUNS, help="Number of same-run repetitions for stability evidence.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_terminal_ranking_route(output_dir=output_dir, limit_users=args.limit_users, runs=args.runs)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_terminal_ranking_route(output_dir: Path, limit_users: int | None = None, runs: int = MINIMUM_RUNS) -> dict[str, Any]:
    run_count = max(1, int(runs))
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users, run_count)
    run_rows: list[dict[str, Any]] = []
    for run_index in range(run_count):
        run_dir = output_dir / f"run_{run_index + 1}"
        baseline_row = _run_baseline(run_dir, limit_users, feature_contract, run_id, run_index, command_text)
        run_rows.append(baseline_row)
        for variant in PROMOTION_VARIANTS:
            run_rows.append(_run_promotion_variant(run_dir, limit_users, feature_contract, baseline_row, variant, run_id, run_index, command_text))
        for variant in LIGHTWEIGHT_LTR_VARIANTS:
            training_result = _train_ltr_variant(run_dir, limit_users, variant)
            run_rows.append(_run_diagnostic_ltr_variant(run_dir, limit_users, feature_contract, baseline_row, variant, training_result, run_id, run_index, command_text))
    summary = _stability_summary(run_rows)
    final_decision = _final_decision(summary)
    comparison = {
        "phase": _PHASE,
        "run_id": run_id,
        "limit_users": limit_users,
        "minimum_runs": MINIMUM_RUNS,
        "required_consistent_runs": REQUIRED_CONSISTENT_RUNS,
        "actual_runs": run_count,
        "candidate_pool_size": 200,
        "top_k": 5,
        "minimum_segment_users": MINIMUM_SEGMENT_USERS,
        "minimum_segment_positive_users": MINIMUM_SEGMENT_POSITIVE_USERS,
        "baseline_config_path": str(BASELINE_CONFIG),
        "output_dir": str(output_dir),
        "command_text": command_text,
        "lanes": _lane_definitions(),
        "promotion_thresholds": _promotion_thresholds(),
        "artifact_inspection": _artifact_inspection(run_rows),
        "stability_summary": summary,
        "final_decision": final_decision,
        "method_registry": [_method_registry_row(row, summary) for row in run_rows],
        "gpu_resource_strategy": _gpu_resource_strategy(),
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in run_rows],
        "runs": [_public_run_row(row) for row in run_rows],
    }
    return comparison


def _run_baseline(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], run_id: str, run_index: int, command_text: str) -> dict[str, Any]:
    variant_output_dir = output_dir / _BASELINE_VARIANT
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "strategy_name": f"{_PHASE}_{_BASELINE_VARIANT}_run_{run_index + 1}",
        },
    )
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(_BASELINE_VARIANT, result, metrics)
    status = _baseline_status()
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:run_{run_index + 1}:{_BASELINE_VARIANT}",
        config=_registry_config(metrics, _BASELINE_VARIANT),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
    )
    return _variant_row(
        variant_name=_BASELINE_VARIANT,
        candidate_type="baseline",
        lane="promotion",
        promotion_eligible=True,
        diagnostic_only=False,
        run_id=run_id,
        run_index=run_index,
        command_text=command_text,
        description="Same-run frozen pool200 baseline.",
        result=result,
        metrics=metrics,
        frozen_rows=frozen_rows,
        baseline_frozen_rows=frozen_rows,
        baseline_metrics=metrics,
        baseline_freeze=_freeze_values(metrics),
        strict_status=status,
        registry_entry=registry_entry,
    )


def _run_promotion_variant(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], baseline_row: dict[str, Any], variant: dict[str, Any], run_id: str, run_index: int, command_text: str) -> dict[str, Any]:
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
    frozen_rows = _read_frozen_rows(variant_name, result, metrics)
    baseline_metrics = baseline_row["raw_metrics"]
    baseline_frozen_rows = baseline_row["frozen_rows"]
    freeze_comparison = compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows)
    strict_status = strict_ranking_promotion_status(
        baseline_metrics,
        metrics,
        freeze_comparison,
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
    )
    status, drift = _status_and_drift(_freeze_values(metrics), baseline_row["freeze"])
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
    row = _variant_row(
        variant_name=variant_name,
        candidate_type=str(variant["candidate_type"]),
        lane="promotion",
        promotion_eligible=True,
        diagnostic_only=False,
        run_id=run_id,
        run_index=run_index,
        command_text=command_text,
        description=str(variant["description"]),
        result=result,
        metrics=metrics,
        frozen_rows=frozen_rows,
        baseline_frozen_rows=baseline_frozen_rows,
        baseline_metrics=baseline_metrics,
        baseline_freeze=baseline_row["freeze"],
        strict_status=strict_status,
        registry_entry=registry_entry,
    )
    row["status"] = status
    row["drift"] = drift
    return row


def _run_diagnostic_ltr_variant(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], baseline_row: dict[str, Any], variant: dict[str, Any], training_result: dict[str, Any], run_id: str, run_index: int, command_text: str) -> dict[str, Any]:
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
            "ltr_model": {
                "enabled": True,
                "model_path": training_result["model_path"],
                "score_scale": 1.0,
                "features": LTR_FEATURE_CONFIG,
            },
        },
    )
    metrics = dict(result["metrics"])
    metrics["ltr_training"] = training_result["metrics"]
    frozen_rows = _read_frozen_rows(variant_name, result, metrics)
    baseline_metrics = baseline_row["raw_metrics"]
    baseline_frozen_rows = baseline_row["frozen_rows"]
    freeze_comparison = compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows)
    feature_contract_gate_summary = _training_feature_contract_gate(training_result)
    leakage_gate_summary = _training_leakage_gate(training_result)
    strict_status = strict_ranking_promotion_status(
        baseline_metrics,
        metrics,
        freeze_comparison,
        ltr_enabled=True,
        feature_contract_gate_summary=feature_contract_gate_summary,
        leakage_gate_summary=leakage_gate_summary,
    )
    status, drift = _status_and_drift(_freeze_values(metrics), baseline_row["freeze"])
    if status == "INVALID" and "freeze_metric_drift" not in strict_status["reasons"]:
        strict_status = strict_status | {"status": "INVALID/STOP", "promotable": False, "diagnostic_only": True, "reasons": [*strict_status["reasons"], "freeze_metric_drift"]}
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{run_id}:run_{run_index + 1}:{variant_name}",
        config=_registry_config(metrics, variant_name),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=strict_status,
        feature_contract=feature_contract,
        feature_contract_gate_summary=feature_contract_gate_summary,
        leakage_gate_summary=leakage_gate_summary,
    )
    row = _variant_row(
        variant_name=variant_name,
        candidate_type=str(variant["model_type"]),
        lane="diagnostic",
        promotion_eligible=False,
        diagnostic_only=True,
        run_id=run_id,
        run_index=run_index,
        command_text=command_text,
        description="LOPO-trained lightweight LTR diagnostic comparator; excluded from promotion evidence.",
        result=result,
        metrics=metrics,
        frozen_rows=frozen_rows,
        baseline_frozen_rows=baseline_frozen_rows,
        baseline_metrics=baseline_metrics,
        baseline_freeze=baseline_row["freeze"],
        strict_status=strict_status,
        registry_entry=registry_entry,
    )
    row["status"] = status
    row["drift"] = drift
    row["ltr_training"] = _public_training_result(training_result)
    return row


def _variant_row(
    *,
    variant_name: str,
    candidate_type: str,
    lane: str,
    promotion_eligible: bool,
    diagnostic_only: bool,
    run_id: str,
    run_index: int,
    command_text: str,
    description: str,
    result: dict[str, Any],
    metrics: dict[str, Any],
    frozen_rows: list[dict[str, Any]],
    baseline_frozen_rows: list[dict[str, Any]],
    baseline_metrics: dict[str, Any],
    baseline_freeze: dict[str, Any],
    strict_status: dict[str, Any],
    registry_entry: dict[str, Any],
) -> dict[str, Any]:
    freeze = _freeze_values(metrics)
    status, drift = _status_and_drift(freeze, baseline_freeze)
    freeze_comparison = compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows)
    return {
        "run_id": run_id,
        "run_index": run_index,
        "candidate_id": variant_name,
        "candidate_type": candidate_type,
        "lane": lane,
        "promotion_eligible": promotion_eligible,
        "diagnostic_only": diagnostic_only,
        "description": description,
        "status": status,
        "strict_status": strict_status,
        "ranking_experiment_registry": registry_entry,
        "drift": drift,
        "frozen_candidate_comparison": freeze_comparison,
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


def _stability_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["candidate_id"], []).append(row)
    baseline_rows = grouped.get(_BASELINE_VARIANT, [])
    baseline_by_run = {row["run_index"]: row for row in baseline_rows}
    summary = {}
    for candidate_id, candidate_rows in grouped.items():
        if candidate_id == _BASELINE_VARIANT:
            summary[candidate_id] = {
                "lane": "promotion",
                "candidate_type": "baseline",
                "runs": len(candidate_rows),
                "consistent_runs": len(candidate_rows),
                "status": "BASELINE",
                "promotable": False,
                "diagnostic_only": False,
                "no_promote_reasons": ["same_run_baseline"],
            }
            continue
        consistent_rows = []
        no_promote_reasons: list[str] = []
        for row in candidate_rows:
            baseline = baseline_by_run.get(row["run_index"])
            if not baseline:
                no_promote_reasons.append("missing_same_run_baseline")
                continue
            row_status = row.get("strict_status", {})
            if row_status.get("status") == "Promote" and row.get("promotion_eligible"):
                consistent_rows.append(row)
            else:
                no_promote_reasons.extend(row_status.get("reasons") or [str(row_status.get("status", "not_promotable"))])
        required_runs_met = len(candidate_rows) >= MINIMUM_RUNS if candidate_rows and candidate_rows[0]["lane"] == "promotion" else False
        consistency_met = len(consistent_rows) >= REQUIRED_CONSISTENT_RUNS
        promotable = bool(candidate_rows and candidate_rows[0]["promotion_eligible"] and required_runs_met and consistency_met)
        summary[candidate_id] = {
            "lane": candidate_rows[0]["lane"],
            "candidate_type": candidate_rows[0]["candidate_type"],
            "runs": len(candidate_rows),
            "consistent_runs": len(consistent_rows),
            "required_runs_met": required_runs_met,
            "consistency_met": consistency_met,
            "status": "Promote" if promotable else "NO_PROMOTE",
            "promotable": promotable,
            "diagnostic_only": bool(candidate_rows[0]["diagnostic_only"]),
            "no_promote_reasons": sorted(set(no_promote_reasons or (["diagnostic_only"] if candidate_rows[0]["diagnostic_only"] else ["promotion_thresholds_not_met"]))),
        }
    return summary


def _final_decision(summary: dict[str, Any]) -> dict[str, Any]:
    for candidate_id in ("gbdt_style_stump_rules", "lambdamart_style_pairwise_rules"):
        row = summary.get(candidate_id, {})
        if row.get("promotable"):
            return {
                "selected_route": candidate_id,
                "status": "Promote",
                "reason": "promotion_thresholds_and_stability_met",
                "no_promote_rationale": _no_promote_rationale(summary, selected=candidate_id),
            }
    return {
        "selected_route": _BASELINE_VARIANT,
        "status": "BASELINE_FINAL_ROUTE",
        "reason": "no_promotion_candidate_met_terminal_thresholds",
        "attribution": ["feature_insufficiency", "label_sparsity", "offline_signal_limitation", "future_online_interaction_data_needed"],
        "no_promote_rationale": _no_promote_rationale(summary, selected=_BASELINE_VARIANT),
    }


def _no_promote_rationale(summary: dict[str, Any], *, selected: str) -> dict[str, Any]:
    return {
        candidate_id: {
            "candidate_type": row.get("candidate_type"),
            "lane": row.get("lane"),
            "reasons": row.get("no_promote_reasons", []),
        }
        for candidate_id, row in summary.items()
        if candidate_id != selected
    }


def _artifact_inspection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    inspection = inspect_ranking_run_artifacts(rows)
    return inspection | {"phase_1_27_1_28_overwrite_check": "new_output_dir_required; historical evidence referenced only"}


def _method_registry_row(row: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    candidate_summary = summary.get(row["candidate_id"], {})
    if row["candidate_id"] == _BASELINE_VARIANT:
        state = "champion"
    elif candidate_summary.get("promotable"):
        state = "challenger"
    elif row.get("diagnostic_only"):
        state = "diagnostic"
    else:
        state = "retired"
    return build_ranking_method_registry_entry(
        method_id=row["candidate_id"],
        method_family=row["candidate_type"],
        lane=row["lane"],
        state=state,
        promotion_eligible=bool(row["promotion_eligible"]),
        diagnostic_only=bool(row["diagnostic_only"]),
        reasons=candidate_summary.get("no_promote_reasons", []),
        champion_id=_BASELINE_VARIANT if state == "champion" else None,
        challenger_of=_BASELINE_VARIANT if state == "challenger" else None,
        gpu_resource=build_ranking_gpu_resource_summary(gpu_required=False),
    )


def _gpu_resource_strategy() -> dict[str, Any]:
    return {
        "schema_version": "ranking_gpu_strategy_v1",
        "current_phase_gpu_required": False,
        "future_gpu_required_families": ["ranknet", "lambdarank", "wide_deep", "deepfm", "dcn", "xdeepfm", "din", "dien", "bst", "sim", "dssm", "two_tower", "bandit", "rl", "grpo"],
        "unavailable_status": "blocked-gpu-unavailable",
        "cpu_smoke_status": "diagnostic-cpu-smoke",
        "promotion_gate": "gpu_training_resource_does_not_lower_offline_promotion_thresholds",
    }


def _public_run_row(row: dict[str, Any]) -> dict[str, Any]:
    public = {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}
    registry = row["ranking_experiment_registry"]
    public["candidate_pool_size"] = registry.get("candidate_pool_size")
    public["top_k"] = registry.get("top_k")
    public["frozen_candidate_match"] = row.get("frozen_candidate_comparison", {}).get("match")
    public["frozen_candidate_status"] = "PASS" if public["frozen_candidate_match"] else "INVALID"
    return public


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}))
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or 200
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or 5
    return config


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _baseline_status() -> dict[str, Any]:
    return {
        "status": "BASELINE",
        "promotable": False,
        "diagnostic_only": False,
        "reasons": ["same_run_baseline"],
        "metric_delta": {},
    }


def _lane_definitions() -> dict[str, Any]:
    return {
        "promotion": {
            "candidate_types": ["baseline", "gbdt", "lambdamart"],
            "promotion_eligible": True,
        },
        "diagnostic": {
            "candidate_types": ["pointwise_logistic", "pairwise_perceptron", "lopo", "deep_diagnostic"],
            "promotion_eligible": False,
        },
    }


def _promotion_thresholds() -> dict[str, Any]:
    return {
        "minimum_runs": MINIMUM_RUNS,
        "required_consistent_runs": REQUIRED_CONSISTENT_RUNS,
        "minimum_segment_users": MINIMUM_SEGMENT_USERS,
        "minimum_segment_positive_users": MINIMUM_SEGMENT_POSITIVE_USERS,
        "underpowered_segments": "diagnostic_only",
        "frozen_candidate_equality": True,
        "candidate_pool_size": 200,
        "top_k": 5,
        "fallback_rate": "not_increased",
        "hit_rate_at_k_absolute_lift": 0.001,
        "hit_rate_at_k_relative_lift": 0.03,
        "candidate_hit_missed_topk_users": "reduced_by_at_least_1",
        "secondary_metrics": "ndcg_at_k/mrr_at_k/map_at_k_not_regressed",
    }


def _command_text(output_dir: Path, limit_users: int | None, runs: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "scripts/run_phase_1_29_terminal_ranking_route.py", "--output-dir", str(output_dir), "--runs", str(runs)]
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
        "# Phase 1.29 Terminal Ranking Route",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Actual runs: `{comparison['actual_runs']}`",
        f"- Selected route: `{comparison['final_decision']['selected_route']}`",
        f"- Decision status: `{comparison['final_decision']['status']}`",
        "- Scope: offline frozen pool200 ranking only; no serving/frontend/display integration.",
        "",
        "| candidate | lane | type | runs | consistent | status | promotable | reasons |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for candidate_id, row in comparison["stability_summary"].items():
        lines.append(
            "| "
            + " | ".join(
                [
                    candidate_id,
                    str(row.get("lane")),
                    str(row.get("candidate_type")),
                    str(row.get("runs")),
                    str(row.get("consistent_runs")),
                    str(row.get("status")),
                    str(row.get("promotable")),
                    ", ".join(row.get("no_promote_reasons", [])),
                ]
            )
            + " |"
        )
    lines.extend(["", "## No-Promote Rationale", ""])
    for candidate_id, row in comparison["final_decision"].get("no_promote_rationale", {}).items():
        lines.append(f"- `{candidate_id}` ({row['lane']}/{row['candidate_type']}): {', '.join(row['reasons'])}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
