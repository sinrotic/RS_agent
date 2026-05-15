from __future__ import annotations

from functools import lru_cache
from itertools import groupby, product
from pathlib import Path
from typing import Any

from rs_core.recsys.ltr import extract_ltr_features, load_ltr_model, score_ltr
from rs_core.recsys.types import MergedCandidate, RankingResult

_ALLOWED_ADDITIVE_WEIGHT_GRID = {
    "source_signal": {-0.2, 0.0, 0.2, 0.4},
    "item_feature": {-0.2, 0.0, 0.2, 0.4},
    "freshness_quality": {0.0, 0.1, 0.2},
    "near_miss_tiebreak_strength": {0.0, 0.05, 0.1},
}


def rank_candidates(
    user_id: str,
    candidates: list[MergedCandidate],
    config: dict,
    top_k: int | None = None,
    allowed_sources: set[str] | None = None,
) -> RankingResult:
    k = int(top_k or config.get("top_k", 5))
    rows = rerank_candidates(fine_rank_candidates(coarse_rank_candidates(candidates, config, allowed_sources), config), config)
    _annotate_stage_ranks(rows)
    rows.sort(key=lambda item: (-item["score"], item["parent_asin"]))
    _annotate_stable_tie_breaks(rows)
    if not config.get("topk_source_minimums"):
        return RankingResult(user_id=user_id, items=rows[:k], fallback_used=not candidates)
    return RankingResult(user_id=user_id, items=_apply_source_minimums(rows, k, config["topk_source_minimums"]), fallback_used=not candidates)


def coarse_rank_candidates(
    candidates: list[MergedCandidate],
    config: dict,
    allowed_sources: set[str] | None = None,
) -> list[dict[str, Any]]:
    weights = config.get("rank_weights", {})
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        sources = [source for source in candidate.sources if allowed_sources is None or source in allowed_sources]
        if not sources:
            continue
        base_score = 0.0
        feedback_boost = 0.0
        for source in sources:
            contribution = float(weights.get(source, 1.0)) * float(candidate.source_scores.get(source, 0.0))
            if source.startswith("feedback_"):
                feedback_boost += contribution
            else:
                base_score += contribution
        base_score += float(weights.get("recent", 0.0)) * float(candidate.metadata.get("recent_pop_score", 0.0) or 0.0)
        base_score += float(weights.get("verified", 0.0)) * float(candidate.metadata.get("verified_pop_score", 0.0) or 0.0)
        base_score += float(weights.get("time_decay", 0.0)) * float(candidate.metadata.get("time_decay_pop_score", 0.0) or 0.0)
        rows.append(
            {
                "_candidate": candidate,
                "parent_asin": candidate.item_id,
                "base_score": round(base_score, 6),
                "_feedback_boost": feedback_boost,
                "coarse_score": round(base_score, 6),
                "sources": sources,
                "category": candidate.category,
                "score_trace": [
                    {"stage": "coarse", "score": round(base_score, 6), "reason_codes": _coarse_reason_codes(sources)},
                ],
            }
        )
    return rows


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
    for row in rows:
        candidate = row.pop("_candidate")
        fine_events = row.pop("_fine_events", [])
        ltr_score, ltr_events = _apply_ltr_model_score(candidate, ltr_model, config)
        model_rerank_events = candidate.metadata.get("model_rerank_events", [])
        if not isinstance(model_rerank_events, list):
            model_rerank_events = []
        final_score = float(row["fine_score"]) + ltr_score
        rerank_score = ltr_score
        row.update(
            {
                "ltr_score": round(ltr_score, 6),
                "rerank_score": round(rerank_score, 6),
                "final_score": round(final_score, 6),
                "score": round(final_score, 6),
                "score_trace": [
                    *row["score_trace"],
                    {"stage": "rerank", "score": round(final_score, 6), "delta": round(rerank_score, 6), "reason_codes": _rerank_reason_codes(ltr_events, model_rerank_events)},
                ],
                "rerank_events": [*fine_events, *ltr_events, *model_rerank_events],
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



def _coarse_reason_codes(sources: list[str]) -> list[str]:
    return [f"source:{source}" for source in sources]



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
    if not model:
        return 0.0, []
    policy = config.get("ltr_model", {})
    features = extract_ltr_features(candidate, policy.get("features", {}))
    raw_score = score_ltr(features, model.get("weights", {}), float(model.get("bias", 0.0)))
    scale = float(policy.get("score_scale", 1.0))
    ltr_score = raw_score * scale
    if not ltr_score:
        return 0.0, []
    return ltr_score, [{"type": "ltr_model", "model_type": model.get("model_type", "unknown"), "delta": round(ltr_score, 6)}]


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
