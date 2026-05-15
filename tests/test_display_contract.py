import pytest

from rs_core.display import build_display_record

pytestmark = pytest.mark.unit
from rs_core.recsys.types import AgentDecision
from rs_core.rsagent.schema import AgentSession, AgentTurn, FeedbackConstraints

BLOCKED_DISPLAY_KEYS = {
    "score",
    "base_score",
    "agent_boost",
    "coarse_score",
    "fine_score",
    "rerank_score",
    "final_score",
    "score_trace",
    "rank_movement",
    "diagnostics",
    "reward_evidence",
    "training_samples",
}
BLOCKED_DISPLAY_TERMS = {
    "agent_boost",
    "base_score",
    "coarse_score",
    "diagnostic",
    "feedback_source",
    "fine_score",
    "final_score",
    "itemcf",
    "ranking",
    "rank_movement",
    "recall source",
    "rerank_score",
    "score_trace",
    "reward",
    "reward_evidence",
    "source",
    "training",
    "training_samples",
}


def test_display_response_exposes_only_frontend_safe_fields():
    session, turn = _session_with_turn()
    display = build_display_record(turn, session)

    assert display["schema_version"] == "rs_agent_display_v1"
    assert display["session_id"] == "s1"
    assert display["user_id"] == "u1"
    assert display["turn_index"] == 2
    assert display["assistant_message"] == "Here are safer display cards."
    assert [item["parent_asin"] for item in display["items"]] == ["speaker_1"]
    item = display["items"][0]
    assert item == {
        "parent_asin": "speaker_1",
        "title": "Portable Speaker",
        "category": "Audio",
        "price": "$49.99",
        "rating": "4.5",
        "store": "Demo Store",
        "features": ["bluetooth", "portable"],
        "description": "Small speaker for commute.",
        "image_url": None,
        "badges": ["blended_signal", "matches_feedback", "missing_image"],
        "summary": "Good commute audio pick",
    }
    assert display["feedback_actions"] == [
        {"type": "like", "label": "喜欢"},
        {"type": "dislike", "label": "不喜欢"},
        {"type": "show_different", "label": "换一批"},
        {"type": "why", "label": "为什么推荐"},
    ]
    assert display["ui_state"] == {"image_fallback_enabled": True, "can_request_more": True}
    assert not BLOCKED_DISPLAY_KEYS & set(item)
    assert not BLOCKED_DISPLAY_KEYS & set(display)
    _assert_no_blocked_display_terms(display)


def test_display_response_tolerates_missing_metadata_and_skips_items_without_parent_asin():
    session = AgentSession(session_id="s1", user_id="u1")
    turn = AgentTurn(
        turn_index=1,
        user_input="recommend",
        feedback_constraints=FeedbackConstraints(),
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="deterministic",
            trigger_reason="test",
            agent_explanation="fallback explanation",
            risk_flags=[],
            limitations=[],
            final_items=[
                {"parent_asin": "minimal_1", "sources": ["popular"]},
                {"score": 99.0, "title": "No id"},
            ],
        ),
        candidates=[],
        ranking=[],
        fallback_used=False,
        diagnostics={},
    )
    session.turns.append(turn)

    display = build_display_record(turn, session)

    assert len(display["items"]) == 1
    assert display["items"][0] == {
        "parent_asin": "minimal_1",
        "title": None,
        "category": None,
        "price": None,
        "rating": None,
        "store": None,
        "features": [],
        "description": None,
        "image_url": None,
        "badges": ["missing_image"],
        "summary": None,
    }
    _assert_no_blocked_display_terms(display)


def _assert_no_blocked_display_terms(value):
    if isinstance(value, dict):
        for child in value.values():
            _assert_no_blocked_display_terms(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blocked_display_terms(child)
    elif isinstance(value, str):
        lowered = value.lower()
        for term in BLOCKED_DISPLAY_TERMS:
            assert term not in lowered



def _session_with_turn():
    session = AgentSession(session_id="s1", user_id="u1")
    turn = AgentTurn(
        turn_index=2,
        user_input="show me commute audio",
        feedback_constraints=FeedbackConstraints(),
        recommendation=AgentDecision(
            user_id="u1",
            strategy_name="deterministic",
            trigger_reason="test",
            agent_explanation="Internal explanation",
            risk_flags=["demo_risk"],
            limitations=[],
            final_items=[
                {
                    "parent_asin": "speaker_1",
                    "score": 12.0,
                    "base_score": 2.0,
                    "agent_boost": 10.0,
                    "final_score": 12.0,
                    "sources": ["itemcf_weak", "feedback_source_itemcf_weak"],
                    "metadata": {
                        "title_clean": "Portable Speaker",
                        "main_category": "Audio",
                        "price": "$49.99",
                        "rating": "4.5",
                        "store": "Demo Store",
                        "features": ["bluetooth", "portable"],
                        "description": "Small speaker for commute.",
                        "summary": "Good commute audio pick",
                    },
                }
            ],
        ),
        candidates=[],
        ranking=[],
        fallback_used=False,
        diagnostics={"diagnostics": "internal"},
        assistant_response="Here are safer display cards.",
    )
    session.turns.append(turn)
    return session, turn
