from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_jsonl, write_json
from rs_core.recsys.evaluation import build_ranking_experiment_registry_entry, build_ranking_feature_contract, compare_frozen_candidate_signatures, strict_ranking_promotion_status
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.ltr_training import train_ltr_ranker
from scripts.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift

METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]

_PHASE = "phase_1_28_lightweight_learned_ranker"
_BASELINE_VARIANT = "same_run_baseline"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_28_lightweight_learned_ranker"
LTR_FEATURE_CONFIG = {"version": "ltr_v2"}
LIGHTWEIGHT_LTR_VARIANTS = [
    {
        "name": "pointwise_logistic_lopo_ltr",
        "model_type": "pointwise_logistic",
        "train": {
            "epochs": 3,
            "learning_rate": 0.1,
            "positive_weight": 1.0,
            "negative_weight": 1.0,
        },
    },
    {
        "name": "pairwise_perceptron_lopo_ltr",
        "model_type": "pairwise_perceptron",
        "train": {
            "epochs": 3,
            "learning_rate": 0.1,
            "negative_sample_per_positive": 3,
            "margin": 1.0,
        },
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.28 lightweight learned-ranker comparison on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 1.28 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    feature_contract = build_ranking_feature_contract()
    baseline_row = _run_baseline(output_dir, args.limit_users, feature_contract)
    ltr_training_results = {}
    variants = {_BASELINE_VARIANT: baseline_row}
    for variant in LIGHTWEIGHT_LTR_VARIANTS:
        training_result = _train_ltr_variant(output_dir, args.limit_users, variant)
        variant_name = str(variant["name"])
        ltr_training_results[variant_name] = _public_training_result(training_result)
        variants[variant_name] = _run_ltr_variant(output_dir, args.limit_users, feature_contract, baseline_row, variant, training_result)
    comparison_variants = {name: _public_variant_row(row) for name, row in variants.items()}
    comparison = {
        "phase": _PHASE,
        "limit_users": args.limit_users,
        "output_dir": str(output_dir),
        "baseline_config_path": str(BASELINE_CONFIG),
        "freeze_fields": FREEZE_FIELDS,
        "baseline_variant": _BASELINE_VARIANT,
        "ltr_variants": [variant["name"] for variant in LIGHTWEIGHT_LTR_VARIANTS],
        "ltr_training": ltr_training_results,
        "all_variants_valid": all(_row_is_valid(row) for row in variants.values()),
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in variants.values()],
        "variants": comparison_variants,
    }
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


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



def _run_baseline(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any]) -> dict[str, Any]:
    variant_output_dir = output_dir / _BASELINE_VARIANT
    result = run_hybrid_demo(
        BASELINE_CONFIG,
        limit_users=limit_users,
        config_overrides={
            "output_dir": str(variant_output_dir),
            "report_path": str(variant_output_dir / "report.md"),
            "export_frozen_candidates": True,
            "strategy_name": f"{_PHASE}_{_BASELINE_VARIANT}",
        },
    )
    metrics = result["metrics"]
    frozen_rows = _read_frozen_rows(_BASELINE_VARIANT, result, metrics)
    feature_contract_gate_summary = _not_applicable_feature_contract_gate()
    leakage_gate_summary = _not_applicable_leakage_gate()
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{_BASELINE_VARIANT}",
        config=_registry_config(metrics, _BASELINE_VARIANT),
        frozen_rows=frozen_rows,
        metrics=metrics,
        status=_baseline_status(),
        feature_contract=feature_contract,
        feature_contract_gate_summary=feature_contract_gate_summary,
        leakage_gate_summary=leakage_gate_summary,
    )
    return _variant_row(
        variant_name=_BASELINE_VARIANT,
        result=result,
        metrics=metrics,
        frozen_rows=frozen_rows,
        baseline_frozen_rows=frozen_rows,
        baseline_metrics=metrics,
        baseline_freeze=_freeze_values(metrics),
        strict_status=_baseline_status(),
        registry_entry=registry_entry,
    )


def _run_ltr_variant(output_dir: Path, limit_users: int | None, feature_contract: dict[str, Any], baseline_row: dict[str, Any], variant: dict[str, Any], training_result: dict[str, Any]) -> dict[str, Any]:
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
    baseline_freeze = baseline_row["freeze"]
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
    status, drift = _status_and_drift(_freeze_values(metrics), baseline_freeze)
    if status == "INVALID" and "freeze_metric_drift" not in strict_status["reasons"]:
        strict_status = strict_status | {"status": "INVALID/STOP", "promotable": False, "diagnostic_only": True, "reasons": [*strict_status["reasons"], "freeze_metric_drift"]}
    registry_entry = build_ranking_experiment_registry_entry(
        experiment_id=f"{_PHASE}:{variant_name}",
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
        result=result,
        metrics=metrics,
        frozen_rows=frozen_rows,
        baseline_frozen_rows=baseline_frozen_rows,
        baseline_metrics=baseline_metrics,
        baseline_freeze=baseline_freeze,
        strict_status=strict_status,
        registry_entry=registry_entry,
    )
    row["status"] = status
    row["drift"] = drift
    row["ltr_training"] = {
        "model_path": training_result["model_path"],
        "metrics_path": training_result["metrics_path"],
        "candidate_rows_path": training_result.get("candidate_rows_path"),
    }
    return row


