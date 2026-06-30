from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.runtime.config import DEFAULT_CONFIG


def _optional_limit_users() -> int | None:
    raw = os.getenv("RS_SERVING_LIMIT_USERS")
    if raw is None or not raw.strip():
        return None
    return int(raw)


@lru_cache(maxsize=1)
def get_recommendation_service() -> RecommendationService:
    """Build the shared single-process recommendation service for service entrypoints."""

    config = os.getenv("RS_SERVING_CONFIG")
    kwargs = {"limit_users": _optional_limit_users()}
    if config:
        kwargs["config"] = Path(config)
    return RecommendationService(**kwargs)


def get_online_recommender() -> Any:
    """Return the online recommender from the shared serving composition."""

    return get_recommendation_service().online_recommender


def get_agent_recommendation_service() -> RecommendationService:
    """Return the shared serving service for agent orchestration entrypoints."""

    return get_recommendation_service()


def clear_recommendation_service_cache() -> None:
    get_recommendation_service.cache_clear()


@lru_cache(maxsize=1)
def get_public_serving_service() -> RecommendationService:
    """Build the main FastAPI recommendation service for public serving."""

    return RecommendationService(DEFAULT_CONFIG, config_overrides={"evaluation_mode": "public_serving"})


def clear_public_serving_service_cache() -> None:
    get_public_serving_service.cache_clear()


__all__ = [
    "clear_public_serving_service_cache",
    "clear_recommendation_service_cache",
    "get_agent_recommendation_service",
    "get_online_recommender",
    "get_public_serving_service",
    "get_recommendation_service",
]
