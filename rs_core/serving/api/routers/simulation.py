from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from rs_core.serving.api.dependencies import get_service, require_simulation_access, require_simulation_endpoint_enabled
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.schemas import SimulationBatchRequest, SimulationBatchResponse, SimulationSceneRequest, SimulationSceneResponse
from rs_core.offline.simulation import run_simulation_batch, run_simulation_scene

router = APIRouter()


@router.post(
    "/simulation/scene",
    response_model=SimulationSceneResponse,
    dependencies=[Depends(require_simulation_endpoint_enabled), Depends(require_simulation_access)],
)
def simulation_scene(
    request: SimulationSceneRequest,
    http_request: Request,
    service: RecommendationService = Depends(get_service),
) -> SimulationSceneResponse:
    try:
        scene = run_simulation_scene(service, request.role_id, max_turns=request.max_turns, user_id=request.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"Unknown simulation role_id: {request.role_id}") from exc
    return SimulationSceneResponse(**scene)


@router.post(
    "/simulation/batch",
    response_model=SimulationBatchResponse,
    dependencies=[Depends(require_simulation_endpoint_enabled), Depends(require_simulation_access)],
)
def simulation_batch(
    request: SimulationBatchRequest,
    http_request: Request,
    service: RecommendationService = Depends(get_service),
) -> SimulationBatchResponse:
    try:
        batch = run_simulation_batch(
            service,
            role_ids=request.role_ids,
            max_turns=request.max_turns,
            repeats=request.repeats,
            user_id=request.user_id,
        )
    except KeyError as exc:
        role_id = exc.args[0] if exc.args else "unknown"
        raise HTTPException(status_code=422, detail=f"Unknown simulation role_id: {role_id}") from exc
    return SimulationBatchResponse(**batch)
