import pytest

from rs_core.display import (
    build_display_record,
    build_public_timeline,
    validate_public_display_payload,
    validate_public_timeline_payload,
)

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
    "feedback_source",
    "deepfm_score",
    "deepfm_shadow_score",
    "feature_contract",
    "model_path",
    "ranking_replacement_allowed",
    "reward_evidence",
    "training_samples",
}
BLOCKED_DISPLAY_TERMS = {
    "agent_boost",
    "base_score",
    "coarse_score",
    "deepfm_score",
    "deepfm_shadow_score",
    "diagnostic",
    "feature_contract",
    "feedback_source",
    "fine_score",
    "final_score",
    "itemcf",
    "model_path",
    "ranking",
    "ranking_replacement_allowed",
    "rank_movement",
    "recall source",
    "rerank_score",
    "score_trace",
    "reward_evidence",
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


def test_public_timeline_uses_public_event_id_and_sanitizes_events():
    session, _turn = _session_with_turn()

    timeline = build_public_timeline(
        session,
        [{"type": "chat", "trace_ref": "internal-trace", "diagnostics_path": "outputs/internal.json"}],
    )

    assert timeline == {
        "schema_version": "rs_agent_public_timeline_v1",
        "session_id": "s1",
        "user_id": "u1",
        "events": [
            {
                "public_event_id": "s1:turn:2",
                "event_type": "chat",
                "turn_index": 2,
                "user_message": "show me commute audio",
                "assistant_message": "Here are safer display cards.",
                "display_response_index": 0,
            }
        ],
    }
    assert "trace_ref" not in timeline["events"][0]
    _assert_no_blocked_display_terms(timeline)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trace_ref", "abc"),
        ("agent_runtime_trace", []),
        ("agent_tool_trace", []),
        ("agent_tool_events", []),
        ("agent_tool_summary", {}),
        ("diagnostics_path", "outputs/diagnostics.json"),
        ("raw_export_trace_path", "outputs/export_trace.json"),
        ("ranking_evidence_path", "outputs/ranking_evidence.json"),
        ("diagnostics", {}),
        ("deepfm_score", 1.0),
        ("deepfm_shadow_score", {"raw_score": 1.0}),
        ("feature_contract", {}),
        ("model_path", "outputs/model.json"),
        ("ranking_replacement_allowed", False),
        ("context_bundle", {}),
        ("context_budget", {}),
        ("session_summary", {}),
        ("user_profile", {}),
        ("archived_turn_summaries", []),
        ("memory_snapshot", {}),
        ("memory_entries", []),
        ("memory_recall", {}),
        ("private_memory_recall", {}),
        ("typed_memory_entries", []),
        ("typed_memory_recall", {}),
        ("rag_context", {}),
        ("rag_evidence", []),
        ("feedback_source", "itemcf_weak"),
        ("recall-source", "itemcf_weak"),
        ("recall_source", "itemcf_weak"),
        ("reward", {}),
        ("reward_evidence", {}),
        ("score", 1.0),
        ("internal", "debug"),
        ("tool", "retrieve_candidates"),
        ("rag", "context"),
        ("source", "internal"),
        ("sources", ["itemcf_weak"]),
        ("training", {}),
        ("training_samples", []),
    ],
)
def test_public_display_validator_rejects_internal_fields(field: str, value):
    session, turn = _session_with_turn()
    display = build_display_record(turn, session)
    display[field] = value

    with pytest.raises(ValueError):
        validate_public_display_payload(display)


@pytest.mark.parametrize(
    "term",
    [
        "agent_tool_trace",
        "agentic_recall_candidates",
        "catalog_constraint_search",
        "deepfm_rank_candidates",
        "deepfm_score",
        "deepfm_shadow_score",
        "feature_contract",
        "model_path",
        "ranking_replacement_allowed",
        "match_specific_need_in_pool",
        "memory entry",
        "memory recall",
        "memory snapshot",
        "raw export trace",
        "rag context",
        "rag evidence",
        "raw evidence",
        "raw snippet",
        "supporting_snippets",
        "supporting snippets",
        "snippet",
        "ranking evidence",
        "rerank_for_browsing",
        "context bundle",
        "session summary",
        "user_profile",
        "diagnostics",
        "reward_evidence",
        "training_samples",
        "typed memory",
        "feedback_source",
        "recall source",
        "rag output",
        "rag result",
        "rag value",
        "tool output",
        "tool result",
        "tool value",
    ],
)
def test_public_display_validator_rejects_internal_terms(term: str):
    session, turn = _session_with_turn()
    display = build_display_record(turn, session)
    display["assistant_message"] = f"Public payload mentions {term}."

    with pytest.raises(ValueError):
        validate_public_display_payload(display)



