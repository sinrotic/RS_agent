from __future__ import annotations

from rs_core.evaluation.agent_scorecard import build_agent_scorecard
from rs_core.rsagent.schema import AgentSession, AgentTurn, FeedbackConstraints
from rs_core.recsys.types import AgentDecision


def test_agent_scorecard_builds_equal_weight_five_dimension_scores():
    session = AgentSession(session_id="s1", user_id="u1")
    constraints = FeedbackConstraints(liked_item_ids={"liked"}, disliked_item_ids={"bad"})
    session.active_constraints = constraints
    turn = AgentTurn(
        turn_index=1,
        user_input="I like item_id=liked",
        feedback_constraints=constraints,
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="test",
            trigger_reason="test",
            agent_explanation="Here are options.",
            risk_flags=[],
            limitations=[],
            final_items=[{"parent_asin": "neighbor", "sources": ["popular", "feedback_rerank"]}],
        ),
        candidates=[{"item_id": "neighbor", "sources": ["popular", "feedback_rerank"], "category": "Audio"}],
        ranking=[{"parent_asin": "neighbor", "rerank_events": []}],
        fallback_used=False,
        diagnostics={
            "feedback_rerank_events": [
                {"type": "feedback_rerank", "action": "boost", "target_item_id": "neighbor", "source_item_id": "liked", "delta": 0.5}
            ]
        },
        assistant_response="Here are options.",
    )
    session.turns.append(turn)

    scorecard = build_agent_scorecard(session, {"metrics": {"satisfaction": 1.0, "accepted": True, "final_action": "accept"}})

    assert scorecard["schema_version"] == "rs_agent_scorecard_v1"
    assert set(scorecard["dimensions"]) == {
        "recommendation_effectiveness",
        "interaction_quality",
        "feedback_responsiveness",
        "memory_consistency",
        "training_data_quality",
    }
    assert set(scorecard["weights"].values()) == {0.2}
    assert 0.0 <= scorecard["overall_score"] <= 1.0
    assert scorecard["dimensions"]["feedback_responsiveness"]["subscores"]["boost_count"] == 1


def test_agent_scorecard_detects_rejected_item_reappearing():
    session = AgentSession(session_id="s1", user_id="u1")
    constraints = FeedbackConstraints(disliked_item_ids={"bad"})
    session.active_constraints = constraints
    session.turns.append(AgentTurn(
        turn_index=1,
        user_input="I dislike item_id=bad",
        feedback_constraints=constraints,
        recommendation=AgentDecision("u1", "test", "test", "No problem.", [], [], [{"parent_asin": "bad"}]),
        candidates=[],
        ranking=[{"parent_asin": "bad"}],
        fallback_used=False,
        diagnostics={},
    ))

    scorecard = build_agent_scorecard(session)

    feedback = scorecard["dimensions"]["feedback_responsiveness"]
    assert feedback["subscores"]["explicit_rejection_filter_score"] == 0.0
    assert feedback["evidence"]["rejected_reappeared"] == [{"turn_index": 1, "item_id": "bad"}]
