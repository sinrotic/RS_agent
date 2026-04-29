from __future__ import annotations

from typing import Any

from rs_core.recsys.types import MergedCandidate, RankingResult


def rank_candidates(
    user_id: str,
    candidates: list[MergedCandidate],
    config: dict,
    top_k: int | None = None,
    allowed_sources: set[str] | None = None,
) -> RankingResult:
    k = int(top_k or config.get("top_k", 5))
    weights = config.get("rank_weights", {})
    rows: list[dict] = []
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
        rerank_delta, rerank_events = _apply_rerank_policy_delta(sources, config)
        feature_score, feature_events, item_features = _apply_item_feature_rerank(candidate, sources, config)
        model_rerank_events = candidate.metadata.get("model_rerank_events", [])
        if not isinstance(model_rerank_events, list):
            model_rerank_events = []
        agent_boost = feedback_boost + rerank_delta + feature_score
        final_score = base_score + agent_boost
        rows.append(
            {
                "parent_asin": candidate.item_id,
                "base_score": round(base_score, 6),
                "agent_boost": round(agent_boost, 6),
                "feature_score": round(feature_score, 6),
                "final_score": round(final_score, 6),
                "score": round(final_score, 6),
                "sources": sources,
                "category": candidate.category,
                "item_features": item_features,
                "rerank_events": [*rerank_events, *feature_events, *model_rerank_events],
            }
        )
    rows.sort(key=lambda item: (-item["score"], item["parent_asin"]))
    if not config.get("topk_source_minimums"):
        return RankingResult(user_id=user_id, items=rows[:k], fallback_used=not candidates)
    return RankingResult(user_id=user_id, items=_apply_source_minimums(rows, k, config["topk_source_minimums"]), fallback_used=not candidates)


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


def _group_sources(group: str) -> set[str]:
    if group == "itemcf":
        return {"itemcf_weak", "itemcf_strong"}
    return {group}
