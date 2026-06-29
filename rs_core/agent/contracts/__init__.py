from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rs_core.agent.contracts.schema import AgentSession, AgentTurn, FeedbackConstraints, RecommendationTurnResult
from rs_core.agent.tools import AgentToolCall, AgentToolExecutionReport, AgentToolResult, AgentToolSpec


@dataclass(frozen=True)
class DialogueRequest:
    session_id: str
    message: str
    user_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DialogueResult:
    session_id: str
    display: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagEvidence:
    item_id: str
    field: str
    text: str
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RagAgentInvocation:
    stage: str
    query: str = ""
    candidate_scope: str = "current_turn_only"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeedbackEvent:
    session_id: str
    action_type: str
    item_id: str | None = None
    comment: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExplanationRequest:
    session_id: str
    item_id: str | None = None
    question: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExplanationResult:
    session_id: str
    item_id: str | None = None
    text: str = ""
    evidence: list[RagEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [evidence.to_dict() for evidence in self.evidence]
        return payload


@dataclass(frozen=True)
class SessionMemoryRef:
    session_id: str
    backend: str = "data-client-managed"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "AgentSession",
    "AgentTurn",
    "FeedbackConstraints",
    "RecommendationTurnResult",
    "AgentToolCall",
    "AgentToolExecutionReport",
    "AgentToolResult",
    "AgentToolSpec",
    "DialogueRequest",
    "DialogueResult",
    "RagEvidence",
    "RagAgentInvocation",
    "FeedbackEvent",
    "ExplanationRequest",
    "ExplanationResult",
    "SessionMemoryRef",
]
