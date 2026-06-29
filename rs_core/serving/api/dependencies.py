from __future__ import annotations

import hmac
import os
import re
import sys
from uuid import uuid4

from fastapi import HTTPException, Request

from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.runtime.composition import clear_public_serving_service_cache, get_public_serving_service

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


def get_service() -> RecommendationService:
    app_module = sys.modules.get("rs_core.serving.api.app")
    exported_get_service = getattr(app_module, "get_service", None) if app_module is not None else None
    if exported_get_service is not None and exported_get_service is not get_service:
        return exported_get_service()
    return get_public_serving_service()


def clear_service_cache() -> None:
    clear_public_serving_service_cache()


get_service.cache_clear = clear_service_cache  # type: ignore[attr-defined]


def normalized_request_id(raw: str | None) -> str:
    candidate = str(raw or "").strip()
    if candidate and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


def request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "")) or normalized_request_id(None)


def strict_auth_enabled() -> bool:
    return os.environ.get(STRICT_AUTH_ENV, "").strip().lower() not in LOCAL_DEV_DEFAULT_ALLOW


def env_enabled(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def token_from_request(request: Request) -> str:
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (
        request.headers.get("x-rs-token")
        or request.headers.get("x-debug-token")
        or request.headers.get("x-simulation-token")
        or ""
    ).strip()


def matches_env_token(request: Request, env_name: str) -> bool:
    expected = os.environ.get(env_name, "").strip()
    presented = token_from_request(request)
    return bool(expected) and hmac.compare_digest(presented, expected)


def require_trial_access(request: Request) -> None:
    if not strict_auth_enabled():
        return
    if matches_env_token(request, TRIAL_TOKEN_ENV) or matches_env_token(request, DEBUG_TOKEN_ENV):
        return
    raise HTTPException(status_code=401, detail={"code": "AUTH_REQUIRED", "message": "Trial token required"})


def require_debug_access(request: Request) -> None:
    if not strict_auth_enabled():
        return
    if matches_env_token(request, DEBUG_TOKEN_ENV):
        return
    raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Debug token required"})


def require_simulation_access(request: Request) -> None:
    if not strict_auth_enabled():
        return
    if matches_env_token(request, SIMULATION_TOKEN_ENV) or matches_env_token(request, DEBUG_TOKEN_ENV):
        return
    raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Simulation token required"})


def require_endpoint_enabled(env_name: str, *, default: bool, message: str) -> None:
    if env_enabled(env_name, default=default):
        return
    raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": message})


def require_recall_endpoint_enabled() -> None:
    require_endpoint_enabled(ENABLE_RECALL_ENV, default=True, message="Recall endpoint disabled")


def require_demo_endpoint_enabled() -> None:
    require_endpoint_enabled(ENABLE_DEMO_ENV, default=True, message="Demo endpoint disabled")


def require_simulation_endpoint_enabled() -> None:
    require_endpoint_enabled(ENABLE_SIMULATION_ENV, default=True, message="Simulation endpoints disabled")
