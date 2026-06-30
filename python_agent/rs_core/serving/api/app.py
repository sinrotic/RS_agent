from __future__ import annotations

from rs_core.serving.api.dependencies import (
    DEBUG_TOKEN_ENV,
    ENABLE_DEMO_ENV,
    ENABLE_RECALL_ENV,
    ENABLE_SIMULATION_ENV,
    LOCAL_DEV_DEFAULT_ALLOW,
    REQUEST_ID_HEADER,
    REQUEST_ID_PATTERN,
    SIMULATION_TOKEN_ENV,
    STRICT_AUTH_ENV,
    TRIAL_TOKEN_ENV,
    env_enabled as _env_enabled,
    get_service,
    matches_env_token as _matches_env_token,
    normalized_request_id as _normalized_request_id,
    request_id as _request_id,
    require_debug_access as _require_debug_access,
    require_endpoint_enabled as _require_endpoint_enabled,
    require_simulation_access as _require_simulation_access,
    require_trial_access as _require_trial_access,
    strict_auth_enabled as _strict_auth_enabled,
    token_from_request as _token_from_request,
)
from rs_core.serving.api.factory import create_app

app = create_app()

__all__ = [
    "DEBUG_TOKEN_ENV",
    "ENABLE_DEMO_ENV",
    "ENABLE_RECALL_ENV",
    "ENABLE_SIMULATION_ENV",
    "LOCAL_DEV_DEFAULT_ALLOW",
    "REQUEST_ID_HEADER",
    "REQUEST_ID_PATTERN",
    "SIMULATION_TOKEN_ENV",
    "STRICT_AUTH_ENV",
    "TRIAL_TOKEN_ENV",
    "app",
    "create_app",
    "get_service",
    "_env_enabled",
    "_matches_env_token",
    "_normalized_request_id",
    "_request_id",
    "_require_debug_access",
    "_require_endpoint_enabled",
    "_require_simulation_access",
    "_require_trial_access",
    "_strict_auth_enabled",
    "_token_from_request",
]
