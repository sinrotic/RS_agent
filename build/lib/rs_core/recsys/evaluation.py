from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from itertools import combinations
from math import log2
from pathlib import Path
from typing import Any

from rs_core.recsys.ranking import rank_candidates
from rs_core.recsys.types import EvaluationSummary, MergedCandidate, RankingResult


FLOAT_TOLERANCE = 1e-9
MIN_HIT_RATE_ABSOLUTE_LIFT = 0.001
MIN_HIT_RATE_RELATIVE_LIFT = 0.03
MIN_MISSED_TOPK_REDUCTION = 1
TERMINAL_MINIMUM_RUNS = 3
TERMINAL_REQUIRED_CONSISTENT_RUNS = 2
TERMINAL_MINIMUM_SEGMENT_USERS = 30
TERMINAL_MINIMUM_SEGMENT_POSITIVE_USERS = 5
RANKING_EXPERIMENT_REGISTRY_SCHEMA_VERSION = "ranking_experiment_registry_v1"
FROZEN_CANDIDATE_ARTIFACT_SCHEMA_VERSION = "frozen_candidate_artifact_v1"
RANKING_FEATURE_CONTRACT_VERSION = "ranking_feature_contract_v1"
RANKING_METHOD_REGISTRY_SCHEMA_VERSION = "ranking_method_registry_v1"
RANKING_ARTIFACT_INSPECTION_SCHEMA_VERSION = "ranking_artifact_inspection_v1"
RANKING_GPU_RESOURCE_SCHEMA_VERSION = "ranking_gpu_resource_v1"
RANKING_METHOD_STATES = ["candidate", "invalid_stop", "diagnostic", "blocked", "retired", "challenger", "champion"]
ALLOWED_RANKING_FEATURE_FAMILIES = [
    "source_features",
    "item_metadata_features",
    "candidate_rank_features",
    "source_score_features",
    "user_history_aggregate_features",
]
DIAGNOSTIC_ONLY_RANKING_FEATURE_FAMILIES = ["near_miss_diagnostics_features"]
FORBIDDEN_RANKING_FEATURE_FAMILIES = [
    "holdout_target_features",
    "future_interaction_features",
    "valid_or_test_trained_features",
]
KEY_METRICS = [
    "hit_rate_at_k",
    "ndcg_at_k",
    "mrr_at_k",
    "map_at_k",
    "candidate_hit_missed_topk_users",
    "candidate_hit_rate_at_pool",
    "fallback_rate",
    "candidate_count_avg",
]
FREEZE_METRICS = ["candidate_hit_rate_at_pool", "candidate_count_avg"]


