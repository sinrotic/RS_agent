from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


TRACE_VISIBILITIES = frozenset({"public", "sft", "internal"})
TOOL_STATUSES = frozenset({"ok", "success", "skipped", "error"})


@dataclass(frozen=True)
class TraceEvent:
    step: str
    kind: str
    status: str = "ok"
    phase: str | None = None
    timestamp: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    visibility: str = "internal"

    def __post_init__(self) -> None:
        if self.visibility not in TRACE_VISIBILITIES:
            raise ValueError(f"Unsupported trace visibility: {self.visibility}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolSummary:
    supported: bool
    phase: str
    requested_count: int = 0
    result_count: int = 0
    executed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    phase: str
    status: str
    reason: str = ""
    error_type: str | None = None
    message: str = ""
    output: Any | None = None

    def __post_init__(self) -> None:
        if self.status not in TOOL_STATUSES:
            raise ValueError(f"Unsupported tool status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimePatch:
    trace_events: list[TraceEvent] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    diagnostics_patch: dict[str, Any] = field(default_factory=dict)
    session_summary_patch: dict[str, Any] = field(default_factory=dict)
    output_patch: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_events": [event.to_dict() for event in self.trace_events],
            "tool_results": [result.to_dict() for result in self.tool_results],
            "diagnostics_patch": self.diagnostics_patch,
            "session_summary_patch": self.session_summary_patch,
            "output_patch": self.output_patch,
        }


@dataclass(frozen=True)
class CommitIntent:
    intent_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    owner: str = "future_domain_builder"
    append_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
