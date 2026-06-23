from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


def qdrant_config_from_args(args: Any) -> dict[str, Any]:
    config = {
        "location": getattr(args, "qdrant_location", None),
        "path": getattr(args, "qdrant_path", None),
        "url": getattr(args, "qdrant_url", None),
        "host": getattr(args, "qdrant_host", None),
        "port": getattr(args, "qdrant_port", None),
        "prefer_grpc": getattr(args, "prefer_grpc", None),
        "timeout": getattr(args, "qdrant_timeout", None),
    }
    return compact_qdrant_config(config)


_QDRANT_ENV_FIELDS = {
    "RS_QDRANT_LOCATION": "location",
    "RS_QDRANT_PATH": "path",
    "RS_QDRANT_URL": "url",
    "RS_QDRANT_HOST": "host",
    "RS_QDRANT_PORT": "port",
    "RS_QDRANT_PREFER_GRPC": "prefer_grpc",
    "RS_QDRANT_TIMEOUT": "timeout",
}


def qdrant_config_from_env(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return Qdrant connection overrides from RS_QDRANT_* environment variables.

    Only connection fields are read here; collection names and governance flags remain
    owned by the manifest/config that declares each Qdrant backend.
    """
    source = os.environ if environ is None else environ
    config: dict[str, Any] = {}
    for env_name, field_name in _QDRANT_ENV_FIELDS.items():
        raw_value = source.get(env_name)
        if raw_value in (None, ""):
            continue
        if field_name == "port":
            config[field_name] = _parse_qdrant_port(raw_value, env_name)
        elif field_name == "timeout":
            config[field_name] = _parse_qdrant_timeout(raw_value, env_name)
        elif field_name == "prefer_grpc":
            config[field_name] = _parse_qdrant_bool(raw_value, env_name)
        else:
            config[field_name] = raw_value
    return config


def merge_qdrant_config(base: Mapping[str, Any] | None, override: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge Qdrant config without letting empty override values erase config."""
    merged = dict(base or {})
    compact_override = compact_qdrant_config(dict(override or {}))
    if any(key in compact_override for key in ("location", "path", "url", "host")):
        for key in ("location", "path", "url", "host"):
            merged.pop(key, None)
    merged.update(compact_override)
    return merged


def compact_qdrant_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if value not in (None, "")}


def _parse_qdrant_port(raw_value: str, env_name: str) -> int:
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer port, got: {raw_value!r}") from exc


def _parse_qdrant_bool(raw_value: str, env_name: str) -> bool:
    lowered = str(raw_value).strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{env_name} must be a boolean value, got: {raw_value!r}")


def _parse_qdrant_timeout(raw_value: str, env_name: str) -> int:
    try:
        timeout = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer timeout in seconds, got: {raw_value!r}") from exc
    if timeout <= 0:
        raise ValueError(f"{env_name} must be positive, got: {raw_value!r}")
    return timeout
