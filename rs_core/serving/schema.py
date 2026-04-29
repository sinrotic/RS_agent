from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class SessionExportResponse(BaseModel):
    session_id: str
    user_id: str
    turn_count: int
    events: list[dict[str, Any]]
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


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
