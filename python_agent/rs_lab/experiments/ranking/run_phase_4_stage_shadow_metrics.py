from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from math import log2
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_jsonl, write_json
from rs_core.offline.evaluation.ranking import build_ranking_feature_contract, inspect_ranking_run_artifacts
from rs_core.workflow.hybrid_demo import run_hybrid_demo
from rs_core.workflow.ranking_experiments import (
    REQUIRED_CANDIDATE_POOL_SIZE,
    REQUIRED_TOP_K,
    RankingMethodSpec,
    build_ranking_method_registry_entry_from_spec,
    build_ranking_run_row,
    public_ranking_run_row,
)
from rs_lab.experiments.ranking.run_phase_1_23_pool200_ranking_isolation import FREEZE_FIELDS
from rs_lab.experiments.ranking.run_phase_1_26_real_ranking_experiments import (
    _not_applicable_feature_contract_gate,
    _not_applicable_leakage_gate,
    _read_frozen_rows,
)
from rs_lab.experiments.ranking.run_phase_2_fine_rank_algorithm_batch import PHYSICAL_PIPELINE_OVERRIDE

_PHASE = "phase_4_stage_shadow_metrics"
_BASELINE_METHOD_ID = "same_run_pool200_baseline"
_SHADOW_METHOD_ID = "coarse_shadow_retention_diagnostic"
BASELINE_CONFIG = ROOT / "configs/ranking/phase_1_25/phase_1_25_pool200_same_run_baseline.yaml"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_4_stage_shadow_metrics"
DEFAULT_SEED = 20260513
WEAK_CUTOFFS = [10, 20]
COARSE_SHADOW_CUTOFFS = [50, 100]
METRIC_FIELDS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    *FREEZE_FIELDS,
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 4 weak metrics and coarse shadow diagnostics on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase 4 artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in Phase 4 artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison = run_phase_4_stage_shadow_metrics(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    write_json(output_dir / "comparison.json", comparison)
    _write_report(output_dir / "comparison.md", comparison)
    print(json.dumps({"comparison_path": str(output_dir / "comparison.json"), "report_path": str(output_dir / "comparison.md")}, ensure_ascii=False, indent=2))


def run_phase_4_stage_shadow_metrics(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    feature_contract = build_ranking_feature_contract()
    run_id = _run_id()
    command_text = _command_text(output_dir, limit_users, seed)
    method_specs = build_method_specs()
    baseline_row = _run_baseline(output_dir, limit_users, feature_contract, method_specs[0], run_id, command_text)
    shadow_row = _build_shadow_row(output_dir, method_specs[1], baseline_row, run_id, command_text)
    runnable_rows = [baseline_row, shadow_row]
    runs = [public_ranking_run_row(row) for row in runnable_rows]
    method_registry = [_method_registry_entry(row) for row in runnable_rows]
    ranking_registry = [row["ranking_experiment_registry"] for row in runnable_rows]

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
        "stage_main_lane_matrix": _stage_main_lane_matrix(),
        "promotion_boundary": _promotion_boundary(),
        "method_registry": method_registry,
        "ranking_experiment_registry": ranking_registry,
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
                "weak_metrics_path",
                "coarse_shadow_diagnostics_path",
            ],
        ),
        "weak_metrics": shadow_row["weak_metrics"],
        "coarse_shadow_diagnostics": shadow_row["coarse_shadow_diagnostics"],
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
            method_id=_SHADOW_METHOD_ID,
            method_family="stage_shadow_diagnostics",
            stage_target="coarse",
            requires_training=False,
            requires_gpu=False,
            dependency=None,
            promotion_lane="phase_4_shadow_diagnostic_only",
            blocked_recovery_condition="shadow diagnostics must be replaced by a verified served stage and valid/test promotion gate before challenger use",
            promotion_eligible=False,
            diagnostic_only=True,
            metadata={
                "shadow_only": True,
                "does_not_crop_candidates": True,
                "coarse_shadow_cutoffs": COARSE_SHADOW_CUTOFFS,
                "weak_metric_cutoffs": WEAK_CUTOFFS,
            },
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