def _variant_row(
    *,
    variant_name: str,
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
        "status": status,
        "strict_status": strict_status,
        "ranking_experiment_registry": registry_entry,
        "drift": drift,
        "frozen_candidate_comparison": freeze_comparison,
        "config_path": str(BASELINE_CONFIG),
        "output_dir": str(Path(result["metrics_path"]).parent),
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


def _public_variant_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"raw_metrics", "frozen_rows", "freeze"}}



def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}))
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or 200
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or 5
    return config



def _public_training_result(training_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_path": training_result["model_path"],
        "metrics_path": training_result["metrics_path"],
        "candidate_rows_path": training_result.get("candidate_rows_path"),
        "metrics": training_result["metrics"],
    }



def _read_frozen_rows(variant_name: str, result: dict[str, Any], metrics: dict[str, Any]) -> list[dict[str, Any]]:
    frozen_candidates_path = result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path")
    if not frozen_candidates_path or not Path(frozen_candidates_path).exists():
        raise ValueError(f"{variant_name} did not export frozen_candidates.jsonl")
    return read_jsonl(frozen_candidates_path)


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _training_feature_contract_gate(training_result: dict[str, Any]) -> dict[str, Any]:
    summary = (training_result.get("metrics") or {}).get("feature_contract_gate")
    if isinstance(summary, dict):
        return summary
    return {
        "schema_version": "ranking_feature_contract_gate_v1",
        "status": "REJECT",
        "checked_rows": 0,
        "checked_feature_count": 0,
        "reasons": ["missing_feature_contract_gate_summary"],
    }


def _training_leakage_gate(training_result: dict[str, Any]) -> dict[str, Any]:
    summary = (training_result.get("metrics") or {}).get("leakage_gate")
    if isinstance(summary, dict):
        return summary
    return {
        "schema_version": "ranking_feature_leakage_gate_v1",
        "status": "REJECT",
        "checked_rows": 0,
        "reasons": ["missing_leakage_gate_summary"],
    }


def _not_applicable_feature_contract_gate() -> dict[str, Any]:
    return {
        "schema_version": "ranking_feature_contract_gate_v1",
        "status": "NOT_APPLICABLE",
        "checked_rows": 0,
        "checked_feature_count": 0,
        "reasons": ["ltr_model_disabled"],
    }


def _not_applicable_leakage_gate() -> dict[str, Any]:
    return {
        "schema_version": "ranking_feature_leakage_gate_v1",
        "status": "NOT_APPLICABLE",
        "checked_rows": 0,
        "reasons": ["ltr_model_disabled"],
    }


def _baseline_status() -> dict[str, Any]:
    return {
        "status": "BASELINE",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": ["same_run_baseline"],
        "metric_delta": {},
    }


def _row_is_valid(row: dict[str, Any]) -> bool:
    strict_status = row.get("strict_status", {})
    return row.get("status") == "VALID" and strict_status.get("status") != "INVALID/STOP" and bool(row.get("frozen_candidate_comparison", {}).get("match"))


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 1.28 Lightweight Learned Ranker Same-run Comparison",
        "",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Baseline variant: `{comparison['baseline_variant']}`",
        f"- LTR variants: {', '.join(comparison['ltr_variants'])}",
        f"- Freeze fields: {', '.join(comparison['freeze_fields'])}",
        f"- All variants valid: `{comparison['all_variants_valid']}`",
        "- Promotion rule: lightweight LTR is diagnostic-only in Phase 1.28; it cannot promote from LOPO training evidence.",
        "",
        "| variant | status | strict_status | promotable | hit_rate_at_k | ndcg_at_k | mrr_at_k | frozen_match | drift |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for variant_name, row in comparison["variants"].items():
        metrics = row["metrics"]
        strict_status = row.get("strict_status", {})
        drift = ", ".join(row["drift"].keys()) if row["drift"] else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    variant_name,
                    row["status"],
                    str(strict_status.get("status")),
                    str(strict_status.get("promotable")),
                    str(metrics.get("hit_rate_at_k")),
                    str(metrics.get("ndcg_at_k")),
                    str(metrics.get("mrr_at_k")),
                    str(row.get("frozen_candidate_comparison", {}).get("match")),
                    drift,
                ]
            )
            + " |"
        )
    lines.extend(["", "## LTR training gates", ""])
    for variant_name, training in comparison["ltr_training"].items():
        training_metrics = training["metrics"]
        lines.append(f"### {variant_name}")
        lines.append("")
        lines.append(f"- feature_contract_gate: `{training_metrics.get('feature_contract_gate', {}).get('status')}`")
        lines.append(f"- leakage_gate: `{training_metrics.get('leakage_gate', {}).get('status')}`")
        lines.append(f"- model_path: `{training['model_path']}`")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
