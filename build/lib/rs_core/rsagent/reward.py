from __future__ import annotations

from typing import Any

from rs_core.rsagent.schema import AgentReward, AgentTurn, RewardEvidence
from rs_core.rsagent.tools import collect_diagnostic_tool_events


def build_reward_evidence(turn: AgentTurn, holdout_items: set[str] | None = None) -> RewardEvidence:
    holdout_items = holdout_items or set()
    final_items = turn.recommendation.final_items
    item_ids = [str(item.get("parent_asin")) for item in final_items if item.get("parent_asin")]
    has_items = bool(item_ids)
    item_sources = {str(item.get("parent_asin")): list(item.get("sources", [])) for item in final_items if item.get("parent_asin")}
    constraints = turn.feedback_constraints
    disliked_items_satisfied = has_items and not (set(item_ids) & set(constraints.disliked_item_ids))
    disliked_categories = {category.lower() for category in constraints.disliked_categories}
    disliked_categories_satisfied = has_items and not any(
        str(item.get("category", "")).lower() in disliked_categories for item in final_items
    )
    preferred_terms = set(constraints.preferred_categories) | set(constraints.preferred_sources)
    preferred_represented = has_items
    if preferred_terms:
        preferred_represented = has_items and any(
            item.get("category") in constraints.preferred_categories
            or any(source in constraints.preferred_sources for source in item.get("sources", []))
            for item in final_items
        )
    prior_filter_respected = has_items
    prior_turn_items = set(turn.diagnostics.get("prior_turn_items", []))
    if constraints.filter_prior_turn_items:
        prior_filter_respected = has_items and not prior_turn_items & set(item_ids)
    feedback_effect_observed = _feedback_effect_observed(turn, set(item_ids), prior_turn_items)
    explanation = turn.recommendation.agent_explanation.lower()
    unsupported_claims = _unsupported_explanation_claims(explanation, item_sources, constraints.to_dict())
    return RewardEvidence(
        holdout_hits=sorted(set(item_ids) & set(holdout_items)),
        feedback_constraints_satisfied={
            "disliked_item_ids": disliked_items_satisfied,
            "disliked_categories": disliked_categories_satisfied,
            "preferred_represented": preferred_represented,
            "prior_turn_filter": prior_filter_respected,
            "feedback_effect_observed": feedback_effect_observed,
        },
        item_sources=item_sources,
        tool_events=collect_diagnostic_tool_events(turn.diagnostics),
        risk_flags=list(turn.recommendation.risk_flags),
        unsupported_explanation_claims=unsupported_claims,
    )


def compute_turn_reward(turn: AgentTurn) -> AgentReward:
    evidence = turn.reward_evidence
    recommendation_quality = 0.4 if evidence.holdout_hits else 0.0
    feedback_alignment = 0.0
    satisfied = evidence.feedback_constraints_satisfied
    if satisfied.get("disliked_item_ids", True):
        feedback_alignment += 0.10
    if satisfied.get("disliked_categories", True):
        feedback_alignment += 0.10
    if satisfied.get("preferred_represented", True):
        feedback_alignment += 0.05
    if satisfied.get("prior_turn_filter", True):
        feedback_alignment += 0.05
    has_feedback_constraints = _has_feedback_constraints(turn.feedback_constraints.to_dict())
    if has_feedback_constraints and not satisfied.get("feedback_effect_observed", False):
        feedback_alignment = min(feedback_alignment, 0.10)
    explanation_faithfulness = max(0.0, 0.20 - 0.10 * len(evidence.unsupported_explanation_claims)) if turn.recommendation.final_items else 0.0
    risk_penalty = 0.0
    if "popular_fallback_used" in evidence.risk_flags:
        risk_penalty -= 0.05
    if "empty_recommendation_list" in evidence.risk_flags:
        risk_penalty -= 0.05
    if not satisfied.get("disliked_item_ids", True) or not satisfied.get("disliked_categories", True):
        risk_penalty -= 0.05
    risk_penalty = max(-0.10, risk_penalty)
    total = _clamp(recommendation_quality + feedback_alignment + explanation_faithfulness + risk_penalty)
    return AgentReward(
        total=round(total, 6),
        recommendation_quality=round(recommendation_quality, 6),
        feedback_alignment=round(feedback_alignment, 6),
        explanation_faithfulness=round(explanation_faithfulness, 6),
        risk_penalty=round(risk_penalty, 6),
    )


def _feedback_effect_observed(turn: AgentTurn, item_ids: set[str], prior_turn_items: set[str]) -> bool:
    constraints = turn.feedback_constraints
    has_constraints = _has_feedback_constraints(constraints.to_dict())
    if not has_constraints or turn.turn_index <= 1:
        return True
    if turn.diagnostics.get("excluded_items") or turn.diagnostics.get("excluded_category_items") or turn.diagnostics.get("excluded_prior_turn_items"):
        return True
    if turn.diagnostics.get("boosts_applied") or turn.diagnostics.get("boost_events"):
        return True
    if constraints.filter_prior_turn_items and item_ids and not item_ids <= prior_turn_items:
        return True
    return False


def _has_feedback_constraints(constraints: dict[str, Any]) -> bool:
    return any(
        bool(constraints.get(key))
        for key in [
            "disliked_item_ids",
            "disliked_categories",
            "preferred_categories",
            "preferred_sources",
            "preferred_keywords",
            "disliked_keywords",
            "filter_prior_turn_items",
        ]
    )


def _unsupported_explanation_claims(
    explanation: str,
    item_sources: dict[str, list[str]],
    constraints: dict[str, Any],
) -> list[str]:
    claims: list[str] = []
    known_sources = {source for sources in item_sources.values() for source in sources}
    for source in ["semantic", "itemcf_weak", "itemcf_strong", "popular", "category"]:
        if source in explanation and source not in known_sources:
            claims.append(f"source:{source}")
    if "feedback" in explanation and not _has_feedback_constraints(constraints):
        claims.append("feedback")
    return claims


def _clamp(value: float) -> float:
    return min(1.0, max(-1.0, value))