def _build_shadow_row(output_dir: Path, method_spec: RankingMethodSpec, baseline_row: dict[str, Any], run_id: str, command_text: str) -> dict[str, Any]:
    diagnostics_dir = output_dir / method_spec.method_id
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    ranking_cases = read_jsonl(baseline_row["ranking_cases_path"])
    stage_trace_rows = read_jsonl(baseline_row["ranking_stage_trace_path"])
    users_with_holdout = int(baseline_row["raw_metrics"].get("users_with_holdout", 0) or 0)
    weak_metrics = _weak_ranking_metrics(ranking_cases, stage_trace_rows, users_with_holdout)
    coarse_shadow = _coarse_shadow_diagnostics(ranking_cases, stage_trace_rows)
    weak_metrics_path = diagnostics_dir / "weak_metrics.json"
    coarse_shadow_path = diagnostics_dir / "coarse_shadow_diagnostics.json"
    write_json(weak_metrics_path, weak_metrics)
    write_json(coarse_shadow_path, coarse_shadow)
    metrics = {key: baseline_row["raw_metrics"].get(key) for key in METRIC_FIELDS} | weak_metrics | coarse_shadow
    status = {
        "status": "PARTIAL diagnostic-only",
        "promotable": False,
        "diagnostic_only": True,
        "reasons": ["weak_metrics_are_diagnostic_only", "coarse_shadow_does_not_crop_or_mutate_candidates", "valid_test_promotion_evidence_missing"],
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
        metrics=metrics,
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
            "weak_metrics_path": str(weak_metrics_path),
            "coarse_shadow_diagnostics_path": str(coarse_shadow_path),
            "diagnostic_source_metrics_path": baseline_row.get("metrics_path"),
            "diagnostic_source_stage_trace_path": baseline_row.get("ranking_stage_trace_path"),
            "adapter_execution": "not_run_shadow_read_only_diagnostics",
            "promotion_evidence_claim": "none",
        },
        feature_contract=build_ranking_feature_contract(),
        feature_contract_gate_summary=_not_applicable_feature_contract_gate(),
        leakage_gate_summary=_not_applicable_leakage_gate(),
        command_text=command_text,
    )
    row["raw_metrics"] = baseline_row["raw_metrics"]
    row["frozen_rows"] = baseline_row["frozen_rows"]
    row["weak_metrics"] = weak_metrics
    row["coarse_shadow_diagnostics"] = coarse_shadow
    return row


def _weak_ranking_metrics(ranking_cases: list[dict[str, Any]], stage_trace_rows: list[dict[str, Any]], users_with_holdout: int) -> dict[str, Any]:
    denominator = users_with_holdout or len({str(row.get("user_id", "")) for row in ranking_cases if row.get("user_id")})
    cases_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    input_counts = _input_candidate_counts(stage_trace_rows)
    target_ranks: list[int] = []
    target_percentiles: list[float] = []
    for row in ranking_cases:
        user_id = str(row.get("user_id", ""))
        if not user_id:
            continue
        cases_by_user[user_id].append(row)
        rank = _positive_int(row.get("target_rank"))
        if rank is None:
            continue
        target_ranks.append(rank)
        input_count = input_counts.get(user_id) or REQUIRED_CANDIDATE_POOL_SIZE
        target_percentiles.append(round(rank / input_count, 6) if input_count else 0.0)

    metrics: dict[str, Any] = {
        "schema_version": "phase_4_weak_ranking_metrics_v1",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "denominator": denominator,
        "denominator_source": "users_with_holdout" if users_with_holdout else "ranking_case_users",
        "target_case_count": len(ranking_cases),
        "target_rank_min": min(target_ranks) if target_ranks else None,
        "target_rank_mean": _mean(target_ranks),
        "target_rank_median": _median(target_ranks),
        "target_rank_p90": _percentile(target_ranks, 0.9),
        "target_rank_percentile_mean": _mean(target_percentiles),
        "target_rank_percentile_median": _median(target_percentiles),
        "missed_top5_but_hit_top20_users": _missed_top5_but_hit_top20_users(cases_by_user),
    }
    for cutoff in WEAK_CUTOFFS:
        hit_users = sum(1 for rows in cases_by_user.values() if any((_positive_int(row.get("target_rank")) or 10**9) <= cutoff for row in rows))
        ndcg_values = [_user_ndcg_at(rows, cutoff) for rows in cases_by_user.values()]
        zero_fill_count = max(0, denominator - len(ndcg_values))
        metrics[f"hit_at_{cutoff}"] = hit_users
        metrics[f"hit_rate_at_{cutoff}"] = round(hit_users / denominator, 6) if denominator else 0.0
        metrics[f"ndcg_at_{cutoff}"] = round((sum(ndcg_values) + 0.0 * zero_fill_count) / denominator, 6) if denominator else 0.0
    return metrics


