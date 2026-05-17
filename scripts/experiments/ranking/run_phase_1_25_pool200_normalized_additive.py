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
from scripts.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, _status_and_drift

METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]

DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_25_pool200_normalized_additive"
VARIANTS = [
    (
        "same_run_baseline",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml",
    ),
    (
        "source_signal_0_2",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_source_signal_0_2.yaml",
    ),
    (
        "source_signal_0_4",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_source_signal_0_4.yaml",
    ),
    (
        "item_feature_0_2",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_item_feature_0_2.yaml",
    ),
    (
        "item_feature_0_4",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_item_feature_0_4.yaml",
    ),
    (
        "balanced_source_item_0_2",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_balanced_source_item_0_2.yaml",
    ),
    (
        "freshness_quality_0_1",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_freshness_quality_0_1.yaml",
    ),
    (
        "near_miss_tiebreak_0_05",
        ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_near_miss_tiebreak_0_05.yaml",
    ),
]


_PHASE = "phase_1_25_pool200_normalized_additive"
_BASELINE_VARIANT = "same_run_baseline"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.25 same-run pool200 normalized-additive ranking comparison.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for same-run artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    feature_contract = build_ranking_feature_contract()
    baseline_freeze: dict[str, Any] | None = None
    baseline_metrics: dict[str, Any] | None = None
    baseline_frozen_rows: list[dict[str, Any]] | None = None
    variants: dict[str, dict[str, Any]] = {}
    for variant_name, config_path in VARIANTS:
        variant_output_dir = output_dir / variant_name
        result = run_hybrid_demo(
            config_path,
            limit_users=args.limit_users,
            config_overrides={
                "output_dir": str(variant_output_dir),
                "report_path": str(variant_output_dir / "report.md"),
                "export_frozen_candidates": True,
            },
        )
        metrics = result["metrics"]
        frozen_candidates_path = result.get("frozen_candidates_path") or metrics.get("frozen_candidates_path")
        if not frozen_candidates_path or not Path(frozen_candidates_path).exists():
            raise ValueError(f"{variant_name} did not export frozen_candidates.jsonl")
        frozen_rows = read_jsonl(frozen_candidates_path)
        freeze = _freeze_values(metrics)
        if variant_name == _BASELINE_VARIANT:
            baseline_freeze = freeze
            baseline_metrics = metrics
            baseline_frozen_rows = frozen_rows
        if baseline_frozen_rows is None or baseline_metrics is None:
            raise ValueError("same_run_baseline must run before Phase 1.25 variants")
        status, drift = _status_and_drift(freeze, baseline_freeze)
        freeze_comparison = compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows)
        ltr_enabled = bool((metrics.get("config_summary") or {}).get("ltr_model", {}).get("enabled", False))
        feature_contract_gate_summary = _ranking_feature_contract_gate_summary(metrics, ltr_enabled)
        leakage_gate_summary = _ranking_leakage_gate_summary(metrics, ltr_enabled)
        strict_status = _baseline_status() if variant_name == _BASELINE_VARIANT else strict_ranking_promotion_status(
            baseline_metrics,
            metrics,
            freeze_comparison,
            ltr_enabled=ltr_enabled,
            feature_contract_gate_summary=feature_contract_gate_summary,
            leakage_gate_summary=leakage_gate_summary,
        )
        if status == "INVALID" and "freeze_metric_drift" not in strict_status["reasons"]:
            strict_status = strict_status | {"status": "INVALID/STOP", "promotable": False, "diagnostic_only": True, "reasons": [*strict_status["reasons"], "freeze_metric_drift"]}
        registry_entry = build_ranking_experiment_registry_entry(
            experiment_id=f"{_PHASE}:{variant_name}",
            config=metrics.get("config_summary", {}) | {"strategy_name": variant_name},
            frozen_rows=frozen_rows,
            metrics=metrics,
            status=strict_status,
            feature_contract=feature_contract,
            feature_contract_gate_summary=feature_contract_gate_summary,
            leakage_gate_summary=leakage_gate_summary,
        )
        variants[variant_name] = {
            "status": status,
            "strict_status": strict_status,
            "ranking_experiment_registry": registry_entry,
            "drift": drift,
            "frozen_candidate_comparison": freeze_comparison,
            "config_path": str(config_path),
            "output_dir": str(variant_output_dir),
            "metrics_path": result["metrics_path"],
            "recommendations_path": result["recommendations_path"],
            "ranking_cases_path": result["ranking_cases_path"],
            "ranking_case_summary_path": result["ranking_case_summary_path"],
            "report_path": result["report_path"],
            "frozen_candidates_path": frozen_candidates_path,
            "frozen_candidates_exported": True,
            "metrics": {key: metrics.get(key) for key in METRIC_FIELDS},
        }

    comparison = {
        "phase": _PHASE,
        "limit_users": args.limit_users,
        "output_dir": str(output_dir),
        "freeze_fields": FREEZE_FIELDS,
        "baseline_variant": _BASELINE_VARIANT,
        "baseline_freeze": baseline_freeze,
        "all_variants_valid": all(_row_is_valid(row) for row in variants.values()),
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in variants.values()],
        "variants": variants,
    }
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _ranking_feature_contract_gate_summary(metrics: dict[str, Any], ltr_enabled: bool) -> dict[str, Any]:
    if not ltr_enabled:
        return {
            "schema_version": "ranking_feature_contract_gate_v1",
            "status": "NOT_APPLICABLE",
            "checked_rows": 0,
            "checked_feature_count": 0,
            "reasons": ["ltr_model_disabled"],
        }
    summary = ((metrics.get("ltr_training") or {}).get("feature_contract_gate") or metrics.get("feature_contract_gate"))
    if isinstance(summary, dict):
        return summary
    return {
        "schema_version": "ranking_feature_contract_gate_v1",
        "status": "REJECT",
        "checked_rows": 0,
        "checked_feature_count": 0,
        "reasons": ["missing_feature_contract_gate_summary"],
    }


def _ranking_leakage_gate_summary(metrics: dict[str, Any], ltr_enabled: bool) -> dict[str, Any]:
    if not ltr_enabled:
        return {
            "schema_version": "ranking_feature_leakage_gate_v1",
            "status": "NOT_APPLICABLE",
            "checked_rows": 0,
            "reasons": ["ltr_model_disabled"],
        }
    summary = ((metrics.get("ltr_training") or {}).get("leakage_gate") or metrics.get("leakage_gate"))
    if isinstance(summary, dict):
        return summary
    return {
        "schema_version": "ranking_feature_leakage_gate_v1",
        "status": "REJECT",
        "checked_rows": 0,
        "reasons": ["missing_leakage_gate_summary"],
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
        "# Phase 1.25 Pool200 Normalized-additive Same-run Comparison",
        "",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Baseline variant: `{comparison['baseline_variant']}`",
        f"- Freeze fields: {', '.join(comparison['freeze_fields'])}",
        f"- All variants valid: `{comparison['all_variants_valid']}`",
        "- LTR promotion: disabled; any LTR-enabled row is diagnostic-only.",
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
    lines.extend(["", "## Frozen candidate signatures", ""])
    for variant_name, row in comparison["variants"].items():
        signature = row.get("frozen_candidate_comparison", {}).get("variant", {})
        lines.append(f"### {variant_name}")
        lines.append("")
        lines.append(f"- hash: `{signature.get('hash')}`")
        lines.append(f"- user_count: {signature.get('user_count')}")
        lines.append(f"- candidate_count: {signature.get('candidate_count')}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
