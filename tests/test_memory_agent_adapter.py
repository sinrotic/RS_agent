from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit

from rs_core.agent_runtime.adapters.memory import (
    MEMORY_AGENT_POST_TURN_STAGE,
    MEMORY_AGENT_SESSION_END_STAGE,
    MemoryAgentAdapter,
    MemoryAgentConfig,
    MemoryAgentInvocation,
)
from rs_core.recsys.types import AgentDecision
from rs_core.rsagent.schema import AgentSession, AgentTurn, FeedbackConstraints


class ExplodingMemoryRunner:
    def run(self, _request):  # type: ignore[no-untyped-def]
        raise RuntimeError("private memory stack path /tmp/memory.log")


def test_memory_agent_disabled_returns_internal_skipped_without_public_output() -> None:
    response = MemoryAgentAdapter().invoke(MemoryAgentInvocation(request_id="memory-1"), MemoryAgentConfig(enabled=False))

    assert response.status == "skipped"
    assert response.request_id == "memory-1"
    assert response.public_output == {}
    assert response.sft_output == {}
    assert response.diagnostics == {"status": "skipped", "reason": "disabled", "internal_only": True}


def test_memory_agent_shadow_builds_internal_support_from_long_memory_snapshot() -> None:
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints.preferred_keywords["bluetooth"] = 1.0
    session.active_constraints.use_cases["commute"] = 1.0
    turn = _turn(session.active_constraints, user_input="need bluetooth for commute")
    session.turns.append(turn)
    config = MemoryAgentConfig(enabled=True, max_recalled_entries=5)

    report = MemoryAgentAdapter().attach_shadow_report(session, turn, config)

    assert report.status == "ok"
    assert report.public_payload_allowed is False
    assert report.candidate_generation_allowed is False
    assert report.ranking_input_replacement_allowed is False
    assert report.promotion_allowed is False
    support = turn.diagnostics["memory_agent_support"]
    assert support["public_payload_allowed"] is False
    assert support["candidate_generation_allowed"] is False
    assert support["ranking_input_replacement_allowed"] is False
    assert support["promotion_allowed"] is False
    assert support["recalled_memory"]["entry_count"] >= 1
    assert support["snapshot_summary"]["entry_count"] >= 1
    assert "preferred_keywords" in support["snapshot_summary"]["active_constraint_keys"]


def test_memory_agent_loop_output_projection_is_internal_only() -> None:
    session = AgentSession(session_id="s1", user_id="u1")
    session.active_constraints.preferred_keywords["audio"] = 1.0
    turn = _turn(session.active_constraints, user_input="audio")
    session.turns.append(turn)

    result = MemoryAgentAdapter().build_loop(session, turn, MemoryAgentConfig(enabled=True)).run(
        _loop_input(turn.user_input, session.session_id, turn.turn_index)
    )

    assert result.public_output == {}
    assert result.sft_output == {}
    assert "memory_agent_support" in result.internal_output


def test_memory_agent_invalid_payload_fails_open() -> None:
    response = MemoryAgentAdapter().invoke(
        MemoryAgentInvocation(stage=MEMORY_AGENT_POST_TURN_STAGE, request_id="bad", payload={}),
        MemoryAgentConfig(enabled=True),
    )

    assert response.status == "skipped"
    assert response.public_output == {}
    assert response.sft_output == {}
    assert response.diagnostics["reason"] == "missing_session_or_turn"


def test_memory_agent_unsupported_mode_reports_internal_error() -> None:
    session = AgentSession(session_id="s1", user_id="u1")
    turn = _turn(session.active_constraints)

    response = MemoryAgentAdapter().invoke(
        MemoryAgentInvocation(stage=MEMORY_AGENT_POST_TURN_STAGE, payload={"session": session, "turn": turn}),
        MemoryAgentConfig(enabled=True, mode="active"),
    )

    assert response.status == "error"
    assert response.public_output == {}
    assert response.sft_output == {}
    assert response.shadow_report is not None
    assert response.shadow_report.errors == ["Unsupported MemoryAgent mode: active"]