def _coarse_shadow_diagnostics(ranking_cases: list[dict[str, Any]], stage_trace_rows: list[dict[str, Any]]) -> dict[str, Any]:
    trace_by_key = {(str(row.get("user_id", "")), str(row.get("item_id", ""))): row for row in stage_trace_rows}
    target_rows = []
    for row in ranking_cases:
        key = (str(row.get("user_id", "")), str(row.get("target_item", "")))
        trace_row = trace_by_key.get(key, {})
        coarse_rank = _positive_int(row.get("target_coarse_rank")) or _positive_int(trace_row.get("coarse_rank"))
        target_rows.append({
            "user_id": row.get("user_id"),
            "target_item": row.get("target_item"),
            "target_rank": row.get("target_rank"),
            "coarse_shadow_rank": coarse_rank,
            "coarse_shadow_score": row.get("target_coarse_score", trace_row.get("coarse_score")),
            "final_rank": row.get("target_final_rank", trace_row.get("final_rank")),
            "final_score": row.get("target_final_score", trace_row.get("final_score")),
            "retained_at_50": coarse_rank is not None and coarse_rank <= 50,
            "retained_at_100": coarse_rank is not None and coarse_rank <= 100,
        })
    denominator = len(target_rows)
    diagnostics: dict[str, Any] = {
        "schema_version": "phase_4_coarse_shadow_diagnostics_v1",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "shadow_only": True,
        "does_not_crop_or_mutate_candidates": True,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "target_case_count": denominator,
        "target_positions_sample": target_rows[:20],
    }
    for cutoff in COARSE_SHADOW_CUTOFFS:
        retained = sum(1 for row in target_rows if row["coarse_shadow_rank"] is not None and row["coarse_shadow_rank"] <= cutoff)
        dropped = sum(1 for row in target_rows if row["coarse_shadow_rank"] is None or row["coarse_shadow_rank"] > cutoff)
        diagnostics[f"coarse_retention_at_{cutoff}"] = round(retained / denominator, 6) if denominator else 0.0
        diagnostics[f"would_drop_positive_at_{cutoff}"] = dropped
        diagnostics[f"would_drop_positive_users_at_{cutoff}"] = len({row["user_id"] for row in target_rows if row["coarse_shadow_rank"] is None or row["coarse_shadow_rank"] > cutoff})
    return diagnostics


def _input_candidate_counts(stage_trace_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {}
    for row in stage_trace_rows:
        user_id = str(row.get("user_id", ""))
        if user_id and user_id not in counts:
            counts[user_id] = int(row.get("input_candidate_count", 0) or 0)
    return counts


def _missed_top5_but_hit_top20_users(cases_by_user: dict[str, list[dict[str, Any]]]) -> int:
    count = 0
    for rows in cases_by_user.values():
        best_rank = min((_positive_int(row.get("target_rank")) or 10**9 for row in rows), default=10**9)
        if REQUIRED_TOP_K < best_rank <= 20:
            count += 1
    return count


def _user_ndcg_at(rows: list[dict[str, Any]], cutoff: int) -> float:
    ranks = sorted(rank for rank in (_positive_int(row.get("target_rank")) for row in rows) if rank is not None and rank <= cutoff)
    if not ranks:
        return 0.0
    dcg = sum(1.0 / log2(rank + 1) for rank in ranks)
    ideal_hits = min(len(rows), cutoff)
    ideal_dcg = sum(1.0 / log2(index + 1) for index in range(1, ideal_hits + 1))
    return round(dcg / ideal_dcg, 6) if ideal_dcg else 0.0


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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
        "weak_metrics_path": result["metrics_path"],
        "coarse_shadow_diagnostics_path": result.get("ranking_stage_summary_path") or (metrics.get("ranking_stage_artifact_paths") or {}).get("summary"),
        "frozen_candidates_exported": True,
        "ranking_stage_artifacts_exported": True,
        "physical_ranking_pipeline": PHYSICAL_PIPELINE_OVERRIDE,
    }


def _method_registry_entry(row: dict[str, Any]) -> dict[str, Any]:
    method_payload = {key: value for key, value in row["method_spec"].items() if key != "schema_version"}
    return build_ranking_method_registry_entry_from_spec(
        RankingMethodSpec(**method_payload),
        run_kind=str(row["run_kind"]),
        reasons=row.get("strict_status", {}).get("reasons", []),
        champion_id=_BASELINE_METHOD_ID if row["run_kind"] == "baseline" else None,
        challenger_of=_BASELINE_METHOD_ID if row["run_kind"] != "baseline" else None,
        dependency_status="not_required",
    )


