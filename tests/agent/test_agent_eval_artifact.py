from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

import json

from rs_core.offline.evaluation.agent_artifact import build_agent_eval_artifact, build_training_signals
from rs_core.agent.contracts.schema import AgentSession, AgentTurn, FeedbackConstraints
from rs_core.common.recsys_types import AgentDecision


def test_agent_eval_artifact_contains_internal_evidence_and_training_signals():
    session = _session_with_two_turns()

    artifact = build_agent_eval_artifact(
        session,
        {"scene_id": "scene-1", "role": {"role_id": "commuter_practical"}, "metrics": {"satisfaction": 1.0, "accepted": True}},
        agent_variant="enhanced_feedback_rerank",
        run_id="run-1",
    )

    assert artifact["schema_version"] == "rs_agent_eval_artifact_v1"
    assert artifact["agent_variant"] == "enhanced_feedback_rerank"
    assert artifact["role_id"] == "commuter_practical"
    assert artifact["tool_events"] == [
        {"type": "constraint_filter", "action": "penalize", "target_item_id": "neighbor", "reason": "disliked_keyword", "delta": -0.2},
        {"type": "feedback_rerank", "action": "boost", "target_item_id": "neighbor", "source_item_id": "liked", "delta": 0.5},
    ]
    assert artifact["training_signals"]["metrics"]["sft_count"] == 2
    assert artifact["training_signals"]["metrics"]["reward_count"] == 2
    assert artifact["training_signals"]["metrics"]["trajectory_turn_count"] == 2
    assert artifact["training_signals"]["trajectory"][1]["tool_events"] == artifact["tool_events"]
    json.dumps(artifact)


def test_training_signals_keep_rollout_samples_wrapped():
    session = _session_with_two_turns()
    artifact = build_agent_eval_artifact(session)
    signals = build_training_signals(artifact["rollouts"], artifact["scorecard"])

    first_rollout_sample = artifact["rollouts"][0]["training_samples"]["sft_sample"]
    assert signals["sft"][0]["schema_version"] == "rs_agent_sft_sample_v1"
    assert signals["sft"][0]["sample"] == first_rollout_sample
    assert signals["training_status"] == "deferred_environment_reward_only"


def test_public_export_shape_does_not_need_internal_artifact_fields():
    public_session = {
        "session_id": "s1",
        "user_id": "u1",
        "turn_count": 1,
        "events": [],
        "display_responses": [],
    }
    blocked = {
        "ranking",
        "candidates",
        "diagnostics",
        "reward",
        "reward_evidence",
        "training_samples",
        "tool_events",
        "constraint_filter_events",
        "feedback_rerank_events",
        "scorecard",
        "judge_scores",
    }

    assert not (blocked & set(public_session))


def _session_with_two_turns() -> AgentSession:
    session = AgentSession(session_id="s1", user_id="u1")
    first_constraints = FeedbackConstraints()
    second_constraints = FeedbackConstraints(liked_item_ids={"liked"}, item_feedback_events=[{"action": "like", "item_id": "liked", "source": "test"}])
    session.active_constraints = second_constraints
    session.turns.extend([
        _turn(1, first_constraints, [{"parent_asin": "old"}], {}),
        _turn(
            2,
            second_constraints,
            [{"parent_asin": "neighbor"}],
            {
                "constraint_filter_events": [
                    {"type": "constraint_filter", "action": "penalize", "target_item_id": "neighbor", "reason": "disliked_keyword", "delta": -0.2}
                ],
                "feedback_rerank_events": [
                    {"type": "feedback_rerank", "action": "boost", "target_item_id": "neighbor", "source_item_id": "liked", "delta": 0.5}
                ],
            },
        ),
    ])
    return session


def _turn(turn_index: int, constraints: FeedbackConstraints, final_items: list[dict], diagnostics: dict) -> AgentTurn:
    return AgentTurn(
        turn_index=turn_index,
        user_input="hello",
        feedback_constraints=constraints,
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="test",
            trigger_reason="test",
            agent_explanation="Here are options.",
            risk_flags=[],
            limitations=[],
            final_items=final_items,
        ),
        candidates=[{"item_id": item["parent_asin"], "sources": ["popular"], "category": "Audio"} for item in final_items],
        ranking=final_items,
        fallback_used=False,
        diagnostics=diagnostics,
        assistant_response="Here are options.",
    )