def heldout_positives(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    positives: dict[str, set[str]] = defaultdict(set)
    for row in records:
        if row.get("label_binary"):
            positives[row.get("user_id", "")].add(row.get("parent_asin", ""))
    return {user: {item for item in items if item} for user, items in positives.items() if user and items}


def evaluate(
    candidates_by_user: dict[str, list[MergedCandidate]],
    rankings_by_user: dict[str, RankingResult],
    holdout_records: list[dict[str, Any]],
    config: dict,
    fallback_users: set[str] | None = None,
) -> EvaluationSummary:
    fallback_users = fallback_users or set()
    positives = heldout_positives(holdout_records)
    users = sorted(set(candidates_by_user) | set(rankings_by_user))
    users_with_holdout = [user for user in users if positives.get(user)]
    eval_users = users_with_holdout or users
    eval_user_set = set(eval_users)
    k = int(config.get("top_k", 5))

    source_counter: Counter[str] = Counter()
    topk_source_counter: Counter[str] = Counter()
    candidate_hit_source_counter: Counter[str] = Counter()
    topk_hit_source_counter: Counter[str] = Counter()
    source_pair_counter: Counter[str] = Counter()
    source_item_sets: dict[str, set[str]] = defaultdict(set)
    source_user_sets: dict[str, set[str]] = defaultdict(set)
    source_candidate_sets: dict[str, set[str]] = defaultdict(set)
    source_marginal_hit_user_sets: dict[str, set[str]] = defaultdict(set)
    unique_candidate_items: set[str] = set()
    category_counts: list[int] = []
    candidate_counts: list[int] = []
    candidate_hit_ranks: list[int] = []
    candidate_cutoffs = _candidate_metric_cutoffs(config)
    candidate_hit_users_at_cutoffs: dict[int, int] = dict.fromkeys(candidate_cutoffs, 0)
    candidate_recall_values_at_cutoffs: dict[int, list[float]] = {cutoff: [] for cutoff in candidate_cutoffs}
    candidate_hit_users = 0
    candidate_hit_missed_topk_users = 0
    ranked_hit_users = 0
    recall_at_k_values: list[float] = []
    recall_at_pool_values: list[float] = []
    ndcg_values: list[float] = []
    mrr_values: list[float] = []
    map_values: list[float] = []
    multi_source_candidates = 0
    single_source_candidates = 0
    for user in users:
        candidates = candidates_by_user.get(user, [])
        targets = positives.get(user, set())
        candidate_counts.append(len(candidates))
        candidate_hits = [candidate for candidate in candidates if candidate.item_id in targets]
        ranking = rankings_by_user.get(user, RankingResult(user, []))
        full_ranking = rank_candidates(user, candidates, config, top_k=len(candidates) or k)
        ranking_items = ranking.items[:k]
        ranked_hit = bool({item["parent_asin"] for item in ranking_items} & targets)
        if user in eval_user_set and targets:
            topk_ids = [item.get("parent_asin") for item in ranking_items]
            pool_ids = [candidate.item_id for candidate in candidates]
            recall_at_k_values.append(_recall(topk_ids, targets))
            recall_at_pool_values.append(_recall(pool_ids, targets))
            ndcg_values.append(_ndcg(topk_ids, targets, k))
            mrr_values.append(_mrr(topk_ids, targets))
            map_values.append(_average_precision(topk_ids, targets))
            for cutoff in candidate_cutoffs:
                cutoff_ids = [candidate.item_id for candidate in candidates[:cutoff]]
                if set(cutoff_ids) & targets:
                    candidate_hit_users_at_cutoffs[cutoff] += 1
                candidate_recall_values_at_cutoffs[cutoff].append(_recall(cutoff_ids, targets))
        if user in eval_user_set and candidate_hits:
            candidate_hit_users += 1
            for candidate in candidate_hits:
                candidate_hit_source_counter.update(candidate.sources)
            for source in _marginal_hit_sources(candidate_hits, targets):
                source_marginal_hit_user_sets[source].add(user)
            rank = _best_hit_rank(full_ranking.items, targets)
            if rank is not None:
                candidate_hit_ranks.append(rank)
            if not ranked_hit:
                candidate_hit_missed_topk_users += 1
        for candidate in candidates:
            source_counter.update(candidate.sources)
            unique_candidate_items.add(candidate.item_id)
            sources = sorted(set(candidate.sources))
            for source in sources:
                source_item_sets[source].add(candidate.item_id)
                source_user_sets[source].add(user)
                source_candidate_sets[source].add(candidate.item_id)
            if len(sources) > 1:
                multi_source_candidates += 1
                for left, right in combinations(sources, 2):
                    source_pair_counter[f"{left}+{right}"] += 1
            else:
                single_source_candidates += 1
        if user in eval_user_set and ranked_hit:
            ranked_hit_users += 1
        for item in ranking_items:
            sources = item.get("sources", [])
            topk_source_counter.update(sources)
            if item.get("parent_asin") in targets:
                topk_hit_source_counter.update(sources)
        categories = {item.get("category", "") for item in ranking_items if item.get("category")}
        category_counts.append(len(categories))

    sample_limitations: list[str] = []
    if not users_with_holdout:
        sample_limitations.append("No held-out positive valid/test rows were available; hit-rate metrics are reported as 0.0 placeholders.")
    if len(eval_users) < len(users):
        sample_limitations.append("Hit-rate metrics only include users with held-out positives.")
    if not users:
        sample_limitations.append("No users were available for evaluation.")

    total_candidates = sum(candidate_counts)
    empty_candidate_users = sum(1 for count in candidate_counts if count == 0)
    catalog_denominator = _catalog_size(config)
    source_marginal_candidate_hit_users = {
        source: len(user_set) for source, user_set in sorted(source_marginal_hit_user_sets.items())
    }
    source_pair_jaccard = _source_pair_jaccard(source_candidate_sets)

    return EvaluationSummary(
        evaluation_mode=str(config.get("evaluation_mode", "valid_test")),
        users_total=len(users),
        users_with_holdout=len(users_with_holdout),
        users_evaluated=len(eval_users),
        hit_rate_denominator="users_with_holdout" if users_with_holdout else "all_demo_users_placeholder",
        candidate_count_avg=_avg(candidate_counts),
        empty_candidate_users=empty_candidate_users,
        empty_candidate_rate=round(empty_candidate_users / len(users), 6) if users else 0.0,
        user_candidate_coverage_rate=round((len(users) - empty_candidate_users) / len(users), 6) if users else 0.0,
        candidate_count_min=min(candidate_counts) if candidate_counts else 0,
        candidate_count_p50=_median(candidate_counts),
        candidate_count_p90=_percentile(candidate_counts, 0.9),
        candidate_count_max=max(candidate_counts) if candidate_counts else 0,
        candidate_hit_rate_at_cutoffs={
            str(cutoff): round(hits / len(eval_users), 6) if eval_users and positives else 0.0
            for cutoff, hits in candidate_hit_users_at_cutoffs.items()
        },
        candidate_recall_at_cutoffs={
            str(cutoff): _avg_float_from_float(values) for cutoff, values in candidate_recall_values_at_cutoffs.items()
        },
        catalog_candidate_coverage_count=len(unique_candidate_items),
        catalog_candidate_coverage_rate=round(len(unique_candidate_items) / catalog_denominator, 6) if catalog_denominator else None,
        source_user_coverage=dict(sorted((source, len(user_set)) for source, user_set in source_user_sets.items())),
        source_item_coverage=dict(sorted((source, len(item_set)) for source, item_set in source_item_sets.items())),
        source_marginal_candidate_hit_users=source_marginal_candidate_hit_users,
        source_marginal_candidate_hit_rate={
            source: round(count / len(eval_users), 6) if eval_users else 0.0
            for source, count in source_marginal_candidate_hit_users.items()
        },
        recall_source_coverage=dict(sorted(source_counter.items())),
        topk_source_coverage=dict(sorted(topk_source_counter.items())),
        source_diagnostics={},
        method_card_diagnostics=_method_card_diagnostics(
            config=config,
            eval_users=eval_users,
            candidate_hit_users=candidate_hit_users,
            source_marginal_candidate_hit_users=source_marginal_candidate_hit_users,
            candidate_counts=candidate_counts,
        ),
        candidate_hit_rate_at_pool=round(candidate_hit_users / len(eval_users), 6) if eval_users and positives else 0.0,
        candidate_hit_users=candidate_hit_users,
        candidate_hit_source_coverage=dict(sorted(candidate_hit_source_counter.items())),
        candidate_hit_rank_min=min(candidate_hit_ranks) if candidate_hit_ranks else None,
        candidate_hit_rank_avg=_avg_float(candidate_hit_ranks) if candidate_hit_ranks else None,
        candidate_hit_rank_p50=_median(candidate_hit_ranks) if candidate_hit_ranks else None,
        candidate_hit_rank_p90=_percentile(candidate_hit_ranks, 0.9) if candidate_hit_ranks else None,
        candidate_hit_missed_topk_users=candidate_hit_missed_topk_users,
        ranked_hit_users=ranked_hit_users,
        fallback_rate=round(len(fallback_users) / len(users), 6) if users else 0.0,
        recall_at_k=_avg_float_from_float(recall_at_k_values),
        recall_at_pool=_avg_float_from_float(recall_at_pool_values),
        ndcg_at_k=_avg_float_from_float(ndcg_values),
        mrr_at_k=_avg_float_from_float(mrr_values),
        map_at_k=_avg_float_from_float(map_values),
        hit_rate_at_k=_hit_rate(rankings_by_user, positives, eval_users, k),
        per_source_candidate_contribution=dict(sorted(candidate_hit_source_counter.items())),
        per_source_topk_contribution=dict(sorted(topk_hit_source_counter.items())),
        source_overlap={
            "single_source_candidate_count": single_source_candidates,
            "multi_source_candidate_count": multi_source_candidates,
            "multi_source_candidate_rate": round(multi_source_candidates / total_candidates, 6)
            if total_candidates
            else 0.0,
            "source_pair_counts": dict(sorted(source_pair_counter.items())),
            "source_pair_jaccard": source_pair_jaccard,
        },
        popular_only_hit_rate_at_k=_source_hit_rate(candidates_by_user, positives, eval_users, config, k, {"popular"}),
        itemcf_only_hit_rate_at_k=_source_hit_rate(candidates_by_user, positives, eval_users, config, k, {"itemcf_weak", "itemcf_strong"}),
        hybrid_hit_rate_at_k=_hit_rate(rankings_by_user, positives, eval_users, k),
        hybrid_no_itemcf_hit_rate_at_k=_source_hit_rate(candidates_by_user, positives, eval_users, config, k, {"popular", "category", "semantic"}),
        category_diversity_avg=_avg(category_counts),
        sample_limitations=sample_limitations,
    )


def frozen_candidate_signature(rows: list[dict[str, Any]]) -> dict[str, Any]:
    canonical = _canonical_frozen_candidate_items(rows)
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    counts_by_user = {user_id: len(items) for user_id, items in canonical.items()}
    return {
        "hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "user_count": len(canonical),
        "candidate_count": sum(counts_by_user.values()),
        "counts_by_user": counts_by_user,
    }


def frozen_candidate_artifact(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signature = frozen_candidate_signature(rows)
    return {
        "schema_version": FROZEN_CANDIDATE_ARTIFACT_SCHEMA_VERSION,
        "canonical_order": "user_id_asc_candidate_order_item_id",
        "signature": signature,
        "hash": signature["hash"],
        "user_count": signature["user_count"],
        "candidate_count": signature["candidate_count"],
        "counts_by_user": signature["counts_by_user"],
    }


def build_ranking_feature_contract() -> dict[str, Any]:
    return {
        "version": RANKING_FEATURE_CONTRACT_VERSION,
        "promotion_scope": "ranking_on_frozen_recall_pool_only",
        "allowed_feature_families": list(ALLOWED_RANKING_FEATURE_FAMILIES),
        "diagnostic_only_feature_families": list(DIAGNOSTIC_ONLY_RANKING_FEATURE_FAMILIES),
        "forbidden_feature_families": list(FORBIDDEN_RANKING_FEATURE_FAMILIES),
    }


def build_ranking_experiment_registry_entry(
    *,
    experiment_id: str,
    config: dict[str, Any],
    frozen_rows: list[dict[str, Any]],
    metrics: dict[str, Any] | None = None,
    status: dict[str, Any] | None = None,
    feature_contract: dict[str, Any] | None = None,
    feature_contract_gate_summary: dict[str, Any] | None = None,
    leakage_gate_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_summary = dict(config.get("config_summary", {}) or {})
    candidate_pool_size = config.get("candidate_pool_size", config_summary.get("candidate_pool_size"))
    top_k = config.get("top_k", config_summary.get("top_k"))
    entry = {
        "schema_version": RANKING_EXPERIMENT_REGISTRY_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "strategy_name": config.get("strategy_name", experiment_id),
        "promotion_scope": "ranking_on_frozen_recall_pool_only",
        "candidate_pool_size": candidate_pool_size,
        "top_k": top_k,
        "frozen_candidate_artifact": frozen_candidate_artifact(frozen_rows),
        "key_metrics": {key: (metrics or {}).get(key) for key in KEY_METRICS},
        "status": status or {"status": "BASELINE", "promotable": False, "diagnostic_only": False, "reasons": []},
    }
    if feature_contract is not None:
        entry["feature_contract"] = feature_contract
        entry["feature_contract_version"] = feature_contract.get("version")
    if feature_contract_gate_summary is not None:
        entry["feature_contract_gate_summary"] = feature_contract_gate_summary
    if leakage_gate_summary is not None:
        entry["leakage_gate_summary"] = leakage_gate_summary
    return entry


def build_ranking_method_registry_entry(
    *,
    method_id: str,
    method_family: str,
    lane: str,
    state: str,
    promotion_eligible: bool,
    diagnostic_only: bool,
    reasons: list[str] | None = None,
    champion_id: str | None = None,
    challenger_of: str | None = None,
    gpu_resource: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state not in RANKING_METHOD_STATES:
        raise ValueError(f"Unsupported ranking method state: {state}")
    return {
        "schema_version": RANKING_METHOD_REGISTRY_SCHEMA_VERSION,
        "method_id": method_id,
        "method_family": method_family,
        "lane": lane,
        "state": state,
        "promotion_eligible": promotion_eligible,
        "diagnostic_only": diagnostic_only,
        "reasons": reasons or [],
        "champion_id": champion_id,
        "challenger_of": challenger_of,
        "gpu_resource": gpu_resource or build_ranking_gpu_resource_summary(gpu_required=False),
    }


def build_ranking_gpu_resource_summary(
    *,
    gpu_required: bool,
    gpu_available: bool | None = None,
    device: str | None = None,
    dependency_status: str = "not_checked",
    fallback_status: str | None = None,
) -> dict[str, Any]:
    if not gpu_required:
        status = "not_required"
    elif gpu_available:
        status = "gpu_enabled"
    else:
        status = fallback_status or "blocked-gpu-unavailable"
    return {
        "schema_version": RANKING_GPU_RESOURCE_SCHEMA_VERSION,
        "gpu_required": gpu_required,
        "gpu_available": gpu_available,
        "device": device,
        "dependency_status": dependency_status,
        "status": status,
    }


def inspect_ranking_run_artifacts(rows: list[dict[str, Any]], *, required_paths: list[str] | None = None) -> dict[str, Any]:
    required = required_paths or ["metrics_path", "recommendations_path", "ranking_cases_path", "ranking_case_summary_path", "report_path", "frozen_candidates_path"]
    inspected = []
    invalid_runs = []
    for row in rows:
        missing = [key for key in required if not row.get(key) or not Path(str(row[key])).exists()]
        registry = row.get("ranking_experiment_registry", {})
        boundary_ok = registry.get("candidate_pool_size") == 200 and registry.get("top_k") == 5
        frozen_candidate_match = bool(row.get("frozen_candidate_comparison", {}).get("match"))
        diagnostic_promotion_violation = bool(row.get("diagnostic_only") and row.get("promotion_eligible"))
        status = "PASS" if not missing and boundary_ok and frozen_candidate_match and not diagnostic_promotion_violation else "INVALID"
        item = {
            "run_index": row.get("run_index"),
            "candidate_id": row.get("candidate_id"),
            "lane": row.get("lane"),
            "status": status,
            "missing_artifacts": missing,
            "candidate_pool_size": registry.get("candidate_pool_size"),
            "top_k": registry.get("top_k"),
            "frozen_candidate_match": row.get("frozen_candidate_comparison", {}).get("match"),
            "diagnostic_promotion_violation": diagnostic_promotion_violation,
        }
        inspected.append(item)
        if status != "PASS":
            invalid_runs.append(item)
    return {
        "schema_version": RANKING_ARTIFACT_INSPECTION_SCHEMA_VERSION,
        "status": "PASS" if not invalid_runs else "INVALID",
        "inspected_runs": inspected,
        "invalid_runs": invalid_runs,
    }


def inspect_physical_ranking_pipeline_artifacts(row: dict[str, Any]) -> dict[str, Any]:
    required_paths = ["trace_path", "summary_path"]
    missing_paths = [key for key in required_paths if not row.get(key) or not Path(str(row[key])).exists()]
    candidate_pool_size_ok = row.get("candidate_pool_size") == 200
    top_k_ok = row.get("top_k") == 5
    expected_stages = ["coarse", "fine", "rerank"]
    stage_counts = dict(row.get("stage_counts", {}) or {})
    pass_through_stage_counts = dict(row.get("pass_through_stage_counts", {}) or {})
    total_ranked_items = int(row.get("total_ranked_items", 0) or 0)
    pass_through_stage_failures = [
        stage for stage in expected_stages
        if int(stage_counts.get(stage, 0) or 0) != total_ranked_items
        or int(pass_through_stage_counts.get(stage, 0) or 0) != total_ranked_items
    ]
    online_metric_claims = _online_metric_claims(row)
    status = "PASS" if not missing_paths and candidate_pool_size_ok and top_k_ok and not pass_through_stage_failures and not online_metric_claims else "INVALID"
    return {
        "schema_version": RANKING_ARTIFACT_INSPECTION_SCHEMA_VERSION,
        "status": status,
        "missing_artifacts": missing_paths,
        "candidate_pool_size": row.get("candidate_pool_size"),
        "candidate_pool_size_ok": candidate_pool_size_ok,
        "top_k": row.get("top_k"),
        "top_k_ok": top_k_ok,
        "stage_counts": stage_counts,
        "pass_through_stage_counts": pass_through_stage_counts,
        "pass_through_stage_failures": pass_through_stage_failures,
        "online_metric_claims": online_metric_claims,
    }



def _online_metric_claims(row: dict[str, Any]) -> list[str]:
    claims = set()
    for key in ("online_metric_claims", "online_metrics"):
        value = row.get(key)
        if isinstance(value, dict):
            claims.update(str(metric) for metric, metric_value in value.items() if metric_value not in (None, {}, [], ""))
        elif isinstance(value, list):
            claims.update(str(metric) for metric in value if metric)
        elif value:
            claims.add(str(key))
    for key in row:
        lowered = str(key).lower()
        if lowered.startswith("online_") and key not in {"online_metric_claims", "online_metrics"}:
            claims.add(str(key))
        if lowered in {"ctr", "cvr", "conversion_rate", "revenue", "clicks", "impressions"}:
            claims.add(str(key))
    return sorted(claims)



def compare_frozen_candidate_artifacts(
    baseline_artifact: dict[str, Any],
    variant_artifact: dict[str, Any],
) -> dict[str, Any]:
    baseline_signature = _artifact_signature(baseline_artifact)
    variant_signature = _artifact_signature(variant_artifact)
    return _compare_frozen_signatures(baseline_signature, variant_signature)


def compare_frozen_candidate_signatures(
    baseline_rows: list[dict[str, Any]],
    variant_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline = frozen_candidate_signature(baseline_rows)
    variant = frozen_candidate_signature(variant_rows)
    return _compare_frozen_signatures(baseline, variant)


def strict_ranking_promotion_status(
    baseline: dict[str, Any],
    variant: dict[str, Any],
    freeze_comparison: dict[str, Any] | None = None,
    *,
    ltr_enabled: bool = False,
    feature_contract_gate_summary: dict[str, Any] | None = None,
    leakage_gate_summary: dict[str, Any] | None = None,
    tolerance: float = FLOAT_TOLERANCE,
) -> dict[str, Any]:
    reasons: list[str] = []
    metric_delta = {key: _metric_delta(baseline, variant, key) for key in KEY_METRICS}
    freeze_match = True if freeze_comparison is None else bool(freeze_comparison.get("match"))
    if not freeze_match:
        reasons.append("frozen_candidate_hash_or_count_drift")
    if _metric_delta(baseline, variant, "fallback_rate") > tolerance:
        reasons.append("fallback_rate_increased")
    for key in FREEZE_METRICS:
        if abs(_metric_delta(baseline, variant, key)) > tolerance:
            reasons.append(f"freeze_metric_drift:{key}")
    if not _config_summary_equal(baseline, variant, "candidate_pool_size"):
        reasons.append("candidate_pool_size_drift")
    if not _config_summary_equal(baseline, variant, "top_k"):
        reasons.append("top_k_drift")
    if feature_contract_gate_summary and feature_contract_gate_summary.get("status") == "REJECT":
        reasons.append("feature_contract_gate_rejected")
    if leakage_gate_summary and leakage_gate_summary.get("status") == "REJECT":
        reasons.append("leakage_gate_rejected")
    if reasons:
        return {"status": "INVALID/STOP", "promotable": False, "diagnostic_only": True, "reasons": reasons, "metric_delta": metric_delta}
    if ltr_enabled:
        return {"status": "PARTIAL diagnostic-only", "promotable": False, "diagnostic_only": True, "reasons": ["ltr_model_enabled"], "metric_delta": metric_delta}
    hit_rate_delta = _metric_delta(baseline, variant, "hit_rate_at_k")
    baseline_hit_rate = float(baseline.get("hit_rate_at_k") or 0.0)
    missed_topk_delta = _metric_delta(baseline, variant, "candidate_hit_missed_topk_users")
    hit_rate_absolute_lift_met = hit_rate_delta + tolerance >= MIN_HIT_RATE_ABSOLUTE_LIFT
    if baseline_hit_rate > tolerance:
        hit_rate_relative_lift_met = hit_rate_delta / baseline_hit_rate + tolerance >= MIN_HIT_RATE_RELATIVE_LIFT
    else:
        hit_rate_relative_lift_met = hit_rate_delta > tolerance
    missed_topk_reduction_met = missed_topk_delta <= -MIN_MISSED_TOPK_REDUCTION
    secondary_not_down = all(_metric_delta(baseline, variant, key) + tolerance >= 0 for key in ["ndcg_at_k", "mrr_at_k", "map_at_k"])
    if hit_rate_absolute_lift_met and hit_rate_relative_lift_met and missed_topk_reduction_met and secondary_not_down:
        return {"status": "Promote", "promotable": True, "diagnostic_only": False, "reasons": [], "metric_delta": metric_delta}
    secondary_up = any(_metric_delta(baseline, variant, key) > tolerance for key in ["ndcg_at_k", "mrr_at_k", "map_at_k"])
    if secondary_up and hit_rate_delta <= tolerance:
        reasons.append("secondary_metric_improved_without_hit_rate_gain")
    else:
        if not hit_rate_absolute_lift_met:
            reasons.append("hit_rate_absolute_lift_below_0.001")
        if not hit_rate_relative_lift_met:
            reasons.append("hit_rate_relative_lift_below_3pct")
        if not missed_topk_reduction_met:
            reasons.append("missed_topk_reduction_below_1")
        if not secondary_not_down:
            reasons.append("secondary_metric_regressed")
    return {"status": "PARTIAL diagnostic-only", "promotable": False, "diagnostic_only": True, "reasons": reasons, "metric_delta": metric_delta}


def terminal_ranking_promotion_gate(
    run_statuses: list[dict[str, Any]],
    *,
    segment_statuses: dict[str, dict[str, Any]] | None = None,
    minimum_runs: int = TERMINAL_MINIMUM_RUNS,
    required_consistent_runs: int = TERMINAL_REQUIRED_CONSISTENT_RUNS,
    minimum_segment_users: int = TERMINAL_MINIMUM_SEGMENT_USERS,
    minimum_segment_positive_users: int = TERMINAL_MINIMUM_SEGMENT_POSITIVE_USERS,
) -> dict[str, Any]:
    valid_statuses = [status for status in run_statuses if status.get("status") != "INVALID/STOP"]
    invalid_statuses = [status for status in run_statuses if status.get("status") == "INVALID/STOP"]
    promoted_runs = [status for status in valid_statuses if status.get("promotable") is True and status.get("status") == "Promote"]
    no_promote_reasons: list[str] = []
    if len(run_statuses) < minimum_runs:
        no_promote_reasons.append(f"minimum_runs_below_{minimum_runs}")
    if len(promoted_runs) < required_consistent_runs:
        no_promote_reasons.append(f"consistent_promote_runs_below_{required_consistent_runs}")
    if invalid_statuses:
        no_promote_reasons.append("invalid_stop_evidence_excluded_from_promotion")
    segment_gate = _terminal_segment_gate(
        segment_statuses or {},
        minimum_segment_users=minimum_segment_users,
        minimum_segment_positive_users=minimum_segment_positive_users,
    )
    blocking_segments = [name for name, status in segment_gate["segments"].items() if status["promotion_eligible"] and not status["promotable"]]
    if blocking_segments:
        no_promote_reasons.append("promotion_eligible_segment_not_promoted")
    promotable = not no_promote_reasons
    return {
        "schema_version": "terminal_ranking_promotion_gate_v1",
        "status": "Promote" if promotable else "No-Promote",
        "promotable": promotable,
        "diagnostic_only": not promotable,
        "minimum_runs": minimum_runs,
        "required_consistent_runs": required_consistent_runs,
        "run_count": len(run_statuses),
        "valid_run_count": len(valid_statuses),
        "invalid_stop_run_count": len(invalid_statuses),
        "consistent_promote_run_count": len(promoted_runs),
        "excluded_invalid_stop_reasons": [status.get("reasons", []) for status in invalid_statuses],
        "segment_gate": segment_gate,
        "no_promote_rationale": no_promote_reasons,
    }


def _terminal_segment_gate(
    segment_statuses: dict[str, dict[str, Any]],
    *,
    minimum_segment_users: int,
    minimum_segment_positive_users: int,
) -> dict[str, Any]:
    segments = {}
    for name, status in sorted(segment_statuses.items()):
        user_count = int(status.get("user_count") or status.get("users") or 0)
        positive_user_count = int(status.get("positive_user_count") or status.get("positive_users") or 0)
        underpowered = user_count < minimum_segment_users or positive_user_count < minimum_segment_positive_users
        segments[name] = {
            "status": status.get("status"),
            "promotable": bool(status.get("promotable")) if not underpowered else False,
            "diagnostic_only": True if underpowered else bool(status.get("diagnostic_only", not status.get("promotable"))),
            "promotion_eligible": not underpowered,
            "underpowered": underpowered,
            "user_count": user_count,
            "positive_user_count": positive_user_count,
            "reasons": status.get("reasons", []),
        }
    return {
        "minimum_segment_users": minimum_segment_users,
        "minimum_segment_positive_users": minimum_segment_positive_users,
        "segments": segments,
        "underpowered_segments": [name for name, status in segments.items() if status["underpowered"]],
    }


def _canonical_frozen_candidate_items(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    user_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        user_id = str(row.get("user_id", ""))
        item_id = str(row.get("item_id", row.get("parent_asin", "")))
        if user_id and item_id:
            user_rows[user_id].append({"item_id": item_id, "candidate_rank": row.get("candidate_rank"), "row_index": index})
    return {
        user_id: [row["item_id"] for row in sorted(user_rows[user_id], key=_frozen_candidate_sort_key)]
        for user_id in sorted(user_rows)
    }


def _frozen_candidate_sort_key(row: dict[str, Any]) -> tuple[int, int]:
    rank = row.get("candidate_rank")
    return (int(rank) if rank is not None else int(row["row_index"]), int(row["row_index"]))


def _artifact_signature(artifact: dict[str, Any]) -> dict[str, Any]:
    signature = artifact.get("signature")
    if isinstance(signature, dict):
        return signature
    return {
        "hash": artifact.get("hash"),
        "user_count": artifact.get("user_count"),
        "candidate_count": artifact.get("candidate_count"),
        "counts_by_user": artifact.get("counts_by_user", {}),
    }


def _compare_frozen_signatures(baseline: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "MATCH" if _frozen_signatures_match(baseline, variant) else "DRIFT",
        "match": _frozen_signatures_match(baseline, variant),
        "baseline": baseline,
        "variant": variant,
        "hash_match": baseline["hash"] == variant["hash"],
        "user_count_match": baseline["user_count"] == variant["user_count"],
        "candidate_count_match": baseline["candidate_count"] == variant["candidate_count"],
        "counts_by_user_match": baseline["counts_by_user"] == variant["counts_by_user"],
    }


def _frozen_signatures_match(baseline: dict[str, Any], variant: dict[str, Any]) -> bool:
    return all(
        baseline[key] == variant[key]
        for key in ["hash", "user_count", "candidate_count", "counts_by_user"]
    )


def _metric_delta(baseline: dict[str, Any], variant: dict[str, Any], key: str) -> float:
    return round(float(variant.get(key) or 0.0) - float(baseline.get(key) or 0.0), 12)


def _config_summary_equal(baseline: dict[str, Any], variant: dict[str, Any], key: str) -> bool:
    left = (baseline.get("config_summary") or {}).get(key)
    right = (variant.get("config_summary") or {}).get(key)
    return left == right


def _candidate_metric_cutoffs(config: dict) -> list[int]:
    raw_cutoffs = config.get("candidate_metric_cutoffs", [20, 50, 100, 200])
    if not isinstance(raw_cutoffs, list):
        raw_cutoffs = [raw_cutoffs]
    candidate_pool_size = config.get("candidate_pool_size")
    max_cutoff = int(candidate_pool_size) if candidate_pool_size else None
    cutoffs = []
    for raw_cutoff in raw_cutoffs:
        cutoff = int(raw_cutoff)
        if cutoff <= 0:
            continue
        if max_cutoff and cutoff > max_cutoff:
            continue
        cutoffs.append(cutoff)
    return sorted(set(cutoffs))


def _catalog_size(config: dict) -> int | None:
    for key in ("catalog_size", "item_catalog_size"):
        value = int(config.get(key, 0) or 0)
        if value > 0:
            return value
    return None


def _source_pair_jaccard(source_candidate_sets: dict[str, set[str]]) -> dict[str, float]:
    overlaps: dict[str, float] = {}
    for left, right in combinations(sorted(source_candidate_sets), 2):
        left_items = source_candidate_sets[left]
        right_items = source_candidate_sets[right]
        union = left_items | right_items
        overlaps[f"{left}+{right}"] = round(len(left_items & right_items) / len(union), 6) if union else 0.0
    return overlaps


def _method_card_diagnostics(
    *,
    config: dict,
    eval_users: list[str],
    candidate_hit_users: int,
    source_marginal_candidate_hit_users: dict[str, int],
    candidate_counts: list[int],
) -> dict[str, Any]:
    candidate_pool_size = int(config.get("candidate_pool_size", 0) or 0)
    baseline_candidate_hit_users = config.get("baseline_candidate_hit_users")
    if baseline_candidate_hit_users is not None:
        baseline_candidate_hit_users = int(baseline_candidate_hit_users)
        marginal_candidate_hit_users = candidate_hit_users - baseline_candidate_hit_users
    else:
        marginal_candidate_hit_users = None
    experiment_scope = str(config.get("experiment_scope", "fixed_contract_candidate_eval"))
    pool_displacement_risk = str(config.get("pool_displacement_risk", "unknown"))
    can_promote = (
        experiment_scope in {"fixed_contract_candidate_eval", "production_scale_candidate_eval"}
        and marginal_candidate_hit_users is not None
        and marginal_candidate_hit_users > 0
        and pool_displacement_risk not in {"high", "unknown"}
    )
    return {
        "schema_version": "recall_method_card_diagnostics_v1",
        "canonical_baseline": str(config.get("canonical_baseline", "semantic_title_category_expansion")),
        "experiment_scope": experiment_scope,
        "evidence_level": str(config.get("evidence_level", "same_contract_verified")),
        "decision_options": ["promote", "reject", "defer", "fallback", "document_only"],
        "forbidden_promotion_metrics": [
            "hit_rate_at_k",
            "ndcg",
            "mrr",
            "map",
            "topk_hit_rate",
            "topk_hit_users",
            "ranking_gap_pool_has_target",
            "ltr_score",
            "rerank_score",
            "ctr",
            "cvr",
            "gmv",
        ],
        "candidate_pool_size": candidate_pool_size,
        "users_with_holdout": len(eval_users),
        "baseline_candidate_hit_users": baseline_candidate_hit_users,
        "candidate_hit_users": candidate_hit_users,
        "marginal_candidate_hit_users": marginal_candidate_hit_users,
        "source_marginal_candidate_hit_users": source_marginal_candidate_hit_users,
        "source_candidate_count_before_cap": sum(candidate_counts),
        "source_candidate_count_after_cap": sum(min(count, candidate_pool_size) for count in candidate_counts) if candidate_pool_size else sum(candidate_counts),
        "pool_displacement_risk": pool_displacement_risk,
        "can_promote": can_promote,
        "decision_hint": "promote" if can_promote else "defer" if pool_displacement_risk == "unknown" else "reject_or_fallback",
    }


def _marginal_hit_sources(candidate_hits: list[MergedCandidate], targets: set[str]) -> set[str]:
    hit_sources = sorted({source for candidate in candidate_hits for source in candidate.sources})
    marginal_sources: set[str] = set()
    for source in hit_sources:
        remaining_hits = [
            candidate for candidate in candidate_hits
            if candidate.item_id in targets and (source not in set(candidate.sources) or len(set(candidate.sources) - {source}) > 0)
        ]
        if not remaining_hits:
            marginal_sources.add(source)
    return marginal_sources


def _hit_rate(rankings: dict[str, RankingResult], positives: dict[str, set[str]], users: list[str], k: int) -> float:
    if not users or not positives:
        return 0.0
    hits = 0
    counted = 0
    for user in users:
        targets = positives.get(user)
        if not targets:
            continue
        counted += 1
        recs = {item["parent_asin"] for item in rankings.get(user, RankingResult(user, [])).items[:k]}
        if recs & targets:
            hits += 1
    return round(hits / counted, 6) if counted else 0.0


def _source_hit_rate(
    candidates_by_user: dict[str, list[MergedCandidate]],
    positives: dict[str, set[str]],
    users: list[str],
    config: dict,
    k: int,
    sources: set[str],
) -> float:
    if not users or not positives:
        return 0.0
    rankings = {
        user: rank_candidates(user, candidates_by_user.get(user, []), config, top_k=k, allowed_sources=sources)
        for user in users
    }
    return _hit_rate(rankings, positives, users, k)


def _best_hit_rank(items: list[dict[str, Any]], targets: set[str]) -> int | None:
    for index, item in enumerate(items, start=1):
        if item.get("parent_asin") in targets:
            return index
    return None


def _recall(item_ids: list[str | None], targets: set[str]) -> float:
    if not targets:
        return 0.0
    return round(len({item for item in item_ids if item in targets}) / len(targets), 6)


def _ndcg(item_ids: list[str | None], targets: set[str], k: int) -> float:
    dcg = 0.0
    for index, item_id in enumerate(item_ids[:k], start=1):
        if item_id in targets:
            dcg += 1.0 / log2(index + 1)
    ideal_hits = min(len(targets), k)
    if ideal_hits == 0:
        return 0.0
    ideal_dcg = sum(1.0 / log2(index + 1) for index in range(1, ideal_hits + 1))
    return round(dcg / ideal_dcg, 6) if ideal_dcg else 0.0


def _mrr(item_ids: list[str | None], targets: set[str]) -> float:
    for index, item_id in enumerate(item_ids, start=1):
        if item_id in targets:
            return round(1.0 / index, 6)
    return 0.0


def _average_precision(item_ids: list[str | None], targets: set[str]) -> float:
    if not targets:
        return 0.0
    hits = 0
    precision_sum = 0.0
    for index, item_id in enumerate(item_ids, start=1):
        if item_id in targets:
            hits += 1
            precision_sum += hits / index
    return round(precision_sum / min(len(targets), len(item_ids)), 6) if hits else 0.0


def _median(values: list[int]) -> float:
    if not values:
        return 0.0
    rows = sorted(values)
    middle = len(rows) // 2
    if len(rows) % 2:
        return float(rows[middle])
    return round((rows[middle - 1] + rows[middle]) / 2, 6)


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    rows = sorted(values)
    index = min(len(rows) - 1, max(0, int(round((len(rows) - 1) * percentile))))
    return float(rows[index])


def _avg_float(values: list[int]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _avg_float_from_float(values: list[float]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0


def _avg(values: list[int]) -> float:
    return round(sum(values) / len(values), 6) if values else 0.0
