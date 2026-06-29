from __future__ import annotations

from dataclasses import dataclass

from rs_core.agent.runtime_core.definition import AgentRunRequest, AgentRunResult
from rs_core.agent.runtime_core.registry import AgentRegistry


@dataclass(frozen=True)
class AgentRunner:
    registry: AgentRegistry

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        try:
            definition = self.registry.get(request.agent_name)
        except KeyError:
            return self._error_result(request, "agent_not_registered")
        if definition.supported_stages and request.stage not in definition.supported_stages:
            return self._error_result(request, "unsupported_stage")
        try:
            return definition.handler.run(request)
        except Exception as exc:  # defensive: child agent failures must stay internal
            return self._error_result(request, "handler_error", f"{type(exc).__name__}: {_safe_message(exc)}")

    @staticmethod
    def _error_result(request: AgentRunRequest, reason: str, detail: str = "") -> AgentRunResult:
        diagnostics = {"status": "error", "reason": reason, "internal_only": True}
        if detail:
            diagnostics["detail"] = detail
        return AgentRunResult(
            agent_name=request.agent_name,
            status="error",
            stage=request.stage,
            request_id=request.request_id,
            diagnostics=diagnostics,
        )


def _safe_message(exc: Exception, limit: int = 180) -> str:
    text = str(exc).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."
