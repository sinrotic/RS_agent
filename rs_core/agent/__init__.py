from __future__ import annotations

__all__ = ["AgentOrchestrationEngine"]


def __getattr__(name: str):
    if name == "AgentOrchestrationEngine":
        from rs_core.agent.engine import AgentOrchestrationEngine

        return AgentOrchestrationEngine
    raise AttributeError(name)
