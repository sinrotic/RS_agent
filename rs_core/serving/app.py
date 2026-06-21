from __future__ import annotations

import hmac
import os
import re
from functools import lru_cache
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rs_core.serving.schema import (
    ChatRequest,
    ChatResponse,
    DemoRoundtripRequest,
    DemoRoundtripResponse,
    EndSessionRequest,
    EndSessionResponse,
    FeedbackRequest,
    FeedbackResponse,
    DisplayRefreshResponse,
    HomeFeedEventRequest,
    ReadinessResponse,
    RecallRequest,
    RecallResponse,
    RecommendFromSequenceRequest,
    RecommendFromSequenceResponse,
    SessionExportResponse,
    SimulationBatchRequest,
    SimulationBatchResponse,
    SimulationSceneRequest,
    SimulationSceneResponse,
    StartSessionRequest,
    StartSessionResponse,
)
from rs_core.serving.service import DEFAULT_CONFIG, RecommendationService, SessionEndedError, SessionNotFoundError
from rs_core.simulation import run_simulation_batch, run_simulation_scene

app = FastAPI(title="RS Agent Serving Demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
TRIAL_TOKEN_ENV = "RS_TRIAL_TOKEN"
DEBUG_TOKEN_ENV = "RS_DEBUG_TOKEN"
SIMULATION_TOKEN_ENV = "RS_SIMULATION_TOKEN"
STRICT_AUTH_ENV = "RS_SERVING_STRICT_AUTH"
ENABLE_RECALL_ENV = "RS_ENABLE_RECALL_ENDPOINT"
ENABLE_DEMO_ENV = "RS_ENABLE_DEMO_ENDPOINT"
ENABLE_SIMULATION_ENV = "RS_ENABLE_SIMULATION_ENDPOINTS"
LOCAL_DEV_DEFAULT_ALLOW = {"", "0", "false", "no"}


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = _normalized_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


@app.exception_handler(SessionNotFoundError)
def session_not_found_handler(request: Request, exc: SessionNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "SESSION_NOT_FOUND", "message": "Unknown session_id"}},
    )


@app.exception_handler(SessionEndedError)
def session_ended_handler(request: Request, exc: SessionEndedError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": {"code": "SESSION_ENDED", "message": "Session has already ended"}},
    )


@lru_cache(maxsize=1)
def get_service() -> RecommendationService:
    return RecommendationService(DEFAULT_CONFIG, config_overrides={"evaluation_mode": "public_serving"})


def _normalized_request_id(raw: str | None) -> str:
    candidate = str(raw or "").strip()
    if candidate and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


def _strict_auth_enabled() -> bool:
    return os.environ.get(STRICT_AUTH_ENV, "").strip().lower() not in LOCAL_DEV_DEFAULT_ALLOW


