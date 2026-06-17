from __future__ import annotations

from functools import lru_cache
from itertools import groupby, product
from pathlib import Path
from typing import Any

from rs_core.common.io import read_json
from rs_core.recsys.cold_deepfm import score_deepfm_model
from rs_core.recsys.ltr import extract_ltr_features, load_ltr_model, score_ltr_model
from rs_core.recsys.types import MergedCandidate, RankingResult

_ALLOWED_ADDITIVE_WEIGHT_GRID = {
    "source_signal": {-0.2, 0.0, 0.2, 0.4},
    "item_feature": {-0.2, 0.0, 0.2, 0.4},
    "freshness_quality": {0.0, 0.1, 0.2},
    "near_miss_tiebreak_strength": {0.0, 0.05, 0.1},
}
_DEEPFM_FEATURE_METADATA_KEYS = {"cold_deepfm_features", "deepfm_features", "ranking_features"}
_FORBIDDEN_DEEPFM_FEATURE_TOKENS = ("label", "target", "holdout", "valid", "test", "future", "candidate_rank", "source_")


def rank_candidates(
    user_id: str,
    candidates: list[MergedCandidate],
    config: dict,
    top_k: int | None = None,
    allowed_sources: set[str] | None = None,
) -> RankingResult:
    k = int(top_k or config.get("top_k", 5))
    coarse_rows = _apply_coarse_top_n(coarse_rank_candidates(candidates, config, allowed_sources), config)
    rows = rerank_candidates(fine_rank_candidates(coarse_rows, config), config)
    _annotate_stage_ranks(rows)
    rows.sort(key=lambda item: (-item["score"], item["parent_asin"]))
    _annotate_stable_tie_breaks(rows)
    if config.get("topk_source_minimums"):
        return RankingResult(user_id=user_id, items=_apply_source_minimums(rows, k, config["topk_source_minimums"]), fallback_used=not candidates)
    rows = _apply_policy_rerank_guards(rows, k, config)
    return RankingResult(user_id=user_id, items=rows[:k], fallback_used=not candidates)


def coarse_rank_candidates(
    candidates: list[MergedCandidate],
    config: dict,
    allowed_sources: set[str] | None = None,
) -> list[dict[str, Any]]:
    weights = config.get("rank_weights", {})
    coarse_policy = config.get("coarse_ranking", {}) if isinstance(config.get("coarse_ranking", {}), dict) else {}
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        sources = [source for source in candidate.sources if allowed_sources is None or source in allowed_sources]
        if not sources:
            continue
        base_score = 0.0
        feedback_boost = 0.0
        source_components: dict[str, dict[str, float]] = {}
        for source in sources:
            raw_score = float(candidate.source_scores.get(source, 0.0))
            calibrated_score = _calibrated_source_score(raw_score, source, coarse_policy)
            contribution = float(weights.get(source, 1.0)) * calibrated_score
            source_components[source] = {
                "raw_score": round(raw_score, 6),
                "calibrated_score": round(calibrated_score, 6),
                "weight": round(float(weights.get(source, 1.0)), 6),
                "contribution": round(contribution, 6),
            }
            if source.startswith("feedback_"):
                feedback_boost += contribution
            else:
                base_score += contribution
        source_prior = _source_prior_score(sources, coarse_policy)
        rrf_score = _reciprocal_rank_fusion_score(candidate, sources, coarse_policy)
        multi_source_boost = _coarse_multi_source_boost(sources, coarse_policy)
        metadata_score = _coarse_metadata_score(candidate, weights)
        base_score += metadata_score + source_prior + rrf_score + multi_source_boost
        coarse_components = {
            "source_score_calibration": source_components,
            "source_prior": round(source_prior, 6),
            "reciprocal_rank_fusion": round(rrf_score, 6),
            "multi_source_boost": round(multi_source_boost, 6),
            "metadata_score": round(metadata_score, 6),
        }
        rows.append(
            {
                "_candidate": candidate,
                "parent_asin": candidate.item_id,
                "base_score": round(base_score, 6),
                "_feedback_boost": feedback_boost,
                "coarse_score": round(base_score, 6),
                "coarse_components": coarse_components,
                "sources": sources,
                "category": candidate.category,
                "score_trace": [
                    {"stage": "coarse", "score": round(base_score, 6), "reason_codes": _coarse_reason_codes(sources, coarse_components), "components": coarse_components},
                ],
            }
        )
    return rows


def _calibrated_source_score(raw_score: float, source: str, coarse_policy: dict[str, Any]) -> float:
    calibration = coarse_policy.get("source_score_calibration", {})
    source_calibration = calibration.get(source, {}) if isinstance(calibration, dict) else {}
    if not isinstance(source_calibration, dict):
        return raw_score
    scale = float(source_calibration.get("scale", 1.0))
    offset = float(source_calibration.get("offset", 0.0))
    lower = source_calibration.get("min")
    upper = source_calibration.get("max")
    calibrated = raw_score * scale + offset
    if lower is not None:
        calibrated = max(float(lower), calibrated)
    if upper is not None:
        calibrated = min(float(upper), calibrated)
    return calibrated


def _source_prior_score(sources: list[str], coarse_policy: dict[str, Any]) -> float:
    priors = coarse_policy.get("source_prior", {})
    if not isinstance(priors, dict):
        return 0.0
    return sum(float(priors.get(source, 0.0)) for source in _ranking_source_set(sources))


def _reciprocal_rank_fusion_score(candidate: MergedCandidate, sources: list[str], coarse_policy: dict[str, Any]) -> float:
    policy = coarse_policy.get("reciprocal_rank_fusion", {})
    if not isinstance(policy, dict) or not policy.get("enabled"):
        return 0.0
    weight = float(policy.get("weight", 1.0))
    rrf_k = float(policy.get("k", 60.0))
    ranks = _candidate_source_ranks(candidate)
    return sum(weight / (rrf_k + rank) for source, rank in ranks.items() if source in sources and rank > 0)


