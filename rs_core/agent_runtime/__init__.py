"""Domain-agnostic agent runtime contracts.

This package intentionally keeps recommendation/simulation domain objects out of
its public core. Domain adapters translate their own state into these contracts.
"""

from rs_core.agent_runtime.core.config import AgentRuntimeConfig, LoopMode, parse_loop_mode
from rs_core.agent_runtime.core.definition import AgentDefinition, AgentHandler, AgentRunRequest, AgentRunResult
from rs_core.agent_runtime.core.events import (
    CommitIntent,
    RuntimePatch,
    ToolResult,
    ToolSummary,
    TraceEvent,
)
from rs_core.agent_runtime.core.loop import (
    AgentLoopInput,
    AgentLoopResult,
    AgentPlan,
    ContextBuilder,
    GenericAgentLoop,
    Planner,
    ResponseComposer,
    StateUpdater,
    ToolCall,
    ToolDispatcher,
)
from rs_core.agent_runtime.core.output_adapter import OutputAdapter, OutputProjectionPolicy, ProjectionViolation
from rs_core.agent_runtime.core.registry import AgentRegistry
from rs_core.agent_runtime.core.runner import AgentRunner
from rs_core.agent_runtime.core.tools import ToolSpec

__all__ = [
    "AgentDefinition",
    "AgentHandler",
    "AgentLoopInput",
    "AgentLoopResult",
    "AgentPlan",
    "AgentRegistry",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentRunner",
    "AgentRuntimeConfig",
    "CommitIntent",
    "ContextBuilder",
    "GenericAgentLoop",
    "LoopMode",
    "OutputAdapter",
    "OutputProjectionPolicy",
    "Planner",
    "ProjectionViolation",
    "ResponseComposer",
    "RuntimePatch",
    "StateUpdater",
    "ToolCall",
    "ToolDispatcher",
    "ToolResult",
    "ToolSpec",
    "ToolSummary",
    "TraceEvent",
    "parse_loop_mode",
]
