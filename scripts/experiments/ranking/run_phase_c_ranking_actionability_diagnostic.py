from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import read_json, read_jsonl, write_json
from rs_core.workflow.ranking_experiments import REQUIRED_CANDIDATE_POOL_SIZE, REQUIRED_TOP_K, RankingMethodSpec
from scripts.experiments.ranking.run_phase_6_industrial_ranking_chain import (
    BASELINE_CONFIG,
    CURRENT_RECALL_MAINLINE_CONFIG,
    CURRENT_RECALL_MAINLINE_ID,
    _current_recall_mainline_summary,
    _promotion_boundary,
    build_method_specs as _phase_6_build_method_specs,
    run_phase_6_industrial_ranking_chain,
)

_PHASE = "phase_c_ranking_actionability_diagnostic"
_BASELINE_METHOD_ID = "same_run_pool200_baseline"
_DIAGNOSTIC_METHOD_ID = "phase_c_ranking_actionability_diagnostic"
_PHASE_6_DIAGNOSTIC_METHOD_ID = "industrial_coarse_fine_rerank_chain_diagnostic"
DEFAULT_OUTPUT_DIR = ROOT / "outputs/ranking/phase_c_ranking_actionability_diagnostic"
DEFAULT_SEED = 20260514
ONLINE_METRIC_NAMES = ["ctr", "cvr", "gmv", "p95", "slo", "agent_feedback"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Phase C ranking actionability diagnostics on frozen pool200 candidates.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Phase C artifacts.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick smoke run.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Deterministic seed recorded in artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_phase_c_ranking_actionability_diagnostic(output_dir=output_dir, limit_users=args.limit_users, seed=args.seed)
    report_path = output_dir / "ranking_actionability_report.json"
    write_json(report_path, report)
    print(json.dumps({"ranking_actionability_report_path": str(report_path)}, ensure_ascii=False, indent=2))


def build_method_specs() -> list[RankingMethodSpec]:
    specs_by_id = {spec.method_id: spec for spec in _phase_6_build_method_specs()}
    baseline = specs_by_id[_BASELINE_METHOD_ID]
    phase_6_diagnostic = specs_by_id[_PHASE_6_DIAGNOSTIC_METHOD_ID]
    return [
        baseline,
        RankingMethodSpec(
            method_id=_DIAGNOSTIC_METHOD_ID,
            method_family=phase_6_diagnostic.method_family,
            stage_target=phase_6_diagnostic.stage_target,
            requires_training=phase_6_diagnostic.requires_training,
            requires_gpu=phase_6_diagnostic.requires_gpu,
            dependency=phase_6_diagnostic.dependency,
            promotion_lane="phase_c_actionability_diagnostic",
            blocked_recovery_condition=phase_6_diagnostic.blocked_recovery_condition,
            promotion_eligible=False,
            diagnostic_only=True,
            metadata=phase_6_diagnostic.metadata | {"source_method_id": _PHASE_6_DIAGNOSTIC_METHOD_ID},
        ),
    ]


def _run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _run_baseline(output_dir: Path, limit_users: int | None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    comparison = run_phase_6_industrial_ranking_chain(output_dir=output_dir, limit_users=limit_users, seed=seed)
    return _runs_by_id(comparison)[_BASELINE_METHOD_ID]


def run_phase_c_ranking_actionability(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    return run_phase_c_ranking_actionability_diagnostic(output_dir=output_dir, limit_users=limit_users, seed=seed)


def run_phase_c_ranking_actionability_diagnostic(output_dir: Path, limit_users: int | None = None, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    comparison = run_phase_6_industrial_ranking_chain(output_dir=output_dir, limit_users=limit_users, seed=seed)
    write_json(output_dir / "comparison.json", comparison)
    runs_by_id = _runs_by_id(comparison)
    baseline = runs_by_id[_BASELINE_METHOD_ID]
    diagnostic = runs_by_id[_DIAGNOSTIC_METHOD_ID]
    baseline_cases = _safe_read_jsonl(baseline.get("ranking_cases_path"))
    diagnostic_cases = _safe_read_jsonl(diagnostic.get("ranking_cases_path"))
    diagnostic_frozen = _safe_read_jsonl(diagnostic.get("frozen_candidates_path"))
    baseline_trace = _safe_read_jsonl(baseline.get("ranking_stage_trace_path"))
    diagnostic_trace = _safe_read_jsonl(diagnostic.get("ranking_stage_trace_path"))
    diagnostic_stage_summary = _safe_read_json(diagnostic.get("ranking_stage_summary_path"))
    baseline_metrics = baseline.get("metrics", {})
    diagnostic_metrics = diagnostic.get("metrics", {})
    artifact_paths = _artifact_paths(output_dir, comparison, baseline, diagnostic)
    report_path = output_dir / "ranking_actionability_report.json"
    artifact_paths["ranking_actionability_report_path"] = str(report_path)

    report = {
        "phase": _PHASE,
        "run_id": comparison["run_id"],
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": seed,
        "limit_users": limit_users,
        "current_recall_mainline": _current_recall_mainline_summary(),
        "candidate_pool_size": REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k": REQUIRED_TOP_K,
        "actionability_status": _actionability_status(diagnostic, diagnostic_cases, diagnostic_trace),
        "promotion_boundary": _phase_c_promotion_boundary(),
        "evidence_boundary": _evidence_boundary(),
        "oracle_at_5": _oracle_at_5(diagnostic_metrics),
        "target_rank_percentile": _target_rank_percentile_summary(diagnostic_cases, diagnostic_trace),
        "candidate_hit_missed_topk_users": {
            "baseline": _int_metric(baseline_metrics, "candidate_hit_missed_topk_users"),
            "diagnostic": _int_metric(diagnostic_metrics, "candidate_hit_missed_topk_users"),
            "delta": _int_metric(diagnostic_metrics, "candidate_hit_missed_topk_users") - _int_metric(baseline_metrics, "candidate_hit_missed_topk_users"),
        },
        "source_exposure": _source_exposure(diagnostic_frozen, diagnostic_trace, diagnostic_cases),
        "duplicate_source_balance": _duplicate_source_balance(diagnostic_frozen, diagnostic_trace),
        "topk_displacement": _topk_displacement(baseline_trace, diagnostic_trace, diagnostic_cases),
        "win_tie_loss": _win_tie_loss(baseline_cases, diagnostic_cases),
        "guardrail_status": _guardrail_status(comparison, baseline, diagnostic, diagnostic_stage_summary),
        "online_metric_claims": _online_metric_claims(diagnostic_stage_summary),
        "artifact_paths": artifact_paths,
    }
    write_json(report_path, report)
    return report


def _runs_by_id(comparison: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {row["candidate_id"]: row for row in comparison["runs"]}
    if _DIAGNOSTIC_METHOD_ID not in rows and _PHASE_6_DIAGNOSTIC_METHOD_ID in rows:
        rows[_DIAGNOSTIC_METHOD_ID] = rows[_PHASE_6_DIAGNOSTIC_METHOD_ID] | {"candidate_id": _DIAGNOSTIC_METHOD_ID}
    return rows


def _actionability_status(diagnostic: dict[str, Any], ranking_cases: list[dict[str, Any]], stage_trace: list[dict[str, Any]]) -> dict[str, Any]:
    has_case_diagnostics = bool(ranking_cases)
    has_stage_trace = bool(stage_trace)
    reasons = ["frozen_pool200_ranker_actionability_diagnostics_ready"]
    if not has_case_diagnostics:
        reasons.append("no_target_case_rows_available_in_sample")
    if not has_stage_trace:
        reasons.append("ranking_stage_trace_missing_or_empty")
    return {
        "status": "READY_FOR_RANKING_ACTIONABILITY_REVIEW" if has_stage_trace else "PARTIAL_DIAGNOSTIC",
        "diagnostic_only": True,
        "promotion_eligible": False,
        "strict_status": diagnostic.get("strict_status", {}).get("status"),
        "reasons": reasons,
    }


def _phase_c_promotion_boundary() -> dict[str, Any]:
    return _promotion_boundary() | {
        "phase_c_actionability_report": True,
        "report_is_current_promotion_evidence": False,
        "online_ctr_cvr_gmv_p95_slo_agent_feedback_forbidden_as_current_promotion_evidence": True,
    }


def _evidence_boundary() -> dict[str, Any]:
    return {
        "allowed_current_evidence": [
            "frozen_pool200_offline_ranking_artifacts",
            "oracle_at_5_from_candidate_hit_rate_at_pool",
            "target_rank_percentile_diagnostics",
            "source_exposure_and_duplicate_balance_diagnostics",
            "same_run_win_tie_loss_against_current_baseline",
        ],
        "not_current_promotion_evidence": ONLINE_METRIC_NAMES,
        "promotion_claim": "none",
        "requires_before_promotion": ["valid_test_split_evidence", "multi_run_consistency", "adapter_contract", "explicit_promotion_gate_pass"],
    }


def _oracle_at_5(metrics: dict[str, Any]) -> dict[str, Any]:
    value = _float_metric(metrics, "candidate_hit_rate_at_pool")
    return {
        "definition": "Upper-bound hit_rate@5 if an oracle ranker could place any held-out positive already present in the frozen pool200 into Top-5.",
        "value": value,
        "source_metric": "candidate_hit_rate_at_pool",
        "denominator": metrics.get("hit_rate_denominator"),
        "users_with_holdout": metrics.get("users_with_holdout"),
    }


def _target_rank_percentile_summary(ranking_cases: list[dict[str, Any]], stage_trace: list[dict[str, Any]]) -> dict[str, Any]:
    input_counts = _input_candidate_counts(stage_trace)
    ranks = []
    percentiles = []
    missed_topk_hit_top20_users = set()
    for row in ranking_cases:
        rank = _positive_int(row.get("target_rank"))
        user_id = str(row.get("user_id", ""))
        if rank is None:
            continue
        ranks.append(rank)
        input_count = input_counts.get(user_id) or REQUIRED_CANDIDATE_POOL_SIZE
        percentiles.append(round(rank / input_count, 6) if input_count else 0.0)
        if REQUIRED_TOP_K < rank <= 20 and user_id:
            missed_topk_hit_top20_users.add(user_id)
    return {
        "case_count": len(ranking_cases),
        "rank_min": min(ranks) if ranks else None,
        "rank_mean": _mean(ranks),
        "rank_median": _median(ranks),
        "rank_p90": _percentile(ranks, 0.9),
        "percentile_mean": _mean(percentiles),
        "percentile_median": _median(percentiles),
        "percentile_p90": _percentile(percentiles, 0.9),
        "missed_top5_but_hit_top20_users": len(missed_topk_hit_top20_users),
    }


def _source_exposure(frozen_rows: list[dict[str, Any]], stage_trace: list[dict[str, Any]], ranking_cases: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_sources: Counter[str] = Counter()
    topk_sources: Counter[str] = Counter()
    target_sources: Counter[str] = Counter()
    for row in frozen_rows:
        candidate_sources.update(_sources(row))
    for row in stage_trace:
        if _positive_int(row.get("final_rank")) and int(row.get("final_rank")) <= REQUIRED_TOP_K:
            topk_sources.update(_sources(row))
    for row in ranking_cases:
        target_sources.update(str(source) for source in row.get("target_sources", []) or [])
    return {
        "candidate_pool_sources": dict(sorted(candidate_sources.items())),
        "topk_sources": dict(sorted(topk_sources.items())),
        "target_sources": dict(sorted(target_sources.items())),
    }


def _duplicate_source_balance(frozen_rows: list[dict[str, Any]], stage_trace: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_summary = _source_balance_summary(frozen_rows)
    topk_rows = [row for row in stage_trace if (_positive_int(row.get("final_rank")) or 10**9) <= REQUIRED_TOP_K]
    topk_summary = _source_balance_summary(topk_rows)
    return {"candidate_pool": candidate_summary, "topk": topk_summary}


def _topk_displacement(baseline_trace: list[dict[str, Any]], diagnostic_trace: list[dict[str, Any]], ranking_cases: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_topk = _topk_by_user(baseline_trace)
    diagnostic_topk = _topk_by_user(diagnostic_trace)
    users = sorted(set(baseline_topk) | set(diagnostic_topk))
    changed_users = []
    displaced_total = 0
    introduced_total = 0
    for user_id in users:
        baseline_items = set(baseline_topk.get(user_id, []))
        diagnostic_items = set(diagnostic_topk.get(user_id, []))
        displaced = sorted(baseline_items - diagnostic_items)
        introduced = sorted(diagnostic_items - baseline_items)
        displaced_total += len(displaced)
        introduced_total += len(introduced)
        if displaced or introduced:
            changed_users.append({"user_id": user_id, "displaced": displaced, "introduced": introduced})
    target_movements = [row.get("target_rank_movement", {}) for row in ranking_cases if row.get("target_rank_movement")]
    return {
        "users_compared": len(users),
        "changed_topk_users": len(changed_users),
        "displaced_item_count": displaced_total,
        "introduced_item_count": introduced_total,
        "changed_user_examples": changed_users[:20],
        "target_rank_movement_examples": target_movements[:20],
    }


def _win_tie_loss(baseline_cases: list[dict[str, Any]], diagnostic_cases: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_by_key = _cases_by_key(baseline_cases)
    diagnostic_by_key = _cases_by_key(diagnostic_cases)
    keys = sorted(set(baseline_by_key) & set(diagnostic_by_key))
    wins = ties = losses = 0
    deltas = []
    examples = []
    for key in keys:
        baseline_rank = _positive_int(baseline_by_key[key].get("target_rank"))
        diagnostic_rank = _positive_int(diagnostic_by_key[key].get("target_rank"))
        if baseline_rank is None or diagnostic_rank is None:
            continue
        delta = baseline_rank - diagnostic_rank
        deltas.append(delta)
        if delta > 0:
            wins += 1
        elif delta < 0:
            losses += 1
        else:
            ties += 1
        if len(examples) < 20 and delta != 0:
            examples.append({"user_id": key[0], "target_item": key[1], "baseline_rank": baseline_rank, "diagnostic_rank": diagnostic_rank, "rank_delta_positive_is_win": delta})
    return {
        "definition": "win means the diagnostic chain ranks the held-out target closer to rank 1 than the same-run baseline.",
        "cases_compared": len(deltas),
        "win": wins,
        "tie": ties,
        "loss": losses,
        "rank_delta_avg_positive_is_win": _mean(deltas),
        "examples": examples,
    }


def _guardrail_status(comparison: dict[str, Any], baseline: dict[str, Any], diagnostic: dict[str, Any], stage_summary: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "candidate_pool_size_200": comparison.get("candidate_pool_size") == REQUIRED_CANDIDATE_POOL_SIZE,
        "top_k_5": comparison.get("top_k") == REQUIRED_TOP_K,
        "current_recall_mainline_fixed": comparison.get("current_recall_mainline", {}).get("mainline_id") == CURRENT_RECALL_MAINLINE_ID,
        "frozen_candidates_match": diagnostic.get("frozen_candidate_comparison", {}).get("match") is True,
        "diagnostic_not_promotable": diagnostic.get("promotion_eligible") is False and diagnostic.get("diagnostic_only") is True,
        "artifact_inspection_pass": comparison.get("artifact_inspection", {}).get("status") == "PASS",
        "online_metric_claims_empty": not _online_metric_claims(stage_summary)["accepted"],
        "baseline_present": baseline.get("run_kind") == "baseline",
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
    }


def _online_metric_claims(stage_summary: dict[str, Any]) -> dict[str, Any]:
    raw_claims = stage_summary.get("online_metric_claims", []) or []
    raw_metrics = stage_summary.get("online_metrics", {}) or {}
    rejected = []
    if raw_metrics:
        rejected.append({"field": "online_metrics", "value": raw_metrics, "reason": "online metrics are future-scope and not current promotion evidence"})
    for claim in raw_claims:
        rejected.append({"field": "online_metric_claims", "value": claim, "reason": "online metric claims are not accepted in Phase C offline diagnostics"})
    return {"accepted": [], "rejected": rejected, "forbidden_metric_names": ONLINE_METRIC_NAMES}


def _artifact_paths(output_dir: Path, comparison: dict[str, Any], baseline: dict[str, Any], diagnostic: dict[str, Any]) -> dict[str, Any]:
    return {
        "output_dir": str(output_dir),
        "phase_6_comparison_path": str(output_dir / "comparison.json"),
        "baseline_metrics_path": baseline.get("metrics_path"),
        "baseline_recommendations_path": baseline.get("recommendations_path"),
        "baseline_ranking_cases_path": baseline.get("ranking_cases_path"),
        "baseline_frozen_candidates_path": baseline.get("frozen_candidates_path"),
        "baseline_stage_trace_path": baseline.get("ranking_stage_trace_path"),
        "diagnostic_metrics_path": diagnostic.get("metrics_path"),
        "diagnostic_recommendations_path": diagnostic.get("recommendations_path"),
        "diagnostic_ranking_cases_path": diagnostic.get("ranking_cases_path"),
        "diagnostic_frozen_candidates_path": diagnostic.get("frozen_candidates_path"),
        "diagnostic_stage_trace_path": diagnostic.get("ranking_stage_trace_path"),
        "diagnostic_stage_summary_path": diagnostic.get("ranking_stage_summary_path"),
        "baseline_config_path": str(BASELINE_CONFIG),
        "fixed_recall_config_path": str(CURRENT_RECALL_MAINLINE_CONFIG),
    }


def _safe_read_jsonl(path: Any) -> list[dict[str, Any]]:
    if not path:
        return []
    target = Path(path)
    if not target.is_file():
        return []
    return read_jsonl(target)


def _safe_read_json(path: Any) -> dict[str, Any]:
    if not path:
        return {}
    target = Path(path)
    if not target.is_file():
        return {}
    return read_json(target)


def _input_candidate_counts(stage_trace_rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {}
    for row in stage_trace_rows:
        user_id = str(row.get("user_id", ""))
        if user_id and user_id not in counts:
            counts[user_id] = int(row.get("input_candidate_count", 0) or 0)
    return counts


def _source_balance_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    single = 0
    multi = 0
    source_combinations: Counter[str] = Counter()
    seen_by_user_item: set[tuple[str, str]] = set()
    duplicate_rows = 0
    for row in rows:
        user_item = (str(row.get("user_id", "")), str(row.get("item_id", row.get("parent_asin", ""))))
        if user_item in seen_by_user_item:
            duplicate_rows += 1
        seen_by_user_item.add(user_item)
        sources = sorted(set(_sources(row)))
        if len(sources) > 1:
            multi += 1
        else:
            single += 1
        source_combinations["+".join(sources) or "unknown"] += 1
    total = single + multi
    return {
        "row_count": total,
        "single_source_count": single,
        "multi_source_count": multi,
        "multi_source_rate": round(multi / total, 6) if total else 0.0,
        "duplicate_user_item_rows": duplicate_rows,
        "source_combinations": dict(source_combinations.most_common()),
    }


def _topk_by_user(stage_trace_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    by_user: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in stage_trace_rows:
        rank = _positive_int(row.get("final_rank"))
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", ""))
        if user_id and item_id and rank is not None and rank <= REQUIRED_TOP_K:
            by_user[user_id].append((rank, item_id))
    return {user_id: [item for _, item in sorted(rows)] for user_id, rows in by_user.items()}


def _cases_by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("user_id", "")), str(row.get("target_item", ""))): row
        for row in rows
        if row.get("user_id") and row.get("target_item")
    }


def _sources(row: dict[str, Any]) -> list[str]:
    return [str(source) for source in row.get("sources", []) or []]


def _int_metric(metrics: dict[str, Any], key: str) -> int:
    try:
        return int(metrics.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _float_metric(metrics: dict[str, Any], key: str) -> float:
    try:
        return round(float(metrics.get(key) or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _mean(values: list[int | float]) -> float:
    return round(sum(float(value) for value in values) / len(values), 6) if values else 0.0


def _median(values: list[int | float]) -> float | int | None:
    if not values:
        return None
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[midpoint]
    return round((float(sorted_values[midpoint - 1]) + float(sorted_values[midpoint])) / 2, 6)


def _percentile(values: list[int | float], percentile: float) -> float | int | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, max(0, int(round((len(sorted_values) - 1) * percentile))))
    return sorted_values[index]


def _resolve_path(path: str | Path) -> Path:
    target = Path(path)
    if target.is_absolute():
        return target
    return ROOT / target


if __name__ == "__main__":
    main()
