from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PUBLIC_SFT_FORBIDDEN_KEYS = frozenset({
    "agent_runtime_trace",
    "raw_trace",
    "hidden_tool_result",
    "hidden_tool_results",
    "raw_rag_evidence",
    "rag_raw_evidence",
    "mcpInfo",
    "inputJSONSchema",
    "boundary_prompt",
    "loop_mode",
    "error_stack",
    "raw_tool_args",
    "raw_tool_output",
})

INTERNAL_FORBIDDEN_KEYS = frozenset({
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
})


class ProjectionViolation(ValueError):
    """Raised when a projected payload contains fields outside its visibility contract."""


@dataclass(frozen=True)
class OutputProjectionPolicy:
    public_fields: frozenset[str] = field(default_factory=frozenset)
    sft_fields: frozenset[str] = field(default_factory=frozenset)
    internal_fields: frozenset[str] = field(default_factory=frozenset)
    public_forbidden_keys: frozenset[str] = PUBLIC_SFT_FORBIDDEN_KEYS
    sft_forbidden_keys: frozenset[str] = PUBLIC_SFT_FORBIDDEN_KEYS
    internal_forbidden_keys: frozenset[str] = INTERNAL_FORBIDDEN_KEYS


@dataclass(frozen=True)
class OutputAdapter:
    """Explicit public/SFT/internal projection with deny-by-default behavior."""

    policy: OutputProjectionPolicy = field(default_factory=OutputProjectionPolicy)

    def project_public(self, payload: dict[str, Any]) -> dict[str, Any]:
        projected = _select_fields(payload, self.policy.public_fields)
        _assert_no_forbidden_keys(projected, self.policy.public_forbidden_keys, "public")
        return projected

    def project_sft(self, payload: dict[str, Any]) -> dict[str, Any]:
        projected = _select_fields(payload, self.policy.sft_fields)
        _assert_no_forbidden_keys(projected, self.policy.sft_forbidden_keys, "sft")
        return projected

    def project_internal(self, payload: dict[str, Any]) -> dict[str, Any]:
        projected = _select_fields(payload, self.policy.internal_fields)
        _assert_no_forbidden_keys(projected, self.policy.internal_forbidden_keys, "internal")
        return projected


def _select_fields(payload: dict[str, Any], allowed_fields: frozenset[str]) -> dict[str, Any]:
    return {key: payload[key] for key in allowed_fields if key in payload}


def _assert_no_forbidden_keys(payload: Any, forbidden_keys: frozenset[str], projection: str, path: str = "") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            current_path = f"{path}.{key}" if path else str(key)
            if str(key) in forbidden_keys:
                raise ProjectionViolation(f"Forbidden {projection} field: {current_path}")
            _assert_no_forbidden_keys(value, forbidden_keys, projection, current_path)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _assert_no_forbidden_keys(value, forbidden_keys, projection, f"{path}[{index}]")
