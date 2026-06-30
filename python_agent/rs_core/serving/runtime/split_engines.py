from __future__ import annotations

from functools import lru_cache

from rs_core.agent.engine import AgentOrchestrationEngine
from rs_core.online.engine import OnlineRecommendationEngine
from rs_core.serving.runtime.composition import get_recommendation_service


@lru_cache(maxsize=1)
def _cached_online_engine() -> OnlineRecommendationEngine:
    service = get_recommendation_service()
    return OnlineRecommendationEngine(recommender=service.online_recommender)


def get_online_engine() -> OnlineRecommendationEngine:
    return _cached_online_engine()


def clear_online_engine_cache() -> None:
    _cached_online_engine.cache_clear()


get_online_engine.cache_clear = clear_online_engine_cache  # type: ignore[attr-defined]


@lru_cache(maxsize=1)
def _cached_agent_engine() -> AgentOrchestrationEngine:
    return AgentOrchestrationEngine(service=get_recommendation_service())


def get_agent_engine() -> AgentOrchestrationEngine:
    return _cached_agent_engine()


def clear_agent_engine_cache() -> None:
    _cached_agent_engine.cache_clear()


get_agent_engine.cache_clear = clear_agent_engine_cache  # type: ignore[attr-defined]


__all__ = [
    "clear_agent_engine_cache",
    "clear_online_engine_cache",
    "get_agent_engine",
    "get_online_engine",
]
