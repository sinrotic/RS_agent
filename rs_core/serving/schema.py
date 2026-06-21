from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ORACLE_FIELD_NAMES = {
    "ground_truth",
    "holdout",
    "label",
    "label_binary",
    "target_item",
    "test_item",
    "training_samples",
}


class StartSessionRequest(BaseModel):
    user_id: str | None = None


class StartSessionResponse(BaseModel):
    session_id: str


class ChatRequest(BaseModel):
    session_id: str
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    display: dict[str, Any]


class FeedbackRequest(BaseModel):
    session_id: str
    action_type: str
    item_id: str | None = None
    comment: str | None = None


class FeedbackResponse(BaseModel):
    session_id: str
    display: dict[str, Any]


FEED_EVENT_TYPES = {"click", "like", "dislike", "dwell", "show_different", "search"}
FEED_REFRESH_ACTIONS = {"rerank_existing", "rerecall_pool500", "no_refresh", "fallback_cached_or_cold"}


class HomeFeedEventRequest(BaseModel):
    session_id: str
    event_type: Literal["click", "like", "dislike", "dwell", "show_different", "search"]
    display_revision: int = Field(default=1, ge=0)
    event_id: str | None = None
    item_id: str | None = None
    query: str | None = None
    dwell_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=50)
    candidate_pool_size: int | None = Field(default=None, ge=1, le=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class FeedRefreshDecisionResponse(BaseModel):
    action: Literal["rerank_existing", "rerecall_pool500", "no_refresh", "fallback_cached_or_cold"]
    decision_source: str
    reason_code: str
    fallback_reason: str | None = None


class DisplayRefreshResponse(BaseModel):
    session_id: str
    request_id: str
    display_revision: int
    decision: FeedRefreshDecisionResponse
    display: dict[str, Any]
    items: list[dict[str, Any]]
    item_count: int
    candidate_count: int
    fallback_used: bool
    public_message: str


SESSION_END_REASONS = {"user_exit", "checkout", "persona_switch", "pagehide", "manual", "unknown"}
SESSION_END_CLIENT_EVENTS = {"manual", "checkout", "persona_change", "pagehide", "beforeunload", "unknown"}


class EndSessionRequest(BaseModel):
    session_id: str
    reason: str = "unknown"
    client_event: str | None = None
    write_summary: bool = True

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = str(value or "unknown").strip().lower()
        return normalized if normalized in SESSION_END_REASONS else "unknown"

    @field_validator("client_event")
    @classmethod
    def normalize_client_event(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value or "unknown").strip().lower()
        return normalized if normalized in SESSION_END_CLIENT_EVENTS else "unknown"


class SummaryDocumentInfo(BaseModel):
    relative_path: str | None = None
    created: bool = False
    error: str | None = None


class EndSessionResponse(BaseModel):
    session_id: str
    status: str
    turn_count: int
    summary_document: SummaryDocumentInfo | None = None


class RecommendFromSequenceRequest(BaseModel):
    user_id: str | None = None
    user_sequence: dict[str, Any]
    feedback_text: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    candidate_pool_size: int | None = Field(default=None, ge=1, le=500)
    complete_pool500: bool = False

    model_config = ConfigDict(extra="forbid")

    @field_validator("user_sequence")
    @classmethod
    def reject_oracle_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = _oracle_fields_in(value)
        if forbidden:
            raise ValueError(f"user_sequence contains evaluation-only fields: {sorted(forbidden)}")
        return value


class RecommendFromSequenceResponse(BaseModel):
    request_id: str
    display: dict[str, Any]
    items: list[dict[str, Any]]
    item_count: int
    candidate_count: int
    fallback_used: bool


class RecallRequest(BaseModel):
    user_id: str | None = None
    user_sequence: dict[str, Any]
    candidate_pool_size: int | None = Field(default=None, ge=1, le=500)
    prior_turn_items: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    @field_validator("user_sequence")
    @classmethod
    def reject_oracle_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = _oracle_fields_in(value)
        if forbidden:
            raise ValueError(f"user_sequence contains evaluation-only fields: {sorted(forbidden)}")
        return value


class RecallRetrievalSummary(BaseModel):
    target_pool_size: int | None = None
    path_count: int | None = None

    model_config = ConfigDict(extra="forbid")


class RecallResponse(BaseModel):
    request_id: str
    candidate_item_ids: list[str]
    candidate_count: int
    retrieval_summary: RecallRetrievalSummary


class ReadinessResponse(BaseModel):
    status: str
    service: str
    mode: str
    session_state: str
    online_route: dict[str, Any]


class SessionExportResponse(BaseModel):
    session_id: str
    user_id: str
    turn_count: int
    public_timeline: dict[str, Any]
    display_responses: list[dict[str, Any]]


class DemoRoundtripRequest(BaseModel):
    message: str = Field(min_length=1)
    feedback_action: str = "show_different"
    user_id: str | None = None
    item_id: str | None = None
    comment: str | None = None


class DemoRoundtripResponse(BaseModel):
    session_id: str
    first_display: dict[str, Any]
    feedback_display: dict[str, Any]
    change_summary: dict[str, Any]


class SimulationSceneRequest(BaseModel):
    role_id: str = "commuter_practical"
    max_turns: int = Field(default=4, ge=1, le=8)
    user_id: str | None = None


class SimulationSceneResponse(BaseModel):
    scene_id: str
    role: dict[str, Any]
    state: dict[str, Any]
    actions: list[dict[str, Any]]
    session: dict[str, Any]


class SimulationBatchRequest(BaseModel):
    role_ids: list[str] | None = None
    max_turns: int = Field(default=4, ge=1, le=8)
    repeats: int = Field(default=1, ge=1, le=5)
    user_id: str | None = None


class SimulationBatchResponse(BaseModel):
    batch_id: str
    summary: dict[str, Any]
    scenes: list[dict[str, Any]]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


def _oracle_fields_in(value: Any) -> set[str]:
    if isinstance(value, dict):
        fields = {str(key) for key in value if str(key) in ORACLE_FIELD_NAMES}
        for child in value.values():
            fields.update(_oracle_fields_in(child))
        return fields
    if isinstance(value, list):
        fields: set[str] = set()
        for child in value:
            fields.update(_oracle_fields_in(child))
        return fields
    return set()
