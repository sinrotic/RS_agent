from __future__ import annotations

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

STATE_FACT_TYPES = (
    ServingFactType.SESSION_STARTED,
    ServingFactType.TURN_COMMITTED,
    ServingFactType.RECOMMEND_REQUEST,
    ServingFactType.FEEDBACK_EVENT,
    ServingFactType.SESSION_ENDED,
    ServingFactType.REQUEST_SUMMARY,
)

STATE_FACT_BUILDERS = (
    session_started_fact,
    turn_committed_fact,
    recommend_request_fact,
    feedback_event_fact,
    session_ended_fact,
    request_summary_fact,
)

__all__ = (
    "ServingFact",
    "ServingFactType",
    "STATE_FACT_TYPES",
    "STATE_FACT_BUILDERS",
    "session_started_fact",
    "turn_committed_fact",
    "recommend_request_fact",
    "feedback_event_fact",
    "session_ended_fact",
    "request_summary_fact",
)