def _registry_config(metrics: dict[str, Any], strategy_name: str) -> dict[str, Any]:
    config = dict(metrics.get("config_summary", {}) or {})
    config["strategy_name"] = strategy_name
    config["candidate_pool_size"] = metrics.get("candidate_pool_size") or config.get("candidate_pool_size") or REQUIRED_CANDIDATE_POOL_SIZE
    config["top_k"] = metrics.get("top_k") or config.get("top_k") or REQUIRED_TOP_K
    config["physical_ranking_pipeline"] = PHYSICAL_PIPELINE_OVERRIDE
    config["export_ranking_stage_artifacts"] = True
    return config


def _stage_main_lane_matrix() -> list[dict[str, Any]]:
    return [
        {"stage": "coarse", "main_lane": "pass_through_pool200", "shadow_lane": _SHADOW_METHOD_ID, "candidate_scope": "full_pool200", "candidate_mutation": False, "diagnostics": ["coarse_score", "coarse_rank", "coarse_retention_at_50", "coarse_retention_at_100"]},
        {"stage": "fine", "main_lane": "existing_fine_rank_full_pool200_scoring", "shadow_lane": None, "candidate_scope": "full_pool200", "candidate_mutation": False, "diagnostics": ["hit_rate_at_10", "hit_rate_at_20", "ndcg_at_10", "ndcg_at_20"]},
        {"stage": "rerank", "main_lane": "existing_rerank_top5", "shadow_lane": None, "candidate_scope": "top_k", "top_k": REQUIRED_TOP_K, "candidate_mutation": False, "diagnostics": ["target_rank", "target_rank_percentile", "missed_top5_but_hit_top20_users"]},
        {"stage": "future-online", "main_lane": "not_current_offline_evidence", "shadow_lane": None, "candidate_scope": "not_applicable", "candidate_mutation": False, "promotion_eligible": False, "diagnostics": []},
    ]


def _promotion_boundary() -> dict[str, Any]:
    return {
        "frozen_pool200_required": True,
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "recall_semantics_changed": False,
        "merge_for_user_changed": False,
        "coarse_shadow_does_not_crop_or_mutate_candidates": True,
        "weak_metrics_diagnostic_only": True,
        "promotion_eligible": False,
        "online_metrics_forbidden_as_current_offline_evidence": True,
    }


def _command_text(output_dir: Path, limit_users: int | None, seed: int) -> str:
    parts = ["./.venv/Scripts/python.exe", "rs_lab/experiments/ranking/run_phase_4_stage_shadow_metrics.py", "--output-dir", str(output_dir), "--seed", str(seed)]
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


def _mean(values: list[int] | list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _median(values: list[int] | list[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    rows = sorted(values)
    index = min(len(rows) - 1, max(0, int(round((len(rows) - 1) * percentile))))
    return float(rows[index])


def _write_report(path: Path, comparison: dict[str, Any]) -> None:
    lines = [
        "# Phase 4 Stage Shadow Metrics",
        "",
        f"- Run id: `{comparison['run_id']}`",
        f"- Output dir: `{comparison['output_dir']}`",
        f"- Seed: `{comparison['seed']}`",
        "- Scope: frozen pool200 / top_k=5; recall semantics and `merge_for_user()` are unchanged.",
        "- Promotion boundary: weak metrics and coarse shadow retention are diagnostic-only and cannot set promotion_eligible=true.",
        "",
        "## Runs",
        "",
        "| method | kind | family | stage | lane | status | promotion_eligible | diagnostic_only |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
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
                ]
            )
            + " |"
        )
    lines.extend(["", "## Weak metrics", ""])
    weak_metrics = comparison["weak_metrics"]
    for key in ["hit_rate_at_10", "hit_rate_at_20", "ndcg_at_10", "ndcg_at_20", "target_rank_mean", "target_rank_median", "missed_top5_but_hit_top20_users"]:
        lines.append(f"- `{key}`: `{weak_metrics.get(key)}`")
    lines.extend(["", "## Coarse shadow", ""])
    coarse_shadow = comparison["coarse_shadow_diagnostics"]
    for key in ["coarse_retention_at_50", "coarse_retention_at_100", "would_drop_positive_at_50", "would_drop_positive_at_100"]:
        lines.append(f"- `{key}`: `{coarse_shadow.get(key)}`")
    lines.extend(["", "## Stage main-lane matrix", ""])
    for row in comparison["stage_main_lane_matrix"]:
        lines.append(f"- `{row['stage']}`: main=`{row['main_lane']}`, shadow=`{row['shadow_lane']}`, candidate_mutation=`{row['candidate_mutation']}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
