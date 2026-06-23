from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ServingFactType(str, Enum):
    SESSION_STARTED = "session_started"
    TURN_COMMITTED = "turn_committed"
    RECOMMEND_REQUEST = "recommend_request"
    FEEDBACK_EVENT = "feedback_event"
    SESSION_ENDED = "session_ended"
    REQUEST_SUMMARY = "request_summary"


EXCLUDED_FACT_TYPES = frozenset({"training_fact", "evaluation_fact", "user_profile_fact"})
FORBIDDEN_PUBLIC_KEYS = frozenset({
    "oracle",
    "oracle_label",
    "label",
    "holdout",
    "raw_prompt",
    "tool_trace",
    "diagnostics",
    "training_samples",
    "evaluation_metrics",
    "user_profile",
})


@dataclass(frozen=True)
class ServingFactValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ServingFact:
    fact_type: ServingFactType
    fact_id: str
    created_at: str
    session_id: str | None = None
    request_id: str | None = None
    user_id: str | None = None
    public_payload: dict[str, Any] = field(default_factory=dict)
    private_payload: dict[str, Any] = field(default_factory=dict)
    oracle_payload: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> ServingFactValidationResult:
        errors: list[str] = []
        if not self.fact_id:
            errors.append("fact_id is required")
        if not self.created_at:
            errors.append("created_at is required")
        if self.fact_type.value in EXCLUDED_FACT_TYPES:
            errors.append(f"excluded fact type is not allowed: {self.fact_type.value}")
        public_forbidden = _find_forbidden_keys(self.public_payload)
        if public_forbidden:
            errors.append(f"public_payload contains forbidden keys: {sorted(public_forbidden)}")
        if self.oracle_payload:
            errors.append("oracle_payload must be empty for serving facts")
        return ServingFactValidationResult(valid=not errors, errors=tuple(errors))

    def to_public_dict(self) -> dict[str, Any]:
        validation = self.validate()
        if not validation.valid:
            raise ValueError("invalid public serving fact: " + "; ".join(validation.errors))
        return {
            "fact_type": self.fact_type.value,
            "fact_id": self.fact_id,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "public_payload": dict(self.public_payload),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def session_started_fact(*, session_id: str, user_id: str, request_id: str | None = None) -> ServingFact:
    return ServingFact(
        fact_type=ServingFactType.SESSION_STARTED,
        fact_id=f"session_started:{session_id}",
        created_at=utc_now_iso(),
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        public_payload={"event": "session_started"},
    )


def turn_committed_fact(
    *,
    session_id: str,
    user_id: str,
    turn_index: int,
    event_type: str,
    user_message: str,
    assistant_message: str,
    request_id: str | None = None,
) -> ServingFact:
    return ServingFact(
        fact_type=ServingFactType.TURN_COMMITTED,
        fact_id=f"turn_committed:{session_id}:{turn_index}",
        created_at=utc_now_iso(),
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        public_payload={
            "event": "turn_committed",
            "turn_index": turn_index,
            "event_type": event_type,
            "user_message": user_message,
            "assistant_message": assistant_message,
        },
    )


def recommend_request_fact(
    *,
    request_id: str,
    user_id: str | None,
    session_id: str | None = None,
    item_count: int | None = None,
    candidate_count: int | None = None,
    fallback_used: bool | None = None,
) -> ServingFact:
    return ServingFact(
        fact_type=ServingFactType.RECOMMEND_REQUEST,
        fact_id=f"recommend_request:{request_id}",
        created_at=utc_now_iso(),
        session_id=session_id,
        request_id=request_id,
        user_id=user_id,
        public_payload={
            "event": "recommend_request",
            "item_count": item_count,
            "candidate_count": candidate_count,
            "fallback_used": fallback_used,
        },
    )


def feedback_event_fact(
    *,
    session_id: str,
    turn_index: int,
    action_type: str,
    item_id: str | None = None,
    comment: str | None = None,
    request_id: str | None = None,
) -> ServingFact:
    return ServingFact(
        fact_type=ServingFactType.FEEDBACK_EVENT,
        fact_id=f"feedback_event:{session_id}:{turn_index}:{action_type}",
        created_at=utc_now_iso(),
        session_id=session_id,
        request_id=request_id,
        public_payload={
            "event": "feedback_event",
            "turn_index": turn_index,
            "action_type": action_type,
            "item_id": item_id,
            "comment": comment,
        },
    )


def session_ended_fact(
    *,
    session_id: str,
    reason: str,
    request_id: str | None = None,
    public_summary: dict[str, Any] | None = None,
) -> ServingFact:
    return ServingFact(
        fact_type=ServingFactType.SESSION_ENDED,
        fact_id=f"session_ended:{session_id}",
        created_at=utc_now_iso(),
        session_id=session_id,
        request_id=request_id,
        public_payload={"event": "session_ended", "reason": reason, "public_summary": public_summary or {}},
    )


def request_summary_fact(
    *,
    request_id: str,
    endpoint: str,
    user_id: str | None = None,
    item_count: int | None = None,
    candidate_count: int | None = None,
    fallback_used: bool | None = None,
    public_summary: dict[str, Any] | None = None,
) -> ServingFact:
    return ServingFact(
        fact_type=ServingFactType.REQUEST_SUMMARY,
        fact_id=f"request_summary:{request_id}",
        created_at=utc_now_iso(),
        request_id=request_id,
        user_id=user_id,
        public_payload={
            "event": "request_summary",
            "endpoint": endpoint,
            "item_count": item_count,
            "candidate_count": candidate_count,
            "fallback_used": fallback_used,
            "public_summary": public_summary or {},
        },
    )


def _find_forbidden_keys(payload: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if normalized_key in FORBIDDEN_PUBLIC_KEYS:
                found.add(str(key))
            found.update(_find_forbidden_keys(value))
    elif isinstance(payload, (list, tuple, set)):
        for value in payload:
            found.update(_find_forbidden_keys(value))
    return found


__all__ = (
    "ServingFactType",
    "EXCLUDED_FACT_TYPES",
    "FORBIDDEN_PUBLIC_KEYS",
    "ServingFactValidationResult",
    "ServingFact",
    "utc_now_iso",
    "session_started_fact",
    "turn_committed_fact",
    "recommend_request_fact",
    "feedback_event_fact",
    "session_ended_fact",
    "request_summary_fact",
)