@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", {"raw_snippet": "unredacted"}),
        ("session_id", ["internal"]),
        ("user_id", {"safe": "no"}),
        ("turn_index", {"score_trace": 1.0}),
        ("assistant_message", {"raw_snippet": "unredacted"}),
    ],
)
def test_public_display_validator_rejects_nested_values_in_scalar_fields(field: str, value):
    session, turn = _session_with_turn()
    display = build_display_record(turn, session)
    display[field] = value

    with pytest.raises(ValueError):
        validate_public_display_payload(display)


def test_public_display_validator_allows_public_text_with_generic_terms():
    session, turn = _session_with_turn()
    display = build_display_record(turn, session)
    display["assistant_message"] = "This reward-themed training item comes from a public source collection."
    display["items"][0]["title"] = "Public Source Training Reward Set"
    display["items"][0]["category"] = "Training Supplies"
    display["items"][0]["store"] = "Public Goods"
    display["items"][0]["features"] = ["source-safe", "training-friendly", "reward-themed"]
    display["items"][0]["description"] = "A public source themed training kit with reward cards."
    display["items"][0]["summary"] = "Training and reward set from public source text."

    assert validate_public_display_payload(display) == display


@pytest.mark.parametrize(
    "field,value",
    [
        ("public_event_id", {"raw_snippet": "unredacted"}),
        ("event_type", ["chat"]),
        ("turn_index", {"score_trace": 1.0}),
        ("user_message", {"raw_snippet": "user text is still a scalar"}),
        ("assistant_message", {"raw_snippet": "unredacted"}),
        ("display_response_index", [0]),
    ],
)
def test_public_timeline_validator_rejects_nested_values_in_event_scalar_fields(field: str, value):
    session, _turn = _session_with_turn()
    timeline = build_public_timeline(session)
    timeline["events"][0][field] = value

    with pytest.raises(ValueError):
        validate_public_timeline_payload(timeline)


def test_public_timeline_validator_allows_public_assistant_text_with_generic_terms():
    session, _turn = _session_with_turn()
    timeline = build_public_timeline(session)
    timeline["events"][0]["assistant_message"] = "This reward-themed training item comes from a public source collection."

    assert validate_public_timeline_payload(timeline) == timeline


@pytest.mark.parametrize(
    "term",
    [
        "long_memory",
        "raw score_trace",
        "agent_tool_trace",
        "memory recall",
        "RAG tool score",
        "itemcf",
        "feedback_source",
        "recall source",
        "final_score",
    ],
)
def test_public_display_validator_rejects_internal_terms_inside_catalog_text(term: str):
    session, turn = _session_with_turn()
    display = build_display_record(turn, session)
    display["items"][0]["summary"] = f"Public payload mentions {term}."

    with pytest.raises(ValueError):
        validate_public_display_payload(display)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda display: display["ui_state"].update({"feedback_source": "itemcf_weak"}),
        lambda display: display["ui_state"].update({"recall-source": "itemcf_weak"}),
        lambda display: display["ui_state"].update({"agentToolTrace": "hidden"}),
        lambda display: display["ui_state"].update({"supportingSnippets": "hidden"}),
        lambda display: display["ui_state"].update({"imageFallbackEnabled": True}),
        lambda display: display["ui_state"].update({"safe": {"source": "itemcf_weak"}}),
        lambda display: display["feedback_actions"][0].update({"source": "internal"}),
        lambda display: display["items"][0]["features"].append({"source": "itemcf_weak"}),
        lambda display: display["items"][0]["badges"].append({"trace_ref": "internal"}),
        lambda display: display["items"][0].update({"price": {"score": 1.0}}),
    ],
)
def test_public_display_validator_rejects_nested_internal_fields_and_non_public_shapes(mutator):
    session, turn = _session_with_turn()
    display = build_display_record(turn, session)
    mutator(display)

    with pytest.raises(ValueError):
        validate_public_display_payload(display)



def test_public_timeline_validator_rejects_trace_ref_and_requires_allowlist():
    with pytest.raises(ValueError):
        validate_public_timeline_payload(
            {
                "schema_version": "rs_agent_public_timeline_v1",
                "session_id": "s1",
                "user_id": "u1",
                "events": [
                    {
                        "trace_ref": "internal",
                        "event_type": "chat",
                        "turn_index": 1,
                        "user_message": "hello",
                        "assistant_message": "hi",
                        "display_response_index": 0,
                    }
                ],
            }
        )



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