def _candidate_source_ranks(candidate: MergedCandidate) -> dict[str, float]:
    lineage = candidate.metadata.get("pool500_source_lineage")
    ranks: dict[str, float] = {}
    if isinstance(lineage, list):
        for row in lineage:
            if not isinstance(row, dict):
                continue
            source = str(row.get("source") or row.get("canonical_source") or "")
            rank = row.get("rank")
            if source and rank not in (None, ""):
                ranks[source] = min(float(rank), ranks.get(source, float("inf")))
    for source in candidate.sources:
        key = f"{source}_rank"
        if candidate.metadata.get(key) not in (None, ""):
            ranks[source] = min(float(candidate.metadata[key]), ranks.get(source, float("inf")))
    return ranks


def _coarse_multi_source_boost(sources: list[str], coarse_policy: dict[str, Any]) -> float:
    boost = float(coarse_policy.get("multi_source_boost", 0.0))
    source_count = len(_ranking_source_set(sources))
    return max(source_count - 1, 0) * boost


def _coarse_metadata_score(candidate: MergedCandidate, weights: dict[str, Any]) -> float:
    return (
        float(weights.get("recent", 0.0)) * float(candidate.metadata.get("recent_pop_score", 0.0) or 0.0)
        + float(weights.get("verified", 0.0)) * float(candidate.metadata.get("verified_pop_score", 0.0) or 0.0)
        + float(weights.get("time_decay", 0.0)) * float(candidate.metadata.get("time_decay_pop_score", 0.0) or 0.0)
    )


def _apply_coarse_top_n(rows: list[dict[str, Any]], config: dict) -> list[dict[str, Any]]:
    top_n = int(config.get("coarse_top_n") or config.get("coarse_topN") or 0)
    if top_n <= 0 or len(rows) <= top_n:
        return rows
    ranked = sorted(rows, key=lambda item: (-float(item["coarse_score"]), item["parent_asin"]))
    for rank, row in enumerate(ranked, start=1):
        row["coarse_candidate_rank"] = rank
        for stage_row in row.get("score_trace", []):
            if stage_row.get("stage") == "coarse":
                stage_row["candidate_rank_before_cutoff"] = rank
                stage_row["coarse_top_n"] = top_n
    return ranked[:top_n]


def fine_rank_candidates(rows: list[dict[str, Any]], config: dict) -> list[dict[str, Any]]:
    additive_weights = _resolve_additive_weights(config)
    component_values = _row_component_values(rows)
    component_norms = _normalize_additive_components(component_values)
    for row in rows:
        candidate = row["_candidate"]
        sources = row["sources"]
        feedback_boost = float(row.pop("_feedback_boost", 0.0))
        rerank_delta, rerank_events = _apply_rerank_policy_delta(sources, config)
        source_fusion_delta, source_fusion_events = _apply_source_aware_fusion_delta(sources, config)
        feature_score, feature_events, item_features = _apply_item_feature_rerank(candidate, sources, config)
        additive_score, additive_breakdown, additive_events = _apply_normalized_additive_score(
            candidate.item_id,
            component_values,
            component_norms,
            additive_weights,
        )
        agent_boost = feedback_boost + rerank_delta + source_fusion_delta + feature_score + additive_score
        fine_score = float(row["base_score"]) + agent_boost
        row.update(
            {
                "agent_boost": round(agent_boost, 6),
                "feature_score": round(feature_score, 6),
                "normalized_additive_score": round(additive_score, 6),
                "fine_score": round(fine_score, 6),
                "item_features": item_features,
                "score_components": additive_breakdown,
                "_fine_events": [*rerank_events, *source_fusion_events, *feature_events, *additive_events],
                "score_trace": [
                    *row["score_trace"],
                    {"stage": "fine", "score": round(fine_score, 6), "delta": round(agent_boost, 6), "reason_codes": _fine_reason_codes(feedback_boost, rerank_events, source_fusion_events, feature_events, additive_events)},
                ],
            }
        )
    return rows


def rerank_candidates(rows: list[dict[str, Any]], config: dict) -> list[dict[str, Any]]:
    ltr_model = _resolve_ltr_model(config)
    deepfm_model = _resolve_deepfm_model(config)
    deepfm_policy = _deepfm_policy(config)
    deepfm_limit = _deepfm_max_scored_candidates(deepfm_policy)
    deepfm_scored_item_ids = _deepfm_scored_item_ids(rows, deepfm_limit)
    for row in rows:
        candidate = row.pop("_candidate")
        fine_events = row.pop("_fine_events", [])
        ltr_score, ltr_events = _apply_ltr_model_score(candidate, ltr_model, config)
        if deepfm_scored_item_ids is not None and candidate.item_id not in deepfm_scored_item_ids:
            deepfm_score = 0.0
            deepfm_events = [{**_deepfm_base_event(deepfm_policy), "status": "skipped", "reason": "max_scored_candidates_exceeded", "delta": 0.0, "max_scored_candidates": deepfm_limit}]
        else:
            deepfm_score, deepfm_events = _apply_deepfm_model_score(candidate, deepfm_model, config)
        model_rerank_events = candidate.metadata.get("model_rerank_events", [])
        if not isinstance(model_rerank_events, list):
            model_rerank_events = []
        final_score = float(row["fine_score"]) + ltr_score + deepfm_score
        rerank_score = ltr_score + deepfm_score
        row.update(
            {
                "ltr_score": round(ltr_score, 6),
                "deepfm_score": round(deepfm_score, 6),
                "rerank_score": round(rerank_score, 6),
                "final_score": round(final_score, 6),
                "score": round(final_score, 6),
                "metadata_present": bool(candidate.metadata),
                "fallback_indicator": _candidate_has_policy_marker(candidate, ("fallback",)),
                "repaired_indicator": _candidate_has_policy_marker(candidate, ("repair", "repaired")),
                "score_trace": [
                    *row["score_trace"],
                    {"stage": "rerank", "score": round(final_score, 6), "delta": round(rerank_score, 6), "reason_codes": _rerank_reason_codes(ltr_events, [*deepfm_events, *model_rerank_events])},
                ],
                "rerank_events": [*fine_events, *ltr_events, *deepfm_events, *model_rerank_events],
            }
        )
    return rows


