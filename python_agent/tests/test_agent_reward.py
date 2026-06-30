from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.recsys_types import AgentDecision, MergedCandidate
from rs_core.agent.constraint_filter import apply_constraint_filter_tool
from rs_core.agent.feedback import constraint_filter_tool
from rs_core.agent.reward import build_reward_evidence, compute_turn_reward
from rs_core.agent.contracts.schema import AgentTurn, FeedbackConstraints
from rs_core.agent.tools import collect_diagnostic_tool_events


def test_reward_uses_component_weights_and_evidence():
    decision = AgentDecision(
        user_id="u1",
        strategy_name="demo",
        trigger_reason="ranked_hybrid_candidates_available",
        agent_explanation="Uses popular source only.",
        risk_flags=[],
        limitations=[],
        final_items=[{"parent_asin": "target", "sources": ["popular"], "category": "Audio"}],
    )
    turn = AgentTurn(
        turn_index=1,
        user_input="prefer Audio",
        feedback_constraints=FeedbackConstraints(preferred_categories={"Audio": 1.0}),
        recommendation=decision,
        candidates=[],
        ranking=decision.final_items,
        fallback_used=False,
        diagnostics={},
    )

    turn.reward_evidence = build_reward_evidence(turn, {"target"})
    reward = compute_turn_reward(turn)

    assert turn.reward_evidence.holdout_hits == ["target"]
    assert reward.recommendation_quality == 0.4
    assert reward.feedback_alignment == 0.3
    assert reward.explanation_faithfulness == 0.2
    assert reward.risk_penalty == 0.0
    assert reward.total == 0.9


def test_reward_caps_alignment_when_feedback_has_no_effect():
    decision = AgentDecision(
        user_id="u1",
        strategy_name="demo",
        trigger_reason="ranked_hybrid_candidates_available",
        agent_explanation="Uses popular source only.",
        risk_flags=[],
        limitations=[],
        final_items=[{"parent_asin": "speaker", "sources": ["popular"], "category": "Audio"}],
    )
    turn = AgentTurn(
        turn_index=2,
        user_input="prefer Audio",
        feedback_constraints=FeedbackConstraints(preferred_categories={"Audio": 1.0}),
        recommendation=decision,
        candidates=[],
        ranking=decision.final_items,
        fallback_used=False,
        diagnostics={"boosts_applied": {}, "boost_events": {}, "prior_turn_items": ["speaker"]},
    )

    turn.reward_evidence = build_reward_evidence(turn, set())
    reward = compute_turn_reward(turn)

    assert turn.reward_evidence.feedback_constraints_satisfied["feedback_effect_observed"] is False
    assert reward.feedback_alignment == 0.1


def test_reward_penalizes_fallback_empty_and_ignored_feedback():
    decision = AgentDecision(
        user_id="u1",
        strategy_name="demo",
        trigger_reason="no_candidates_available",
        agent_explanation="No candidates.",
        risk_flags=["popular_fallback_used", "empty_recommendation_list"],
        limitations=[],
        final_items=[],
    )
    turn = AgentTurn(
        turn_index=1,
        user_input="dislike a",
        feedback_constraints=FeedbackConstraints(disliked_item_ids={"a"}),
        recommendation=decision,
        candidates=[],
        ranking=[],
        fallback_used=True,
        diagnostics={},
    )
    turn.reward_evidence = build_reward_evidence(turn, set())
    reward = compute_turn_reward(turn)

    assert reward.feedback_alignment == 0.0
    assert reward.explanation_faithfulness == 0.0
    assert reward.risk_penalty == -0.1
    assert reward.total == -0.1


def test_constraint_filter_module_delegates_to_production_policy_contract():
    candidates = [
        MergedCandidate("wired_1", ["popular"], {"popular": 1.0}, "Audio", {"title_clean": "wired headphones", "price": 30}),
        MergedCandidate("speaker_1", ["popular"], {"popular": 0.8}, "Audio", {"title_clean": "portable bluetooth speaker", "price": 80}),
    ]
    constraints = FeedbackConstraints(disliked_item_ids={"wired_1"}, preferred_keywords={"bluetooth": 1.0})
    config = {"constraint_filter": {"keyword_boost": 0.3}, "constraint_filter_min_candidates": 1}

    direct_filtered, direct_diagnostics = apply_constraint_filter_tool(candidates, constraints, config)
    policy_filtered, policy_diagnostics = constraint_filter_tool(
        candidates,
        constraints,
        {"constraint_filter_min_candidates": 1, "feedback_keyword_boost": 0.3},
    )

    assert [candidate.item_id for candidate in direct_filtered] == [candidate.item_id for candidate in policy_filtered]
    assert direct_diagnostics["excluded_items"] == policy_diagnostics["excluded_items"]
    assert direct_diagnostics["boosts_applied"] == policy_diagnostics["boosts_applied"]
    filter_event = direct_diagnostics["constraint_filter_events"][0]
    boost_event = direct_diagnostics["constraint_filter_events"][1]
    assert {"type", "action", "target_item_id", "reason"} <= set(filter_event)
    assert {"type", "action", "target_item_id", "reason"} <= set(boost_event)
    assert filter_event["type"] == "constraint_filter"
    assert filter_event["action"] == "filter"
    assert filter_event["target_item_id"] == "wired_1"
    assert filter_event["reason"] == "disliked_item"
    assert boost_event["type"] == "constraint_filter"
    assert boost_event["action"] == "boost"
    assert boost_event["target_item_id"] == "speaker_1"
    assert boost_event["reason"] == "preferred_keyword"


def test_reward_evidence_collects_internal_constraint_and_rerank_events():
    decision = AgentDecision(
        user_id="u1",
        strategy_name="demo",
        trigger_reason="ranked_hybrid_candidates_available",
        agent_explanation="Uses popular source only.",
        risk_flags=[],
        limitations=[],
        final_items=[{"parent_asin": "speaker", "sources": ["popular"], "category": "Audio"}],
    )
    constraint_event = {"type": "constraint_filter", "action": "penalize", "target_item_id": "speaker", "reason": "disliked_keyword"}
    rerank_event = {"type": "feedback_rerank", "action": "boost", "target_item_id": "speaker", "reason": "liked_item_neighbor"}
    turn = AgentTurn(
        turn_index=2,
        user_input="prefer Audio",
        feedback_constraints=FeedbackConstraints(preferred_categories={"Audio": 1.0}),
        recommendation=decision,
        candidates=[],
        ranking=decision.final_items,
        fallback_used=False,
        diagnostics={
            "constraint_filter_events": [constraint_event],
            "feedback_rerank_events": [rerank_event],
        },
    )

    evidence = build_reward_evidence(turn, set())

    assert evidence.tool_events == [constraint_event, rerank_event]


def test_tool_event_helper_uses_fixed_keys_and_ignores_non_dict_events():
    constraint_event = {"type": "constraint_filter", "action": "filter", "target_item_id": "speaker", "reason": "max_price"}
    rerank_event = {"type": "feedback_rerank", "action": "boost", "target_item_id": "speaker", "reason": "liked_item_neighbor"}

    events = collect_diagnostic_tool_events({
        "feedback_rerank_events": [rerank_event, "invalid"],
        "constraint_filter_events": [constraint_event, None],
        "unrelated_events": [{"type": "ignored"}],
    })

    assert events == [constraint_event, rerank_event]
    assert all({"type", "action", "target_item_id", "reason"} <= set(event) for event in events)
