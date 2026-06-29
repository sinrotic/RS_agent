from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends

from rs_core.serving.schemas import RankRequest, RecallRequest, RecommendFromSequenceRequest


EngineDependency = Callable[[], Any]


def create_router(get_online_engine: EngineDependency) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "online-service"}

    @router.get("/ready")
    def ready(engine: Any = Depends(get_online_engine)) -> dict[str, Any]:
        return engine.ready()

    @router.post("/recommend")
    def recommend(request: RecommendFromSequenceRequest, engine: Any = Depends(get_online_engine)) -> dict[str, Any]:
        return engine.recommend(request)

    @router.post("/recall")
    def recall(request: RecallRequest, engine: Any = Depends(get_online_engine)) -> dict[str, Any]:
        return engine.recall(request)

    @router.post("/rank")
    def rank(request: RankRequest, engine: Any = Depends(get_online_engine)) -> dict[str, Any]:
        return engine.rank(request.model_dump())

    return router


__all__ = ["create_router"]
