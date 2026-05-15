from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.config import load_config
from rs_core.common.io import read_jsonl, write_json
from rs_core.recsys.evaluation import build_ranking_experiment_registry_entry, build_ranking_feature_contract, compare_frozen_candidate_signatures, frozen_candidate_artifact, inspect_ranking_run_artifacts
from rs_core.workflow.hybrid_demo import run_hybrid_demo

DEFAULT_OUTPUT_DIR = ROOT / "outputs/phase_1_23_pool200_ranking_isolation"
FREEZE_FIELDS = [
    "users_with_holdout",
    "candidate_hit_users",
    "candidate_hit_rate_at_pool",
    "candidate_count_avg",
    "fallback_rate",
]
VARIANTS = [
    (
        "no_rerank_baseline",
        ROOT / "configs/phase_1_23_pool200_no_rerank_baseline.yaml",
    ),
    (
        "ranking_v2",
        ROOT / "configs/phase_1_23_pool200_ranking_v2.yaml",
    ),
    (
        "item_feature_rerank",
        ROOT / "configs/phase_1_23_pool200_item_feature_rerank.yaml",
    ),
    (
        "source_aware_fusion",
        ROOT / "configs/phase_1_23_pool200_source_aware_fusion.yaml",
    ),
]
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "recall_at_pool",
    *FREEZE_FIELDS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.23 same-run pool200 ranking isolation comparison.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for same-run artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    feature_contract = build_ranking_feature_contract()
    baseline_freeze: dict[str, Any] | None = None
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
        if variant_name == "no_rerank_baseline":
            baseline_freeze = freeze
            baseline_frozen_rows = frozen_rows
        if baseline_frozen_rows is None:
            raise ValueError("no_rerank_baseline must run before Phase 1.23 variants")
        status, drift = _status_and_drift(freeze, baseline_freeze)
        freeze_comparison = compare_frozen_candidate_signatures(baseline_frozen_rows, frozen_rows)
        registry_entry = build_ranking_experiment_registry_entry(
            experiment_id=f"phase_1_23_pool200_ranking_isolation:{variant_name}",
            config=metrics.get("config_summary", {}) | {"strategy_name": variant_name},
            frozen_rows=frozen_rows,
            metrics=metrics,
            status=_baseline_status() if variant_name == "no_rerank_baseline" else _variant_status(status, drift, freeze_comparison),
            feature_contract=feature_contract,
        )
        variants[variant_name] = {
            "status": status,
            "strict_status": registry_entry["status"],
            "drift": drift,
            "frozen_candidate_comparison": freeze_comparison,
            "ranking_experiment_registry": registry_entry,
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

    batch0_artifact = _batch0_pool200_artifact(args.limit_users, baseline_freeze, baseline_frozen_rows or [], variants)
    comparison = {
        "phase": "phase_1_23_pool200_ranking_isolation",
        "limit_users": args.limit_users,
        "output_dir": str(output_dir),
        "freeze_fields": FREEZE_FIELDS,
        "baseline_variant": "no_rerank_baseline",
        "baseline_freeze": baseline_freeze,
        "batch0_pool200_artifact": batch0_artifact,
        "ranking_experiment_registry": [row["ranking_experiment_registry"] for row in variants.values()],
        "artifact_inspection": inspect_ranking_run_artifacts(_inspection_rows(variants)),
        "all_variants_valid": all(row["status"] == "VALID" and row["frozen_candidate_comparison"]["match"] for row in variants.values()),
        "variants": variants,
    }
    write_json(output_dir / "batch0_pool200_artifact.json", batch0_artifact)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md"), "batch0_artifact_path": str(output_dir / "batch0_pool200_artifact.json")}, ensure_ascii=False, indent=2))


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


def _freeze_values(metrics: dict[str, Any]) -> dict[str, Any]:
    return {field: metrics.get(field) for field in FREEZE_FIELDS}


def _status_and_drift(freeze: dict[str, Any], baseline_freeze: dict[str, Any] | None) -> tuple[str, dict[str, dict[str, Any]]]:
    if baseline_freeze is None:
        return "INVALID", {field: {"baseline": None, "current": freeze.get(field)} for field in FREEZE_FIELDS}
    drift = {
        field: {"baseline": baseline_freeze.get(field), "current": freeze.get(field)}
        for field in FREEZE_FIELDS
        if freeze.get(field) != baseline_freeze.get(field)
    }
    return ("INVALID" if drift else "VALID", drift)


def _baseline_status() -> dict[str, Any]:
    return {
        "status": "BASELINE",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": ["batch0_pool200_frozen_baseline"],
        "metric_delta": {},
    }


def _variant_status(status: str, drift: dict[str, dict[str, Any]], freeze_comparison: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    if status != "VALID":
        reasons.append("freeze_metric_drift")
    if not freeze_comparison.get("match"):
        reasons.append("frozen_candidate_hash_drift")
    return {
        "status": "VALID_DIAGNOSTIC" if not reasons else "INVALID/STOP",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": reasons or ["phase_1_23_batch0_diagnostic_only"],
        "drift": drift,
    }


def _batch0_pool200_artifact(
    limit_users: int | None,
    baseline_freeze: dict[str, Any] | None,
    baseline_frozen_rows: list[dict[str, Any]],
    variants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    baseline_config = load_config(ROOT / "configs/phase_1_23_pool200_no_rerank_baseline.yaml")
    fixed_recall_config = load_config(ROOT / "configs/phase_1_21_recall_coverage_pool200_experimental.yaml")
    baseline_artifact = frozen_candidate_artifact(baseline_frozen_rows)
    return {
        "schema_version": "pool200_batch0_artifact_v1",
        "phase": "phase_1_23_pool200_ranking_isolation",
        "role": "batch0_frozen_pool200_baseline",
        "candidate_pool_size": int(baseline_config["candidate_pool_size"]),
        "top_k": int(baseline_config["top_k"]),
        "limit_users": limit_users,
        "dataset": {
            "clean_dir": baseline_config["clean_dir"],
            "views_dir": baseline_config["views_dir"],
            "evaluation_mode": baseline_config.get("evaluation_mode", "valid_test"),
            "hit_rate_denominator": fixed_recall_config.get("hit_rate_denominator"),
            "expected_users_with_holdout": fixed_recall_config.get("expected_users_with_holdout"),
        },
        "split_metadata": {
            "train_path": str(Path(baseline_config["clean_dir"]) / "canonical_interactions.train.jsonl"),
            "valid_path": str(Path(baseline_config["clean_dir"]) / "canonical_interactions.valid.jsonl"),
            "test_path": str(Path(baseline_config["clean_dir"]) / "canonical_interactions.test.jsonl"),
            "evaluation_splits": ["valid", "test"],
            "candidate_generation_split": "train_recall_views",
        },
        "frozen_candidate_artifact": baseline_artifact,
        "baseline_freeze": baseline_freeze,
        "baseline_frozen_candidates_path": variants["no_rerank_baseline"]["frozen_candidates_path"],
        "promotion_scope": "ranking_on_frozen_pool200_recall_candidates_only",
        "pool100_reuse_policy": {
            "reusable_for_pool200_promotion": False,
            "reason": "pool100 historical evidence has a different candidate_pool_size boundary and cannot promote pool200 ranking experiments.",
        },
        "recall_semantics_contract": {
            "fixed_recall_config_path": "configs/phase_1_21_recall_coverage_pool200_experimental.yaml",
            "preserve_recall_settings": True,
            "ranking_variants_must_match_frozen_hash": True,
        },
        "variant_hashes": {
            name: row["ranking_experiment_registry"]["frozen_candidate_artifact"]["hash"]
            for name, row in variants.items()
        },
    }


def _inspection_rows(variants: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, (variant_name, row) in enumerate(variants.items()):
        rows.append(
            {
                "run_index": index,
                "candidate_id": variant_name,
                "lane": "baseline" if variant_name == "no_rerank_baseline" else "diagnostic",
                "promotion_eligible": False,
                "diagnostic_only": True,
                **row,
            }
        )
    return rows


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 1.23 Pool200 Ranking Isolation Same-run Comparison",
        "",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Baseline variant: `{comparison['baseline_variant']}`",
        f"- Freeze fields: {', '.join(comparison['freeze_fields'])}",
        f"- All variants valid: `{comparison['all_variants_valid']}`",
        "",
        "| variant | status | hit_rate_at_k | ndcg_at_k | mrr_at_k | frozen_candidates | drift |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for variant_name, row in comparison["variants"].items():
        metrics = row["metrics"]
        drift = ", ".join(row["drift"].keys()) if row["drift"] else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    variant_name,
                    row["status"],
                    str(metrics.get("hit_rate_at_k")),
                    str(metrics.get("ndcg_at_k")),
                    str(metrics.get("mrr_at_k")),
                    f"`{row.get('frozen_candidates_path')}`" if row.get("frozen_candidates_path") else "MISSING",
                    drift,
                ]
            )
            + " |"
        )
    lines.extend(["", "## Freeze field values", ""])
    for variant_name, row in comparison["variants"].items():
        lines.append(f"### {variant_name}")
        lines.append("")
        for field in comparison["freeze_fields"]:
            lines.append(f"- {field}: {row['metrics'].get(field)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
