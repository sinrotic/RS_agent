from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LoopMode(str, Enum):
    LEGACY = "legacy"
    GENERIC_SHADOW = "generic_shadow"
    GENERIC_ACTIVE = "generic_active"


def parse_loop_mode(value: Any) -> LoopMode:
    """Parse a loop mode with legacy as the safe default."""
    if value in (None, ""):
        return LoopMode.LEGACY
    normalized = str(value).strip().lower()
    try:
        return LoopMode(normalized)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in LoopMode)
        raise ValueError(f"Unsupported agent_runtime.loop_mode: {value!r}; expected one of {allowed}") from exc


@dataclass(frozen=True)
class AgentRuntimeConfig:
    loop_mode: LoopMode = LoopMode.LEGACY
    golden_diff_allowlist: tuple[str, ...] = (
        "timestamp",
        "generated_id",
        "run_id",
        "non_semantic_whitespace",
        "token_count_small_drift",
    )
    rollback_on_forbidden_leak: bool = True
    rollback_on_trace_mismatch: bool = True
    rollback_on_append_violation: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, config: dict[str, Any] | None) -> "AgentRuntimeConfig":
        raw = config or {}
        compatibility = raw.get("compatibility") if isinstance(raw.get("compatibility"), dict) else {}
        allowlist = compatibility.get("golden_diff_allowlist", cls.golden_diff_allowlist)
        return cls(
            loop_mode=parse_loop_mode(raw.get("loop_mode")),
            golden_diff_allowlist=tuple(str(item) for item in allowlist),
            rollback_on_forbidden_leak=bool(compatibility.get("rollback_on_forbidden_leak", True)),
            rollback_on_trace_mismatch=bool(compatibility.get("rollback_on_trace_mismatch", True)),
            rollback_on_append_violation=bool(compatibility.get("rollback_on_append_violation", True)),
            metadata={key: value for key, value in raw.items() if key not in {"loop_mode", "compatibility"}},
        )
