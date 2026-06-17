from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rs_core.common.config import load_config
from rs_core.common.openai_compatible_client import DEFAULT_API_KEY_ENV, DEFAULT_BASE_URL
from rs_core.training.data_contracts import SFT_SAMPLE_SCHEMA_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_GPT_SFT_CONFIG: dict[str, Any] = {
    "experiment_name": "gpt_sft_generation_smoke",
    "stage": "sft_data_generation",
    "dry_run": True,
    "seed": 20260614,
    "data": {
        "source": "training_signals",
        "input_path": None,
        "output_path": "outputs/training/gpt_sft_generation_smoke/sft_samples.jsonl",
        "sft_schema": SFT_SAMPLE_SCHEMA_VERSION,
        "max_samples": 3,
    },
    "gpt_sft": {
        "enabled": False,
        "provider": "openai_compatible",
        "api_base": DEFAULT_BASE_URL,
        "api_key_env": DEFAULT_API_KEY_ENV,
        "model": "gpt-4o-mini",
        "timeout_seconds": 60,
        "temperature": 0.2,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
        "strict": True,
    },
    "safety": {
        "must_select_from_candidates": True,
        "reject_unknown_item_ids": True,
        "require_schema_validation": True,
    },
}


def load_gpt_sft_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    config = deepcopy(DEFAULT_GPT_SFT_CONFIG)
    if path is not None:
        config = _merge_nested(config, _normalize_legacy_config(load_config(_resolve_project_path(path))))
    if overrides:
        config = _merge_nested(config, _normalize_legacy_config(overrides))
    _apply_env_overrides(config)
    validate_gpt_sft_config(config)
    return config


def validate_gpt_sft_config(config: dict[str, Any]) -> None:
    errors: list[str] = []
    data = _as_dict(config.get("data"))
    gpt_sft = _as_dict(config.get("gpt_sft"))

    if str(gpt_sft.get("provider", "")).strip() != "openai_compatible":
        errors.append("gpt_sft.provider must be openai_compatible")
    api_base = str(gpt_sft.get("api_base", "")).strip()
    if not api_base:
        errors.append("gpt_sft.api_base is required")
    elif not _is_safe_api_base(api_base, bool(gpt_sft.get("allow_insecure_local_api_base", False))):
        errors.append("gpt_sft.api_base must use https unless allow_insecure_local_api_base=true for localhost/127.0.0.1")
    if not str(gpt_sft.get("api_key_env", "")).strip():
        errors.append("gpt_sft.api_key_env is required")
    if not str(gpt_sft.get("model", "")).strip():
        errors.append("gpt_sft.model is required")
    if float(gpt_sft.get("timeout_seconds", 0) or 0) <= 0:
        errors.append("gpt_sft.timeout_seconds must be positive")
    if gpt_sft.get("max_tokens") is not None and int(gpt_sft.get("max_tokens", 0) or 0) <= 0:
        errors.append("gpt_sft.max_tokens must be positive when set")
    if int(data.get("max_samples", 0) or 0) <= 0:
        errors.append("data.max_samples must be positive")
    if str(data.get("sft_schema", "")).strip() != SFT_SAMPLE_SCHEMA_VERSION:
        errors.append(f"data.sft_schema must be {SFT_SAMPLE_SCHEMA_VERSION}")
    if not str(data.get("output_path", "")).strip():
        errors.append("data.output_path is required")
    _resolve_data_paths(data)

    if errors:
        raise ValueError("Invalid GPT SFT config: " + "; ".join(errors))


def _apply_env_overrides(config: dict[str, Any]) -> None:
    gpt_sft = _as_dict(config.setdefault("gpt_sft", {}))
    if os.getenv("RS_AGENT_GPT_SFT_API_BASE"):
        gpt_sft["api_base"] = os.environ["RS_AGENT_GPT_SFT_API_BASE"]
    if os.getenv("RS_AGENT_GPT_SFT_MODEL"):
        gpt_sft["model"] = os.environ["RS_AGENT_GPT_SFT_MODEL"]
    if os.getenv("RS_AGENT_GPT_SFT_API_KEY_ENV"):
        gpt_sft["api_key_env"] = os.environ["RS_AGENT_GPT_SFT_API_KEY_ENV"]


def _normalize_legacy_config(config: dict[str, Any]) -> dict[str, Any]:
    """Accept the first smoke-config draft while returning the approved nested shape."""
    normalized = deepcopy(config)
    if "api" in normalized and "gpt_sft" not in normalized:
        api = dict(normalized.pop("api") or {})
        normalized["gpt_sft"] = {
            "api_base": api.get("base_url", api.get("api_base", DEFAULT_BASE_URL)),
            "api_key_env": api.get("api_key_env", DEFAULT_API_KEY_ENV),
            "model": api.get("model", "gpt-4o-mini"),
            "timeout_seconds": api.get("timeout_seconds", 60),
            "temperature": api.get("temperature", 0.2),
            "max_tokens": api.get("max_tokens", 1200),
            "response_format": api.get("response_format", {"type": "json_object"}),
            "provider": "openai_compatible",
            "enabled": normalized.get("dry_run") is False,
            "strict": True,
        }
    if "generation" in normalized and "data" not in normalized:
        generation = dict(normalized.pop("generation") or {})
        normalized["data"] = {
            "input_path": normalized.pop("input_path", None),
            "output_path": normalized.pop("output_path", DEFAULT_GPT_SFT_CONFIG["data"]["output_path"]),
            "max_samples": generation.get("limit", 1),
            "source": "training_signals",
            "sft_schema": SFT_SAMPLE_SCHEMA_VERSION,
        }
        normalized.setdefault("gpt_sft", {})["system_prompt"] = generation.get("system_prompt")
    return normalized


def _resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _resolve_data_paths(data: dict[str, Any]) -> None:
    for key in ["input_path", "output_path"]:
        value = data.get(key)
        if value:
            data[key] = str(_resolve_project_path(str(value)))


def _is_safe_api_base(api_base: str, allow_insecure_local: bool) -> bool:
    parsed = urlparse(api_base)
    if parsed.scheme == "https":
        return True
    return allow_insecure_local and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
