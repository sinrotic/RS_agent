from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any


_ELASTICSEARCH_ENV_FIELDS = {
    "RS_ELASTICSEARCH_URI": "uri",
    "RS_ELASTICSEARCH_URL": "uri",
    "RS_ELASTICSEARCH_INDEX": "index_name",
    "RS_ELASTICSEARCH_USERNAME": "username",
    "RS_ELASTICSEARCH_PASSWORD": "password",
    "RS_ELASTICSEARCH_API_KEY": "api_key",
    "RS_ELASTICSEARCH_TIMEOUT": "timeout",
}

_SECRET_FIELDS = {"username", "password", "api_key", "token"}
_TARGET_FIELDS = {"uri", "url", "hosts"}


def elasticsearch_config_from_args(args: Any) -> dict[str, Any]:
    config = {
        "uri": getattr(args, "elasticsearch_uri", None),
        "index_name": getattr(args, "index_name", None) or getattr(args, "elasticsearch_index", None),
        "username": getattr(args, "elasticsearch_username", None),
        "password": getattr(args, "elasticsearch_password", None),
        "api_key": getattr(args, "elasticsearch_api_key", None),
        "timeout": getattr(args, "elasticsearch_timeout", None),
    }
    return compact_elasticsearch_config(config)


def elasticsearch_config_from_env(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return Elasticsearch connection overrides from RS_ELASTICSEARCH_* environment variables."""
    source = os.environ if environ is None else environ
    config: dict[str, Any] = {}
    for env_name, field_name in _ELASTICSEARCH_ENV_FIELDS.items():
        raw_value = source.get(env_name)
        if raw_value in (None, ""):
            continue
        if field_name == "timeout":
            config[field_name] = _parse_elasticsearch_timeout(raw_value, env_name)
        else:
            config[field_name] = raw_value
    return config


def merge_elasticsearch_config(base: Mapping[str, Any] | None, override: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge Elasticsearch config without letting empty override values erase config."""
    merged = dict(base or {})
    compact_override = compact_elasticsearch_config(dict(override or {}))
    merged.update(compact_override)
    return merged


def compact_elasticsearch_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if value not in (None, "")}


def public_elasticsearch_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a public-safe summary of Elasticsearch config without endpoints or secrets."""
    source = compact_elasticsearch_config(dict(config or {}))
    return {
        "enabled": bool(source.get("enabled", bool(source))),
        "target_configured": any(source.get(key) not in (None, "") for key in _TARGET_FIELDS),
        "target_kind": elasticsearch_target_kind(source),
        "index_configured": bool(source.get("index_name") or source.get("index") or source.get("alias")),
        "has_auth": any(source.get(key) not in (None, "") for key in _SECRET_FIELDS),
    }


def elasticsearch_target_kind(config: Mapping[str, Any] | None) -> str:
    source = config or {}
    for key in ("uri", "url", "hosts"):
        if source.get(key) not in (None, ""):
            return key
    return "none"


def _parse_elasticsearch_timeout(raw_value: str, env_name: str) -> int:
    try:
        timeout = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer timeout in seconds, got: {raw_value!r}") from exc
    if timeout <= 0:
        raise ValueError(f"{env_name} must be positive, got: {raw_value!r}")
    return timeout