def _resolve_additive_weights(config: dict) -> dict[str, float]:
    policy = config.get("normalized_additive_ranking", {})
    if not policy.get("enabled"):
        return {}
    weights = {key: float(value) for key, value in dict(policy.get("weights", {}) or {}).items()}
    unsupported = sorted(set(weights) - set(_ALLOWED_ADDITIVE_WEIGHT_GRID))
    if unsupported:
        raise ValueError(f"Unsupported normalized additive weights: {unsupported}")
    for key, value in weights.items():
        if value not in _ALLOWED_ADDITIVE_WEIGHT_GRID[key]:
            allowed = sorted(_ALLOWED_ADDITIVE_WEIGHT_GRID[key])
            raise ValueError(f"Weight {key}={value} is outside the finite Phase 1.25 grid: {allowed}")
    return weights


def phase_1_25_weight_grid() -> list[dict[str, float]]:
    keys = list(_ALLOWED_ADDITIVE_WEIGHT_GRID)
    return [
        dict(zip(keys, values, strict=True))
        for values in product(*(sorted(_ALLOWED_ADDITIVE_WEIGHT_GRID[key]) for key in keys))
    ]


def _candidate_component_values(
    candidates: list[MergedCandidate],
    allowed_sources: set[str] | None,
) -> dict[str, dict[str, float | None]]:
    values: dict[str, dict[str, float | None]] = {}
    for candidate in candidates:
        sources = [source for source in candidate.sources if allowed_sources is None or source in allowed_sources]
        if not sources:
            continue
        values[candidate.item_id] = _component_values_for_candidate(candidate, sources)
    return values


