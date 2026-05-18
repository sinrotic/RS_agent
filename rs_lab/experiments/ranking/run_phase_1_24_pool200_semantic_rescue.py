from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import write_json
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS, METRIC_FIELDS, _status_and_drift

DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_1_24_pool200_semantic_near_miss_rescue"
VARIANTS = [
    (
        "no_rerank_baseline",
        ROOT / "configs/ranking/phase_1_23/phase_1_23_pool200_no_rerank_baseline.yaml",
    ),
    (
        "semantic_near_miss_rescue",
        ROOT / "configs/ranking/phase_1_24/phase_1_24_pool200_semantic_near_miss_rescue.yaml",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.24 same-run pool200 semantic near-miss rescue comparison.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for same-run artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_freeze: dict[str, Any] | None = None
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
        freeze = _freeze_values(metrics)
        if variant_name == "no_rerank_baseline":
            baseline_freeze = freeze
        status, drift = _status_and_drift(freeze, baseline_freeze)
        variants[variant_name] = {
            "status": status,
            "drift": drift,
            "config_path": str(config_path),
            "output_dir": str(variant_output_dir),
            "metrics_path": result["metrics_path"],
            "recommendations_path": result["recommendations_path"],
            "ranking_cases_path": result["ranking_cases_path"],
            "ranking_case_summary_path": result["ranking_case_summary_path"],
            "report_path": result["report_path"],
            "frozen_candidates_path": frozen_candidates_path,
            "frozen_candidates_exported": bool(frozen_candidates_path and Path(frozen_candidates_path).exists()),
            "metrics": {key: metrics.get(key) for key in METRIC_FIELDS},
        }

    comparison = {
        "phase": "phase_1_24_pool200_semantic_near_miss_rescue",
        "limit_users": args.limit_users,
        "output_dir": str(output_dir),
        "freeze_fields": FREEZE_FIELDS,
        "baseline_variant": "no_rerank_baseline",
        "baseline_freeze": baseline_freeze,
        "all_variants_valid": all(row["status"] == "VALID" for row in variants.values()),
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


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 1.24 Pool200 Semantic Near-miss Rescue Same-run Comparison",
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
