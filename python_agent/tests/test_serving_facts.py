from __future__ import annotations

import pytest

from rs_core.serving.domain.serving_fact import (
    ServingFact,
    ServingFactType,
    feedback_event_fact,
    recommend_request_fact,
    request_summary_fact,
    session_ended_fact,
    session_started_fact,
    turn_committed_fact,
)

pytestmark = [pytest.mark.unit, pytest.mark.serving]


def test_fact_builders_cover_serving_fact_types() -> None:
    facts = [
        session_started_fact(session_id="s1", user_id="u1", request_id="r1"),
        turn_committed_fact(
            session_id="s1",
            user_id="u1",
            turn_index=1,
            event_type="chat",
            user_message="hi",
            assistant_message="hello",
            request_id="r2",
        ),
        recommend_request_fact(request_id="r3", user_id="u1", session_id="s1", item_count=10, candidate_count=500, fallback_used=False),
        feedback_event_fact(session_id="s1", turn_index=1, action_type="like", item_id="i1", comment="good", request_id="r4"),
        session_ended_fact(session_id="s1", reason="user_exit", request_id="r5", public_summary={"turns": 1}),
        request_summary_fact(request_id="r6", endpoint="/recommend", user_id="u1", item_count=10, candidate_count=500),
    ]

    assert {fact.fact_type for fact in facts} == set(ServingFactType)
    assert all(fact.validate().valid for fact in facts)


def test_public_safe_fact_export_excludes_private_payload() -> None:
    fact = ServingFact(
        fact_type=ServingFactType.REQUEST_SUMMARY,
        fact_id="request_summary:r1",
        created_at="2026-06-22T00:00:00+00:00",
        request_id="r1",
        public_payload={"endpoint": "/recommend"},
        private_payload={"internal_trace": "hidden"},
    )

    public = fact.to_public_dict()

    assert public["public_payload"] == {"endpoint": "/recommend"}
    assert "private_payload" not in public
    assert "user_id" not in public


def test_public_payload_rejects_oracle_and_training_fields() -> None:
    fact = ServingFact(
        fact_type=ServingFactType.FEEDBACK_EVENT,
        fact_id="feedback_event:s1:1:like",
        created_at="2026-06-22T00:00:00+00:00",
        public_payload={"event": "feedback_event", "oracle": {"label": 1}},
    )

    result = fact.validate()

    assert result.valid is False
    assert any("forbidden keys" in error for error in result.errors)


def test_public_payload_rejects_forbidden_fields_inside_lists() -> None:
    fact = ServingFact(
        fact_type=ServingFactType.REQUEST_SUMMARY,
        fact_id="request_summary:r1",
        created_at="2026-06-22T00:00:00+00:00",
        public_payload={
            "event": "request_summary",
            "items": [{"item_id": "i1", "Oracle": {"hit": True}}],
            "public_summary": {"evidence": [{"label": 1}]},
        },
    )

    result = fact.validate()

    assert result.valid is False
    assert any("Oracle" in error for error in result.errors)
    assert any("label" in error for error in result.errors)


def test_oracle_payload_is_never_admitted_to_serving_fact() -> None:
    fact = ServingFact(
        fact_type=ServingFactType.RECOMMEND_REQUEST,
        fact_id="recommend_request:r1",
        created_at="2026-06-22T00:00:00+00:00",
        oracle_payload={"holdout": True},
    )

    result = fact.validate()

    assert result.valid is False
    assert "oracle_payload must be empty for serving facts" in result.errors


def test_fact_type_excludes_training_evaluation_and_user_profile() -> None:
    assert {fact_type.value for fact_type in ServingFactType}.isdisjoint({"training_fact", "evaluation_fact", "user_profile_fact"})
