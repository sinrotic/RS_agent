from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from rs_core.serving.api.dependencies import get_service, request_id, require_trial_access
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.schemas import (
    ChatRequest,
    ChatResponse,
    DisplayRefreshResponse,
    EndSessionRequest,
    EndSessionResponse,
    FeedbackRequest,
    FeedbackResponse,
    HomeFeedEventRequest,
    RecommendFromSequenceRequest,
    RecommendFromSequenceResponse,
    SessionExportResponse,
    StartSessionRequest,
    StartSessionResponse,
)

router = APIRouter()


@router.post("/session/start", response_model=StartSessionResponse, dependencies=[Depends(require_trial_access)])
def start_session(
    request: StartSessionRequest,
    http_request: Request,
    service: RecommendationService = Depends(get_service),
) -> StartSessionResponse:
    session_id = service.start_session(request.user_id, request_id=request_id(http_request))
    return StartSessionResponse(session_id=session_id)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_trial_access)])
def chat(request: ChatRequest, http_request: Request, service: RecommendationService = Depends(get_service)) -> ChatResponse:
    result = service.chat(request.session_id, request.message, request_id=request_id(http_request))
    return ChatResponse(session_id=result.session_id, display=result.display)


@router.post("/feedback", response_model=FeedbackResponse, dependencies=[Depends(require_trial_access)])
def feedback(request: FeedbackRequest, http_request: Request, service: RecommendationService = Depends(get_service)) -> FeedbackResponse:
    try:
        result = service.feedback(
            request.session_id,
            request.action_type,
            request.item_id,
            request.comment,
            request_id=request_id(http_request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FeedbackResponse(session_id=result.session_id, display=result.display)


@router.post("/session/end", response_model=EndSessionResponse, dependencies=[Depends(require_trial_access)])
def end_session(request: EndSessionRequest, http_request: Request, service: RecommendationService = Depends(get_service)) -> EndSessionResponse:
    result = service.end_session(
        request.session_id,
        reason=request.reason,
        client_event=request.client_event,
        write_summary=request.write_summary,
        request_id=request_id(http_request),
    )
    return EndSessionResponse(**result)


@router.post("/recommend", response_model=RecommendFromSequenceResponse, dependencies=[Depends(require_trial_access)])
def recommend_from_sequence(
    request: RecommendFromSequenceRequest,
    http_request: Request,
    service: RecommendationService = Depends(get_service),
) -> RecommendFromSequenceResponse:
    try:
        result = service.recommend_from_sequence(request, request_id=request_id(http_request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecommendFromSequenceResponse(**result)


@router.post("/feed/refresh", response_model=DisplayRefreshResponse, dependencies=[Depends(require_trial_access)])
def feed_refresh(
    request: HomeFeedEventRequest,
    http_request: Request,
    service: RecommendationService = Depends(get_service),
) -> DisplayRefreshResponse:
    try:
        result = service.feed_refresh(request, request_id=request_id(http_request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DisplayRefreshResponse(**result)


@router.get("/session/{session_id}", response_model=SessionExportResponse, dependencies=[Depends(require_trial_access)])
def export_session(session_id: str, http_request: Request, service: RecommendationService = Depends(get_service)) -> SessionExportResponse:
    return SessionExportResponse(**service.export_session(session_id))