def test_memory_agent_config_parses_string_booleans_and_numbers() -> None:
    config = MemoryAgentConfig.from_dict({
        "enabled": "true",
        "attach_support_to_diagnostics": "0",
        "fail_open": "yes",
        "max_recalled_entries": "3",
        "max_memory_entries": "7",
        "recall_min_score": "1.5",
    })

    assert config.enabled is True
    assert config.attach_support_to_diagnostics is False
    assert config.fail_open is True
    assert config.max_recalled_entries == 3
    assert config.max_memory_entries == 7
    assert config.recall_min_score == 1.5


def test_memory_agent_session_end_uses_public_safe_summary_input_without_internal_fields() -> None:
    response = MemoryAgentAdapter().invoke(
        MemoryAgentInvocation(
            stage=MEMORY_AGENT_SESSION_END_STAGE,
            request_id="end-1",
            payload={"public_export": _public_export_with_internal_noise()},
        ),
        MemoryAgentConfig(enabled=True),
    )

    assert response.status == "ok"
    assert response.public_output == {}
    assert response.sft_output == {}
    assert response.summary_support is not None
    assert response.summary_support.session_id == "session-1"
    serialized = json.dumps(response.to_dict(), ensure_ascii=False).lower()
    assert "raw_evidence" not in serialized
    assert "score_trace" not in serialized
    assert "agent_thoughts" not in serialized
    assert "diagnostics raw" not in serialized


def test_memory_agent_runner_failure_is_internal_only() -> None:
    response = MemoryAgentAdapter(runner=ExplodingMemoryRunner()).invoke(
        MemoryAgentInvocation(request_id="explode"),
        MemoryAgentConfig(enabled=True),
    )

    assert response.status == "error"
    assert response.public_output == {}
    assert response.sft_output == {}
    assert response.diagnostics["internal_only"] is True


def _loop_input(user_input: str, session_id: str, turn_index: int):  # type: ignore[no-untyped-def]
    from rs_core.agent_runtime.core import AgentLoopInput

    return AgentLoopInput(agent_name="memory_agent", user_input=user_input, session_id=session_id, state={"turn_index": turn_index}, metadata={"mode": "shadow"})


def _turn(constraints: FeedbackConstraints, user_input: str = "prefer audio") -> AgentTurn:
    return AgentTurn(
        turn_index=1,
        user_input=user_input,
        feedback_constraints=constraints,
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="demo",
            trigger_reason="ranked_hybrid_candidates_available",
            agent_explanation="Uses popular source only.",
            risk_flags=[],
            limitations=[],
            final_items=[{"parent_asin": "speaker_1", "category": "Audio"}],
        ),
        candidates=[],
        ranking=[{"parent_asin": "speaker_1", "category": "Audio"}],
        fallback_used=False,
        diagnostics={},
    )


def _public_export_with_internal_noise() -> dict[str, object]:
    return {
        "session_id": "session-1",
        "user_id": "u1",
        "turn_count": 1,
        "agent_thoughts": [{"raw_evidence": "do not leak"}],
        "public_timeline": {
            "events": [
                {
                    "event_type": "chat",
                    "turn_index": 1,
                    "user_message": "For commute, prefer bluetooth and Audio",
                    "assistant_message": "我推荐几款蓝牙音频商品。",
                    "diagnostics": {"raw_evidence": "diagnostics raw"},
                }
            ]
        },
        "display_responses": [
            {
                "turn_index": 1,
                "assistant_message": "我推荐几款蓝牙音频商品。",
                "diagnostics": {"raw_evidence": "do not leak"},
                "items": [
                    {
                        "parent_asin": "speaker_1",
                        "title": "Bluetooth Speaker",
                        "category": "Audio",
                        "price": 39.99,
                        "rating": 4.7,
                        "features": ["portable", "wireless"],
                        "summary": "适合通勤使用。",
                        "score_trace": {"rank": 1},
                    }
                ],
                "feedback_actions": [{"type": "like", "label": "喜欢"}],
            }
        ],
    }