def _row_component_values(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    return {
        row["parent_asin"]: _component_values_for_candidate(row["_candidate"], row["sources"])
        for row in rows
    }


def _component_values_for_candidate(candidate: MergedCandidate, sources: list[str]) -> dict[str, float | None]:
    source_signal_values = [float(candidate.source_scores.get(source, 0.0)) for source in sources]
    return {
        "source_signal": max(source_signal_values) if source_signal_values else None,
        "item_feature": _component_item_feature_value(candidate, sources),
        "freshness_quality": _component_freshness_quality_value(candidate),
        "near_miss_tiebreak_strength": _component_near_miss_value(candidate),
    }


def _component_item_feature_value(candidate: MergedCandidate, sources: list[str]) -> float:
    features = _item_feature_values(candidate, sources)
    return float(
        features.get("multi_source", 0)
        + features.get("two_tower_itemcf_source", 0)
        + features.get("two_tower_semantic_source", 0)
        + features.get("feedback_category_match", 0)
        + features.get("feedback_source_match", 0)
        + features.get("feedback_keyword_match_count", 0)
        - features.get("feedback_disliked_keyword_match_count", 0)
    )


def _component_freshness_quality_value(candidate: MergedCandidate) -> float | None:
    keys = ("recent_pop_score", "verified_pop_score", "time_decay_pop_score")
    values = [candidate.metadata.get(key) for key in keys if candidate.metadata.get(key) is not None]
    if not values:
        return None
    return sum(float(value or 0.0) for value in values)


def _component_near_miss_value(candidate: MergedCandidate) -> float:
    value = candidate.metadata.get("near_miss_tiebreak_score")
    if value is not None:
        return float(value or 0.0)
    return 1.0 if len(_ranking_source_set(candidate.sources)) >= 2 else 0.0


def _normalize_additive_components(
    component_values: dict[str, dict[str, float | None]],
) -> dict[str, dict[str, dict[str, float | bool]]]:
    normalized: dict[str, dict[str, dict[str, float | bool]]] = {item_id: {} for item_id in component_values}
    for component in _ALLOWED_ADDITIVE_WEIGHT_GRID:
        raw_values = [values.get(component) for values in component_values.values() if values.get(component) is not None]
        minimum = min(raw_values) if raw_values else 0.0
        maximum = max(raw_values) if raw_values else 0.0
        denominator = maximum - minimum
        for item_id, values in component_values.items():
            raw_value = values.get(component)
            missing = raw_value is None
            filled_value = 0.0 if missing else float(raw_value)
            normalized_value = 0.0 if missing or denominator == 0.0 else (filled_value - minimum) / denominator
            normalized[item_id][component] = {
                "raw": round(filled_value, 6),
                "normalized": round(normalized_value, 6),
                "missing": missing,
            }
    return normalized


def _apply_normalized_additive_score(
    item_id: str,
    component_values: dict[str, dict[str, float | None]],
    component_norms: dict[str, dict[str, dict[str, float | bool]]],
    weights: dict[str, float],
) -> tuple[float, dict[str, dict[str, float | bool]], list[dict[str, Any]]]:
    breakdown: dict[str, dict[str, float | bool]] = {}
    score = 0.0
    for component in _ALLOWED_ADDITIVE_WEIGHT_GRID:
        diagnostics = dict(component_norms.get(item_id, {}).get(component, {"raw": 0.0, "normalized": 0.0, "missing": True}))
        weight = float(weights.get(component, 0.0))
        contribution = round(float(diagnostics["normalized"]) * weight, 6)
        diagnostics["weight"] = weight
        diagnostics["contribution"] = contribution
        breakdown[component] = diagnostics
        score += contribution
    if not weights:
        return 0.0, breakdown, []
    return round(score, 6), breakdown, [{"type": "normalized_additive_score", "delta": round(score, 6), "components": breakdown}]


def _annotate_stage_ranks(rows: list[dict[str, Any]]) -> None:
    stage_specs = [("coarse", "coarse_score"), ("fine", "fine_score"), ("rerank", "final_score")]
    ranks_by_stage: dict[str, dict[str, int]] = {}
    for stage, score_key in stage_specs:
        ordered = sorted(rows, key=lambda item: (-float(item[score_key]), item["parent_asin"]))
        ranks_by_stage[stage] = {item["parent_asin"]: rank for rank, item in enumerate(ordered, start=1)}
    for item in rows:
        item_id = item["parent_asin"]
        coarse_rank = ranks_by_stage["coarse"][item_id]
        fine_rank = ranks_by_stage["fine"][item_id]
        final_rank = ranks_by_stage["rerank"][item_id]
        item["coarse_rank"] = coarse_rank
        item["fine_rank"] = fine_rank
        item["final_rank"] = final_rank
        item["rank_movement"] = {
            "coarse_to_fine": coarse_rank - fine_rank,
            "fine_to_final": fine_rank - final_rank,
            "coarse_to_final": coarse_rank - final_rank,
        }
        for stage_row in item.get("score_trace", []):
            if stage_row.get("stage") == "coarse":
                stage_row["rank"] = coarse_rank
            elif stage_row.get("stage") == "fine":
                stage_row["rank"] = fine_rank
                stage_row["rank_movement_from_previous"] = coarse_rank - fine_rank
            elif stage_row.get("stage") == "rerank":
                stage_row["rank"] = final_rank
                stage_row["rank_movement_from_previous"] = fine_rank - final_rank



def _coarse_reason_codes(sources: list[str], components: dict[str, Any] | None = None) -> list[str]:
    reason_codes = [f"source:{source}" for source in sources]
    components = components or {}
    if components.get("source_prior"):
        reason_codes.append("source_prior")
    if components.get("reciprocal_rank_fusion"):
        reason_codes.append("reciprocal_rank_fusion")
    if components.get("multi_source_boost"):
        reason_codes.append("multi_source_boost")
    if components.get("metadata_score"):
        reason_codes.append("metadata_score")
    return reason_codes



def _fine_reason_codes(
    feedback_boost: float,
    rerank_events: list[dict[str, Any]],
    source_fusion_events: list[dict[str, Any]],
    feature_events: list[dict[str, Any]],
    additive_events: list[dict[str, Any]],
) -> list[str]:
    reason_codes: list[str] = []
    if feedback_boost:
        reason_codes.append("feedback_boost")
    for event in [*rerank_events, *source_fusion_events, *feature_events, *additive_events]:
        event_type = event.get("type")
        feature = event.get("feature")
        reason_codes.append(f"{event_type}:{feature}" if feature else str(event_type))
    return reason_codes



def _rerank_reason_codes(ltr_events: list[dict[str, Any]], model_rerank_events: list[Any]) -> list[str]:
    reason_codes: list[str] = []
    for event in ltr_events:
        reason_codes.append(str(event.get("type", "ltr_model")))
    for event in model_rerank_events:
        if isinstance(event, dict):
            reason_codes.append(str(event.get("type", "model_rerank")))
    return reason_codes



def _annotate_stable_tie_breaks(rows: list[dict[str, Any]]) -> None:
    for _, tied_rows in groupby(rows, key=lambda item: item["score"]):
        tied = list(tied_rows)
        if len(tied) <= 1:
            continue
        item_ids = [str(item["parent_asin"]) for item in tied]
        for item in tied:
            item.setdefault("rerank_events", []).append({
                "type": "stable_tie_break",
                "key": "parent_asin_asc",
                "score": item["score"],
                "tied_item_ids": item_ids,
            })


def _apply_policy_rerank_guards(rows: list[dict[str, Any]], top_k: int, config: dict) -> list[dict[str, Any]]:
    policy = config.get("policy_rerank_guard", {})
    if not policy.get("enabled"):
        return rows
    guarded = list(rows)
    for rule_name, predicate, cap_key in (
        ("fallback_exposure_cap", _is_fallback_policy_item, "max_fallback_topk_ratio"),
        ("repaired_candidate_cap", _is_repaired_policy_item, "max_repaired_topk_ratio"),
        ("metadata_missing_cap", _is_metadata_missing_policy_item, "max_metadata_missing_topk_ratio"),
        ("category_missing_cap", _is_category_missing_policy_item, "max_category_missing_topk_ratio"),
    ):
        if cap_key in policy:
            guarded = _cap_policy_items(guarded, top_k, float(policy[cap_key]), predicate, rule_name)
    source_cap = policy.get("max_per_source_topk_ratio", policy.get("max_top_source_concentration_ratio"))
    if source_cap is not None:
        guarded = _cap_policy_group(guarded, top_k, float(source_cap), _primary_policy_source, "source_diversity_guard")
    category_cap = policy.get("max_per_category_topk_ratio", policy.get("max_top_category_concentration_ratio"))
    if category_cap is not None:
        guarded = _cap_policy_group(guarded, top_k, float(category_cap), _policy_category, "category_diversity_guard")
    if "max_abs_rank_movement" in policy:
        guarded = _cap_rank_movement(guarded, top_k, int(policy["max_abs_rank_movement"]))
    _renumber_policy_final_ranks(guarded)
    return guarded


def _cap_policy_items(
    rows: list[dict[str, Any]],
    top_k: int,
    max_ratio: float,
    predicate: Any,
    rule_name: str,
) -> list[dict[str, Any]]:
    eligible, previously_deferred = _split_policy_guard_deferred(rows)
    cap = max(0, int(top_k * max_ratio))
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    count = 0
    for row in eligible:
        if predicate(row) and len(selected) < top_k:
            if count >= cap:
                _mark_policy_guard_deferred(row, rule_name)
                deferred.append(row)
                continue
            count += 1
        selected.append(row)
    return [*selected, *deferred, *previously_deferred]


def _cap_policy_group(
    rows: list[dict[str, Any]],
    top_k: int,
    max_ratio: float,
    group_key: Any,
    rule_name: str,
) -> list[dict[str, Any]]:
    eligible, previously_deferred = _split_policy_guard_deferred(rows)
    cap = max(1, int(top_k * max_ratio))
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for row in eligible:
        key = str(group_key(row))
        if len(selected) < top_k and counts.get(key, 0) >= cap:
            _mark_policy_guard_deferred(row, rule_name, key)
            deferred.append(row)
            continue
        counts[key] = counts.get(key, 0) + 1
        selected.append(row)
    return [*selected, *deferred, *previously_deferred]


def _cap_rank_movement(rows: list[dict[str, Any]], top_k: int, max_abs_rank_movement: int) -> list[dict[str, Any]]:
    eligible, previously_deferred = _split_policy_guard_deferred(rows)
    selected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for row in eligible:
        movement = int((row.get("rank_movement") or {}).get("coarse_to_final", 0))
        if len(selected) < top_k and abs(movement) > max_abs_rank_movement:
            _mark_policy_guard_deferred(row, "rank_movement_guard", str(movement))
            deferred.append(row)
            continue
        selected.append(row)
    return [*selected, *deferred, *previously_deferred]


def _split_policy_guard_deferred(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for row in rows:
        if _has_policy_guard_defer_event(row):
            deferred.append(row)
        else:
            eligible.append(row)
    return eligible, deferred



def _has_policy_guard_defer_event(row: dict[str, Any]) -> bool:
    return any(
        event.get("type") == "policy_rerank_guard" and event.get("action") == "defer_beyond_guarded_topk"
        for event in row.get("rerank_events", [])
        if isinstance(event, dict)
    )



def _mark_policy_guard_deferred(row: dict[str, Any], rule_name: str, group_key: str | None = None) -> None:
    event = {"type": "policy_rerank_guard", "rule": rule_name, "action": "defer_beyond_guarded_topk"}
    if group_key is not None:
        event["group_key"] = group_key
    row.setdefault("rerank_events", []).append(event)
    for stage_row in row.get("score_trace", []):
        if stage_row.get("stage") == "rerank":
            stage_row.setdefault("reason_codes", []).append(f"policy_guard:{rule_name}")


def _renumber_policy_final_ranks(rows: list[dict[str, Any]]) -> None:
    for rank, row in enumerate(rows, start=1):
        previous_final_rank = int(row.get("final_rank", rank))
        row["final_rank"] = rank
        row["rank_movement"] = dict(row.get("rank_movement", {}))
        coarse_rank = int(row.get("coarse_rank", rank))
        fine_rank = int(row.get("fine_rank", rank))
        row["rank_movement"]["fine_to_final"] = fine_rank - rank
        row["rank_movement"]["coarse_to_final"] = coarse_rank - rank
        row["rank_movement"]["policy_rerank_guard"] = previous_final_rank - rank
        for stage_row in row.get("score_trace", []):
            if stage_row.get("stage") == "rerank":
                stage_row["rank"] = rank
                stage_row["rank_movement_from_previous"] = fine_rank - rank


def _is_fallback_policy_item(row: dict[str, Any]) -> bool:
    sources = {str(source) for source in row.get("sources", [])}
    return bool(row.get("fallback_indicator")) or "co_visit_fallback_repair" in sources


def _is_repaired_policy_item(row: dict[str, Any]) -> bool:
    sources = {str(source) for source in row.get("sources", [])}
    return bool(row.get("repaired_indicator")) or "co_visit_fallback_repair" in sources


def _is_metadata_missing_policy_item(row: dict[str, Any]) -> bool:
    return not bool(row.get("metadata_present"))


def _is_category_missing_policy_item(row: dict[str, Any]) -> bool:
    return not row.get("category")


def _primary_policy_source(row: dict[str, Any]) -> str:
    sources = [str(source) for source in row.get("sources", []) if not str(source).startswith("feedback_")]
    if any(source in {"itemcf_weak", "itemcf_strong"} for source in sources):
        return "itemcf"
    return sources[0] if sources else "unknown"


def _policy_category(row: dict[str, Any]) -> str:
    return str(row.get("category") or "missing")


def _candidate_has_policy_marker(candidate: MergedCandidate, tokens: tuple[str, ...]) -> bool:
    if "co_visit_fallback_repair" in candidate.sources and any(token in {"fallback", "repair", "repaired"} for token in tokens):
        return True
    for key, value in candidate.metadata.items():
        lowered = str(key).lower()
        if value and any(token in lowered for token in tokens):
            return True
    return False


def _resolve_ltr_model(config: dict) -> dict[str, Any] | None:
    policy = config.get("ltr_model", {})
    if not policy.get("enabled"):
        return None
    if isinstance(policy.get("model"), dict):
        return policy["model"]
    model_path = policy.get("model_path")
    if not model_path:
        return None
    return _load_ltr_model_cached(str(Path(model_path)))


@lru_cache(maxsize=8)
def _load_ltr_model_cached(model_path: str) -> dict[str, Any]:
    return load_ltr_model(Path(model_path))


def _apply_ltr_model_score(candidate: MergedCandidate, model: dict[str, Any] | None, config: dict) -> tuple[float, list[dict]]:
    policy = config.get("ltr_model", {})
    if not policy.get("enabled") or not model:
        return 0.0, []
    features = extract_ltr_features(candidate, policy.get("features", {}))
    raw_score, events = score_ltr_model(features, model)
    scale = float(policy.get("score_scale", 1.0))
    ltr_score = raw_score * scale
    if not ltr_score:
        return 0.0, events
    for event in events:
        event["delta"] = round(ltr_score, 6)
    return ltr_score, events


def _deepfm_policy(config: dict) -> dict[str, Any]:
    disabled_policy: dict[str, Any] = {}
    for key in ("deepfm_shadow", "deepfm_model", "cold_deepfm_model"):
        policy = config.get(key)
        if not isinstance(policy, dict):
            continue
        resolved = dict(policy)
        resolved.setdefault("_policy_key", key)
        if resolved.get("enabled"):
            return resolved
        if not disabled_policy:
            disabled_policy = resolved
    return disabled_policy


def _resolve_deepfm_model(config: dict) -> dict[str, Any] | None:
    policy = _deepfm_policy(config)
    if not policy.get("enabled"):
        return None
    model = policy.get("model") if isinstance(policy.get("model"), dict) else None
    model_path = policy.get("model_path")
    if model is None and model_path:
        try:
            model = _load_deepfm_model_cached(str(Path(model_path)))
        except FileNotFoundError as exc:
            return {"load_error": "missing_model_path", "model_path": str(model_path), "error": str(exc)}
    if model is None:
        return None
    contract = policy.get("feature_contract") if isinstance(policy.get("feature_contract"), dict) else None
    report = policy.get("artifact_report") if isinstance(policy.get("artifact_report"), dict) else None
    contract_path = policy.get("feature_contract_path")
    report_path = policy.get("artifact_report_path") or policy.get("offline_report_path")
    try:
        return {
            "model": model,
            "feature_contract": contract or (_load_deepfm_json_cached(str(Path(contract_path))) if contract_path else None),
            "artifact_report": report or (_load_deepfm_json_cached(str(Path(report_path))) if report_path else None),
        }
    except FileNotFoundError as exc:
        return {"load_error": "missing_artifact_path", "error": str(exc)}


@lru_cache(maxsize=4)
def _load_deepfm_model_cached(model_path: str) -> dict[str, Any]:
    return read_json(Path(model_path))


@lru_cache(maxsize=8)
def _load_deepfm_json_cached(json_path: str) -> dict[str, Any]:
    return read_json(Path(json_path))


def _apply_deepfm_model_score(candidate: MergedCandidate, model: dict[str, Any] | None, config: dict) -> tuple[float, list[dict[str, Any]]]:
    policy = _deepfm_policy(config)
    if not policy.get("enabled"):
        return 0.0, []
    event = _deepfm_base_event(policy)
    if not model:
        return 0.0, [{**event, "status": "skipped", "reason": "missing_model"}]
    if model.get("load_error"):
        error_event = {**event, "status": "skipped", "reason": model["load_error"], "delta": 0.0}
        if model.get("model_path"):
            error_event["artifact_path"] = str(model["model_path"])
        if model.get("error"):
            error_event["error"] = str(model["error"])
        return 0.0, [error_event]
    model_weights = model.get("model") if isinstance(model.get("model"), dict) else model
    contract = model.get("feature_contract") if isinstance(model.get("feature_contract"), dict) else None
    report = model.get("artifact_report") if isinstance(model.get("artifact_report"), dict) else None
    contract_gate = _deepfm_feature_contract_gate(model_weights, contract)
    if contract_gate["status"] != "PASS":
        return 0.0, [{**event, **contract_gate, "delta": 0.0}]
    features = _deepfm_features_for_candidate(candidate, policy, model_weights, contract)
    feature_names = _deepfm_model_feature_names(model_weights)
    missing_features = [name for name in feature_names if name not in features]
    if missing_features and policy.get("require_all_features", True):
        return 0.0, [{**event, "status": "skipped", "reason": "missing_required_features", "missing_features": missing_features[:20], "missing_feature_count": len(missing_features)}]
    raw_score = score_deepfm_model(features, model_weights)
    scale = float(policy.get("score_scale", 0.0 if _is_deepfm_shadow_policy(policy) else 1.0))
    mode = str(policy.get("mode") or policy.get("scoring_mode") or ("shadow_diagnostic" if _is_deepfm_shadow_policy(policy) else "rerank"))
    requested_delta = raw_score * scale if _deepfm_affect_ranking_requested(policy, mode, scale) else 0.0
    governance = _deepfm_governance_gate(policy, report, requested_delta, model_weights)
    delta = 0.0 if governance["governance_blocked_delta"] else requested_delta
    event.update(
        {
            "status": "scored_no_ranking_effect" if delta == 0.0 else "scored_with_ranking_delta",
            "mode": mode,
            "raw_score": round(raw_score, 6),
            "score_scale": round(scale, 6),
            "delta": round(delta, 6),
            "feature_strategy": _deepfm_feature_strategy(policy),
            "feature_count": len(features),
            "missing_feature_count": len(missing_features),
            **governance,
        }
    )
    return delta, [event]


def _deepfm_base_event(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "deepfm_shadow_score" if _is_deepfm_shadow_policy(policy) else "diagnostic_deepfm_rerank",
        "diagnostic_only": True,
        "public_payload_allowed": bool(policy.get("public_payload_allowed", False)),
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "promotion_allowed": False,
    }


def _is_deepfm_shadow_policy(policy: dict[str, Any]) -> bool:
    mode = str(policy.get("mode") or policy.get("scoring_mode") or "")
    return policy.get("_policy_key") == "deepfm_shadow" or mode.startswith("shadow")


def _deepfm_feature_contract_gate(model: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any]:
    if not contract:
        return {"status": "PASS", "feature_contract_checked": False}
    model_features = _deepfm_model_feature_names(model)
    contract_features = [str(name) for name in contract.get("feature_names", [])]
    if not contract_features:
        return {"status": "blocked_feature_contract", "reason": "missing_contract_feature_names", "feature_contract_checked": True}
    if model_features != contract_features:
        return {
            "status": "blocked_feature_contract",
            "reason": "model_contract_feature_mismatch",
            "feature_contract_checked": True,
            "missing_model_features": [name for name in contract_features if name not in model_features][:20],
            "extra_model_features": [name for name in model_features if name not in contract_features][:20],
        }
    return {"status": "PASS", "feature_contract_checked": True, "feature_contract_feature_count": len(contract_features)}


def _deepfm_model_feature_names(model: dict[str, Any]) -> list[str]:
    return [str(name) for name in model.get("feature_names", [])]


def _deepfm_governance_gate(policy: dict[str, Any], report: dict[str, Any] | None, requested_delta: float, model: dict[str, Any]) -> dict[str, Any]:
    report_replacement_allowed = report.get("ranking_replacement_allowed") is True if report else None
    report_effect_allowed = report.get("ranking_effect_conclusion_allowed") is True if report else None
    model_diagnostic_only = model.get("diagnostic_only") is True
    policy_diagnostic_only = policy.get("diagnostic_only") is True
    report_diagnostic_only = report.get("diagnostic_only") is True if report else False
    policy_replacement = policy.get("ranking_input_replacement_allowed", policy.get("ranking_replacement_allowed"))
    policy_effect = policy.get("ranking_effect_conclusion_allowed")
    delta_allowed = policy_replacement is True and policy_effect is True and not model_diagnostic_only and not policy_diagnostic_only and not report_diagnostic_only
    if report:
        delta_allowed = delta_allowed and report_replacement_allowed is True and report_effect_allowed is True
    governance_blocked_delta = bool(requested_delta and not delta_allowed)
    return {
        "ranking_replacement_allowed": bool(delta_allowed),
        "ranking_effect_conclusion_allowed": bool(delta_allowed),
        "report_ranking_replacement_allowed": report_replacement_allowed,
        "report_ranking_effect_conclusion_allowed": report_effect_allowed,
        "model_diagnostic_only": model_diagnostic_only,
        "policy_diagnostic_only": policy_diagnostic_only,
        "report_diagnostic_only": report_diagnostic_only,
        "governance_blocked_delta": governance_blocked_delta,
    }


def _deepfm_affect_ranking_requested(policy: dict[str, Any], mode: str, scale: float) -> bool:
    if policy.get("affect_ranking") is not None:
        return bool(policy.get("affect_ranking")) and scale != 0.0
    return mode not in {"shadow", "shadow_diagnostic", "diagnostic"} and scale != 0.0


def _deepfm_max_scored_candidates(policy: dict[str, Any]) -> int | None:
    if not policy.get("enabled") or policy.get("max_scored_candidates") in (None, ""):
        return None
    try:
        return max(0, int(policy["max_scored_candidates"]))
    except (TypeError, ValueError):
        return None


def _deepfm_scored_item_ids(rows: list[dict[str, Any]], limit: int | None) -> set[str] | None:
    if limit is None:
        return None
    ranked = sorted(rows, key=lambda item: (-float(item["fine_score"]), item["parent_asin"]))
    return {str(item["parent_asin"]) for item in ranked[:limit]}


def _deepfm_feature_strategy(policy: dict[str, Any]) -> str:
    if policy.get("feature_strategy"):
        return str(policy["feature_strategy"])
    return "all_zero_safe" if policy.get("_policy_key") == "deepfm_shadow" else "metadata"


def _deepfm_features_for_candidate(candidate: MergedCandidate, policy: dict[str, Any], model: dict[str, Any] | None = None, contract: dict[str, Any] | None = None) -> dict[str, float]:
    strategy = _deepfm_feature_strategy(policy)
    expected_features = [str(name) for name in (contract or {}).get("feature_names", [])] or _deepfm_model_feature_names(model or {})
    if strategy in {"all_zero_safe", "metadata_exact_key"}:
        features = {name: 0.0 for name in expected_features}
        if strategy == "metadata_exact_key":
            features.update({key: value for key, value in _deepfm_metadata_features(candidate, policy).items() if key in features})
        return features
    features = _deepfm_metadata_features(candidate, policy)
    inline_features = policy.get("features")
    if isinstance(inline_features, dict):
        features.update(_numeric_feature_dict(inline_features))
    return features


def _deepfm_metadata_features(candidate: MergedCandidate, policy: dict[str, Any]) -> dict[str, float]:
    requested_keys = policy.get("feature_metadata_keys") or sorted(_DEEPFM_FEATURE_METADATA_KEYS)
    feature_keys = [str(key) for key in requested_keys if str(key) in _DEEPFM_FEATURE_METADATA_KEYS]
    features: dict[str, float] = {}
    for key in feature_keys:
        value = candidate.metadata.get(key)
        if isinstance(value, dict):
            features.update(_numeric_feature_dict(value))
    return features


def _numeric_feature_dict(values: dict[str, Any]) -> dict[str, float]:
    features: dict[str, float] = {}
    for key, value in values.items():
        feature_name = str(key)
        if _is_forbidden_deepfm_feature_name(feature_name):
            continue
        try:
            features[feature_name] = float(value)
        except (TypeError, ValueError):
            continue
    return features


def _is_forbidden_deepfm_feature_name(feature_name: str) -> bool:
    lowered = feature_name.lower()
    return any(token in lowered for token in _FORBIDDEN_DEEPFM_FEATURE_TOKENS)


def _apply_source_aware_fusion_delta(sources: list[str], config: dict) -> tuple[float, list[dict]]:
    policy = config.get("source_aware_fusion", {})
    if not policy.get("enabled"):
        return 0.0, []
    source_set = _ranking_source_set(sources)
    delta = 0.0
    events: list[dict[str, Any]] = []
    has_itemcf = bool(source_set & _group_sources("itemcf"))
    has_two_tower = "two_tower" in source_set
    if has_itemcf:
        adjustment = float(policy.get("itemcf_source_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "itemcf_source", "delta": round(adjustment, 6)})
    if has_itemcf and len(source_set) >= 2:
        adjustment = float(policy.get("itemcf_multi_source_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "itemcf_multi_source", "delta": round(adjustment, 6)})
    if has_two_tower:
        adjustment = float(policy.get("two_tower_source_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "two_tower_source", "delta": round(adjustment, 6)})
    if has_two_tower and len(source_set) >= 2:
        adjustment = float(policy.get("two_tower_multi_source_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "two_tower_multi_source", "delta": round(adjustment, 6)})
    if has_two_tower and has_itemcf:
        adjustment = float(policy.get("two_tower_itemcf_source_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "two_tower_itemcf_source", "delta": round(adjustment, 6)})
    if has_two_tower and "semantic" in source_set:
        adjustment = float(policy.get("two_tower_semantic_source_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "two_tower_semantic_source", "delta": round(adjustment, 6)})
    if source_set == {"two_tower"}:
        adjustment = -float(policy.get("two_tower_only_penalty", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "two_tower_only", "delta": round(adjustment, 6)})
    if source_set == {"semantic"}:
        adjustment = -float(policy.get("semantic_only_penalty", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "semantic_only", "delta": round(adjustment, 6)})
    if source_set == {"popular"}:
        adjustment = -float(policy.get("popular_only_penalty", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "source_aware_fusion", "feature": "popular_only", "delta": round(adjustment, 6)})
    return delta, events


def _apply_item_feature_rerank(candidate: MergedCandidate, sources: list[str], config: dict) -> tuple[float, list[dict], dict[str, Any]]:
    policy = config.get("item_feature_rerank", {})
    features = _item_feature_values(candidate, sources)
    if not policy.get("enabled"):
        return 0.0, [], features
    weights = policy.get("weights", {})
    score = 0.0
    events: list[dict[str, Any]] = []
    for feature, value in features.items():
        weight = float(weights.get(feature, 0.0))
        contribution = float(value) * weight
        if contribution:
            score += contribution
            events.append({"type": "item_feature", "feature": feature, "value": value, "weight": weight, "delta": round(contribution, 6)})
    return score, events, features


def _item_feature_values(candidate: MergedCandidate, sources: list[str]) -> dict[str, Any]:
    source_set = set(sources)
    boost_events = candidate.metadata.get("feedback_boost_events", [])
    if not isinstance(boost_events, list):
        boost_events = []
    return {
        "multi_source": int(len(source_set - {"feedback_category", "feedback_keyword", "feedback_keyword_penalty", "feedback_model_rerank"}) >= 2),
        "two_tower_source": int("two_tower" in source_set),
        "two_tower_only": int(source_set == {"two_tower"}),
        "two_tower_multi_source": int("two_tower" in source_set and len(source_set) >= 2),
        "two_tower_itemcf_source": int("two_tower" in source_set and bool(source_set & _group_sources("itemcf"))),
        "two_tower_semantic_source": int("two_tower" in source_set and "semantic" in source_set),
        "semantic_only": int(source_set == {"semantic"}),
        "popular_only": int(source_set == {"popular"}),
        "feedback_category_match": int(any(event.get("type") == "preferred_category" for event in boost_events)),
        "feedback_source_match": int(any(event.get("type") == "preferred_source" for event in boost_events)),
        "feedback_keyword_match_count": sum(1 for event in boost_events if event.get("type") == "preferred_keyword"),
        "feedback_disliked_keyword_match_count": sum(1 for event in boost_events if event.get("type") == "disliked_keyword"),
    }


def _apply_rerank_policy_delta(sources: list[str], config: dict) -> tuple[float, list[dict]]:
    policy = config.get("rerank_policy", {})
    if not policy.get("enabled"):
        return 0.0, []
    delta = 0.0
    events: list[dict] = []
    source_set = set(sources)
    if "semantic" in source_set:
        adjustment = float(policy.get("semantic_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "semantic_boost", "delta": adjustment, "reason": "source_present"})
    if len(source_set) >= 2:
        adjustment = float(policy.get("multi_source_boost", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "multi_source_boost", "delta": adjustment, "reason": "multiple_sources_present"})
    if source_set == {"popular"}:
        adjustment = -float(policy.get("popular_only_penalty", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "popular_only_penalty", "delta": adjustment, "reason": "single_source_popular"})
    if source_set == {"semantic"}:
        adjustment = -float(policy.get("semantic_only_penalty", 0.0))
        delta += adjustment
        if adjustment:
            events.append({"type": "semantic_only_penalty", "delta": adjustment, "reason": "single_source_semantic"})
    return delta, events


def _apply_source_minimums(rows: list[dict], k: int, minimums: dict[str, int]) -> list[dict]:
    selected: dict[str, dict] = {}
    for group, minimum in minimums.items():
        sources = _group_sources(group)
        eligible = [row for row in rows if any(source in sources for source in row["sources"])]
        if len(eligible) < int(minimum):
            continue
        for row in eligible[: int(minimum)]:
            selected[row["parent_asin"]] = row
    for row in rows:
        if len(selected) >= k:
            break
        selected.setdefault(row["parent_asin"], row)
    final_rows = list(selected.values())[:k]
    final_rows.sort(key=lambda item: (-item["score"], item["parent_asin"]))
    return final_rows


def _ranking_source_set(sources: list[str]) -> set[str]:
    return {source for source in sources if not source.startswith("feedback_")}


def _group_sources(group: str) -> set[str]:
    if group == "itemcf":
        return {"itemcf_weak", "itemcf_strong"}
    return {group}
