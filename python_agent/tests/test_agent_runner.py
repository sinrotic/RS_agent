from __future__ import annotations

from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.unit

from rs_core.agent.runtime_core import (
    AgentDefinition,
    AgentRegistry,
    AgentRunRequest,
    AgentRunResult,
    AgentRunner,
)


@dataclass
class RecordingHandler:
    status: str = "ok"
    raise_error: bool = False
    calls: list[AgentRunRequest] | None = None

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        if self.calls is None:
            self.calls = []
        self.calls.append(request)
        if self.raise_error:
            raise RuntimeError("private stack path /tmp/agent.log")
        return AgentRunResult(
            agent_name=request.agent_name,
            status=self.status,
            stage=request.stage,
            request_id=request.request_id,
            output={"handled": True},
            diagnostics={"status": self.status, "internal_only": True},
        )


def test_agent_registry_registers_and_returns_definition() -> None:
    handler = RecordingHandler()
    definition = AgentDefinition(name="rag_agent", handler=handler, supported_stages=frozenset({"post"}))
    registry = AgentRegistry()

    registry.register(definition)

    assert registry.get("rag_agent") is definition
    assert registry.definitions() == (definition,)


def test_agent_registry_rejects_duplicate_or_empty_names() -> None:
    registry = AgentRegistry()
    registry.register(AgentDefinition(name="rag_agent", handler=RecordingHandler()))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(AgentDefinition(name="rag_agent", handler=RecordingHandler()))
    with pytest.raises(ValueError, match="must not be empty"):
        registry.register(AgentDefinition(name=" ", handler=RecordingHandler()))


def test_agent_runner_invokes_registered_handler() -> None:
    handler = RecordingHandler()
    registry = AgentRegistry()
    registry.register(AgentDefinition(name="rag_agent", handler=handler, supported_stages=frozenset({"pre"})))
    runner = AgentRunner(registry)

    result = runner.run(AgentRunRequest(agent_name="rag_agent", stage="pre", request_id="req-1", payload={"query": "camp"}))

    assert result.status == "ok"
    assert result.output == {"handled": True}
    assert handler.calls is not None
    assert handler.calls[0].request_id == "req-1"
    assert handler.calls[0].payload == {"query": "camp"}


def test_agent_runner_returns_internal_error_for_missing_agent() -> None:
    result = AgentRunner(AgentRegistry()).run(AgentRunRequest(agent_name="missing", stage="pre", request_id="req-1"))

    assert result.status == "error"
    assert result.stage == "pre"
    assert result.request_id == "req-1"
    assert result.public_output == {}
    assert result.sft_output == {}
    assert result.diagnostics == {"status": "error", "reason": "agent_not_registered", "internal_only": True}


def test_agent_runner_returns_internal_error_for_unsupported_stage() -> None:
    registry = AgentRegistry()
    registry.register(AgentDefinition(name="rag_agent", handler=RecordingHandler(), supported_stages=frozenset({"post"})))

    result = AgentRunner(registry).run(AgentRunRequest(agent_name="rag_agent", stage="pre"))

    assert result.status == "error"
    assert result.public_output == {}
    assert result.sft_output == {}
    assert result.diagnostics == {"status": "error", "reason": "unsupported_stage", "internal_only": True}


def test_agent_runner_wraps_handler_exception_as_sanitized_internal_error() -> None:
    registry = AgentRegistry()
    registry.register(AgentDefinition(name="rag_agent", handler=RecordingHandler(raise_error=True)))

    result = AgentRunner(registry).run(AgentRunRequest(agent_name="rag_agent", stage="pre"))

    assert result.status == "error"
    assert result.public_output == {}
    assert result.sft_output == {}
    assert result.diagnostics["reason"] == "handler_error"
    assert result.diagnostics["internal_only"] is True
    assert "RuntimeError" in result.diagnostics["detail"]
    assert "Traceback" not in result.diagnostics["detail"]
