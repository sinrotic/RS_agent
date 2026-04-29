from __future__ import annotations

from rs_core.recsys.types import AgentDecision
from rs_core.rsagent.reward import build_reward_evidence, compute_turn_reward
from rs_core.rsagent.schema import AgentTurn, FeedbackConstraints


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
