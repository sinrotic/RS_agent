from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from rs_core.serving.api.dependencies import get_service, require_debug_access, require_demo_endpoint_enabled
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.schemas import DemoRoundtripRequest, DemoRoundtripResponse

router = APIRouter()


@router.post("/demo/e2e", response_model=DemoRoundtripResponse, dependencies=[Depends(require_demo_endpoint_enabled), Depends(require_debug_access)])
def demo_roundtrip(
    request: DemoRoundtripRequest,
    http_request: Request,
    service: RecommendationService = Depends(get_service),
) -> DemoRoundtripResponse:
    try:
        result = service.run_demo_roundtrip(
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