def _env_enabled(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _token_from_request(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (
        request.headers.get("x-rs-token")
        or request.headers.get("x-debug-token")
        or request.headers.get("x-simulation-token")
        or ""
    ).strip()


def _matches_env_token(request: Request, env_name: str) -> bool:
    expected = os.environ.get(env_name, "").strip()
    presented = _token_from_request(request)
    return bool(expected) and hmac.compare_digest(presented, expected)


def _require_trial_access(request: Request) -> None:
    if not _strict_auth_enabled():
        return
    if _matches_env_token(request, TRIAL_TOKEN_ENV) or _matches_env_token(request, DEBUG_TOKEN_ENV):
        return
    raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED", "message": "Trial token required"})


def _require_debug_access(request: Request) -> None:
    if not _strict_auth_enabled():
        return
    if _matches_env_token(request, DEBUG_TOKEN_ENV):
        return
    raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Debug token required"})


def _require_simulation_access(request: Request) -> None:
    if not _strict_auth_enabled():
        return
    if _matches_env_token(request, SIMULATION_TOKEN_ENV) or _matches_env_token(request, DEBUG_TOKEN_ENV):
        return
    raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Simulation token required"})


def _require_endpoint_enabled(env_name: str, *, default: bool, message: str) -> None:
    if _env_enabled(env_name, default=default):
        return
    raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": message})


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or _normalized_request_id(None)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "rs-agent-serving",
        "mode": "online-service",
        "session_state": "single_process_in_memory",
    }


@app.get("/ready", response_model=ReadinessResponse)
def ready(http_request: Request) -> ReadinessResponse:
    _require_trial_access(http_request)
    return ReadinessResponse(**get_service().readiness())


@app.post("/session/start", response_model=StartSessionResponse)
def start_session(request: StartSessionRequest, http_request: Request) -> StartSessionResponse:
    _require_trial_access(http_request)
    session_id = get_service().start_session(request.user_id, request_id=_request_id(http_request))
    return StartSessionResponse(session_id=session_id)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request) -> ChatResponse:
    _require_trial_access(http_request)
    result = get_service().chat(request.session_id, request.message, request_id=_request_id(http_request))
    return ChatResponse(session_id=result.session_id, display=result.display)


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(request: FeedbackRequest, http_request: Request) -> FeedbackResponse:
    _require_trial_access(http_request)
    try:
        result = get_service().feedback(request.session_id, request.action_type, request.item_id, request.comment, request_id=_request_id(http_request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FeedbackResponse(session_id=result.session_id, display=result.display)


@app.post("/session/end", response_model=EndSessionResponse)
def end_session(request: EndSessionRequest, http_request: Request) -> EndSessionResponse:
    _require_trial_access(http_request)
    result = get_service().end_session(
        request.session_id,
        reason=request.reason,
        client_event=request.client_event,
        write_summary=request.write_summary,
        request_id=_request_id(http_request),
    )
    return EndSessionResponse(**result)


@app.post("/recommend", response_model=RecommendFromSequenceResponse)
def recommend_from_sequence(request: RecommendFromSequenceRequest, http_request: Request) -> RecommendFromSequenceResponse:
    _require_trial_access(http_request)
    try:
        result = get_service().recommend_from_sequence(request, request_id=_request_id(http_request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendFromSequenceResponse(**result)


@app.post("/feed/refresh", response_model=DisplayRefreshResponse)
def feed_refresh(request: HomeFeedEventRequest, http_request: Request) -> DisplayRefreshResponse:
    _require_trial_access(http_request)
    try:
        result = get_service().feed_refresh(request, request_id=_request_id(http_request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DisplayRefreshResponse(**result)


@app.post("/recall", response_model=RecallResponse)
def recall(request: RecallRequest, http_request: Request) -> RecallResponse:
    _require_endpoint_enabled(ENABLE_RECALL_ENV, default=True, message="Recall endpoint disabled")
    _require_debug_access(http_request)
    try:
        result = get_service().recall(request, request_id=_request_id(http_request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecallResponse(**result)


@app.get("/session/{session_id}", response_model=SessionExportResponse)
def export_session(session_id: str, http_request: Request) -> SessionExportResponse:
    _require_trial_access(http_request)
    return SessionExportResponse(**get_service().export_session(session_id))


@app.post("/demo/e2e", response_model=DemoRoundtripResponse)
def demo_roundtrip(request: DemoRoundtripRequest, http_request: Request) -> DemoRoundtripResponse:
    _require_endpoint_enabled(ENABLE_DEMO_ENV, default=True, message="Demo endpoint disabled")
    _require_debug_access(http_request)
    try:
        result = get_service().run_demo_roundtrip(
            message=request.message,
            feedback_action=request.feedback_action,
            user_id=request.user_id,
            item_id=request.item_id,
            comment=request.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DemoRoundtripResponse(
        session_id=result.session_id,
        first_display=result.first_display,
        feedback_display=result.feedback_display,
        change_summary=result.change_summary,
    )


@app.post("/simulation/scene", response_model=SimulationSceneResponse)
def simulation_scene(request: SimulationSceneRequest, http_request: Request) -> SimulationSceneResponse:
    _require_endpoint_enabled(ENABLE_SIMULATION_ENV, default=True, message="Simulation endpoints disabled")
    _require_simulation_access(http_request)
    try:
        scene = run_simulation_scene(get_service(), request.role_id, max_turns=request.max_turns, user_id=request.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown simulation role_id: {request.role_id}") from exc
    return SimulationSceneResponse(**scene)


@app.post("/simulation/batch", response_model=SimulationBatchResponse)
def simulation_batch(request: SimulationBatchRequest, http_request: Request) -> SimulationBatchResponse:
    _require_endpoint_enabled(ENABLE_SIMULATION_ENV, default=True, message="Simulation endpoints disabled")
    _require_simulation_access(http_request)
    try:
        batch = run_simulation_batch(
            get_service(),
            role_ids=request.role_ids,
            max_turns=request.max_turns,
            repeats=request.repeats,
            user_id=request.user_id,
        )
    except KeyError as exc:
        role_id = exc.args[0] if exc.args else "unknown"
        raise HTTPException(status_code=422, detail=f"Unknown simulation role_id: {role_id}") from exc
    return SimulationBatchResponse(**batch)
