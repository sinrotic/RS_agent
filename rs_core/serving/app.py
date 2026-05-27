from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from rs_core.serving.schema import (
    ChatRequest,
    ChatResponse,
    DemoRoundtripRequest,
    DemoRoundtripResponse,
    FeedbackRequest,
    FeedbackResponse,
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
from rs_core.serving.service import DEFAULT_CONFIG, RecommendationService, SessionNotFoundError
from rs_core.simulation import run_simulation_batch, run_simulation_scene

app = FastAPI(title="RS Agent Serving Demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(SessionNotFoundError)
def session_not_found_handler(request: Request, exc: SessionNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "SESSION_NOT_FOUND", "message": "Unknown session_id"}},
    )


@lru_cache(maxsize=1)
def get_service() -> RecommendationService:
    return RecommendationService(DEFAULT_CONFIG)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "rs-agent-serving",
        "mode": "single-process-demo",
    }


@app.post("/session/start", response_model=StartSessionResponse)
def start_session(request: StartSessionRequest) -> StartSessionResponse:
    session_id = get_service().start_session(request.user_id)
    return StartSessionResponse(session_id=session_id)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    result = get_service().chat(request.session_id, request.message)
    return ChatResponse(session_id=result.session_id, display=result.display)


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(request: FeedbackRequest) -> FeedbackResponse:
    try:
        result = get_service().feedback(request.session_id, request.action_type, request.item_id, request.comment)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FeedbackResponse(session_id=result.session_id, display=result.display)


@app.post("/recommend", response_model=RecommendFromSequenceResponse)
def recommend_from_sequence(request: RecommendFromSequenceRequest) -> RecommendFromSequenceResponse:
    try:
        result = get_service().recommend_from_sequence(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendFromSequenceResponse(**result)


@app.get("/session/{session_id}", response_model=SessionExportResponse)
def export_session(session_id: str) -> SessionExportResponse:
    return SessionExportResponse(**get_service().export_session(session_id))


@app.post("/demo/e2e", response_model=DemoRoundtripResponse)
def demo_roundtrip(request: DemoRoundtripRequest) -> DemoRoundtripResponse:
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
def simulation_scene(request: SimulationSceneRequest) -> SimulationSceneResponse:
    try:
        scene = run_simulation_scene(get_service(), request.role_id, max_turns=request.max_turns, user_id=request.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown simulation role_id: {request.role_id}") from exc
    return SimulationSceneResponse(**scene)


@app.post("/simulation/batch", response_model=SimulationBatchResponse)
def simulation_batch(request: SimulationBatchRequest) -> SimulationBatchResponse:
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
