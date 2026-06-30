from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


def milvus_config_from_args(args: Any) -> dict[str, Any]:
    config = {
        "uri": getattr(args, "milvus_uri", None),
        "token": getattr(args, "milvus_token", None),
        "db_name": getattr(args, "milvus_db_name", None),
        "timeout": getattr(args, "milvus_timeout", None),
    }
    return compact_milvus_config(config)


_MILVUS_ENV_FIELDS = {
    "RS_MILVUS_URI": "uri",
    "RS_MILVUS_TOKEN": "token",
    "RS_MILVUS_DB_NAME": "db_name",
    "RS_MILVUS_TIMEOUT": "timeout",
}


def milvus_config_from_env(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return Milvus connection overrides from RS_MILVUS_* environment variables."""
    source = os.environ if environ is None else environ
    config: dict[str, Any] = {}
    for env_name, field_name in _MILVUS_ENV_FIELDS.items():
        raw_value = source.get(env_name)
        if raw_value in (None, ""):
            continue
        if field_name == "timeout":
            config[field_name] = _parse_milvus_timeout(raw_value, env_name)
        else:
            config[field_name] = raw_value
    return config


def merge_milvus_config(base: Mapping[str, Any] | None, override: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge Milvus config without letting empty override values erase config."""
    merged = dict(base or {})
    compact_override = compact_milvus_config(dict(override or {}))
    merged.update(compact_override)
    return merged


def compact_milvus_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if value not in (None, "")}


def _parse_milvus_timeout(raw_value: str, env_name: str) -> int:
    try:
        timeout = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer timeout in seconds, got: {raw_value!r}") from exc
    if timeout <= 0:
        raise ValueError(f"{env_name} must be positive, got: {raw_value!r}")
    return timeout
