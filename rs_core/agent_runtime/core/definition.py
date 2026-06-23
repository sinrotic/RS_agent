from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentRunRequest:
    agent_name: str
    stage: str = ""
    request_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    visibility: str = "internal_only"


@dataclass(frozen=True)
class AgentRunResult:
    agent_name: str
    status: str
    stage: str = ""
    request_id: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    public_output: dict[str, Any] = field(default_factory=dict)
    sft_output: dict[str, Any] = field(default_factory=dict)


class AgentHandler(Protocol):
    def run(self, request: AgentRunRequest) -> AgentRunResult: ...


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    handler: AgentHandler
    description: str = ""
    supported_stages: frozenset[str] = field(default_factory=frozenset)
    default_visibility: str = "internal_only"
    metadata: dict[str, Any] = field(default_factory=dict)
