from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from rs_core.serving.api.dependencies import get_service, request_id, require_debug_access, require_recall_endpoint_enabled, require_trial_access
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.schemas import ReadinessResponse, RecallRequest, RecallResponse

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "rs-agent-serving",
        "mode": "online-service",
        "session_state": "single_process_in_memory",
    }


@router.get("/ready", response_model=ReadinessResponse, dependencies=[Depends(require_trial_access)])
def ready(service: RecommendationService = Depends(get_service)) -> ReadinessResponse:
    return ReadinessResponse(**service.readiness())


@router.post("/recall", response_model=RecallResponse, dependencies=[Depends(require_recall_endpoint_enabled), Depends(require_debug_access)])
def recall(request: RecallRequest, http_request: Request, service: RecommendationService = Depends(get_service)) -> RecallResponse:
    try:
        result = service.recall(request, request_id=request_id(http_request))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RecallResponse(**result)
