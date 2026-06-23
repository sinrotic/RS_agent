from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.common.qdrant_config import merge_qdrant_config, qdrant_config_from_env
from rs_core.serving.facades import SERVING_GOVERNANCE_GUARDRAILS

DEFAULT_CONFIG = "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml"
SERVING_CONFIG_ENV = "RS_SERVING_CONFIG"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_serving_config(config: str | Path = DEFAULT_CONFIG) -> str | Path:
    env_config = os.environ.get(SERVING_CONFIG_ENV)
    if env_config:
        return env_config
    if str(config) == DEFAULT_CONFIG:
        registry_config = _current_online_service_config()
        if registry_config:
            return registry_config
    return config


def _current_online_service_config() -> str | None:
    registry_path = PROJECT_ROOT / "configs/governance/current_route_registry.yaml"
    if not registry_path.exists():
        return None
    try:
        registry = load_config(registry_path)
    except Exception:
        return None
    routes = registry.get("routes") if isinstance(registry.get("routes"), dict) else {}
    route = routes.get("current_online_service_route") if isinstance(routes.get("current_online_service_route"), dict) else {}
    config_paths = route.get("config_paths")
    if isinstance(config_paths, list) and config_paths:
        path = Path(str(config_paths[0]))
        return str(path if path.is_absolute() else PROJECT_ROOT / path)
    return None


def _validate_serving_config(config: dict[str, Any]) -> None:
    evaluation_mode = config.get("evaluation_mode")
    if evaluation_mode not in (None, "", "none", "public_serving"):
        raise ValueError(f"Serving runtime requires evaluation_mode public_serving or omitted, got: {evaluation_mode}")
    if str(config.get("role", "")).strip().lower() == "evaluation_only":
        raise ValueError("Serving runtime rejects role:evaluation_only")
    if config.get("serving_allowed") is False:
        raise ValueError("Serving runtime rejects serving_allowed:false")
    _validate_serving_governance_guardrails(config)


def _validate_serving_governance_guardrails(config: dict[str, Any]) -> None:
    online_route = config.get("online_route")
    if not isinstance(online_route, dict):
        return
    governance = online_route.get("governance")
    if _online_route_has_candidate_inputs(online_route) and not isinstance(governance, dict):
        raise ValueError("Serving runtime requires online_route.governance for online candidate routes")
    if not isinstance(governance, dict):
        return
    for field, expected in SERVING_GOVERNANCE_GUARDRAILS.items():
        if governance.get(field) is not expected:
            raise ValueError(f"Serving runtime requires online_route.governance.{field}:{str(expected).lower()}")


def _online_route_has_candidate_inputs(online_route: dict[str, Any]) -> bool:
    return any(
        online_route.get(field)
        for field in (
            "pool500_candidates_path",
            "source_indexes",
            "online_source_indexes",
            "source_manifests",
        )
    )


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _qdrant_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    env_config = qdrant_config_from_env()
    if not env_config:
        return {}
    overrides: dict[str, Any] = {}
    _set_qdrant_override(overrides, ["rag", "hybrid", "qdrant"], config, env_config)
    _set_qdrant_override(overrides, ["rag", "qdrant"], config, env_config)
    _set_qdrant_override(overrides, ["online_route", "source_indexes", "two_tower", "qdrant"], config, env_config)
    _set_qdrant_override(overrides, ["online_retrieval", "providers", "two_tower_qdrant", "qdrant"], config, env_config)
    _set_qdrant_override(overrides, ["online_retrieval", "providers", "semantic_vector", "qdrant"], config, env_config)
    _set_qdrant_override(overrides, ["semantic_qdrant"], config, env_config)
    _set_qdrant_override(overrides, ["semantic_backend", "qdrant"], config, env_config)
    return overrides


def _set_qdrant_override(overrides: dict[str, Any], path: list[str], config: dict[str, Any], env_config: dict[str, Any]) -> None:
    base = _get_nested_mapping(config, path)
    if base is None:
        return
    cursor = overrides
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = merge_qdrant_config(base, env_config)


def _get_nested_mapping(config: dict[str, Any], path: list[str]) -> dict[str, Any] | None:
    cursor: Any = config
    for key in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor if isinstance(cursor, dict) else None


