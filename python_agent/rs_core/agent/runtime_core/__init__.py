"""Generic agent runtime core contracts."""

from rs_core.agent.runtime_core.config import AgentRuntimeConfig, LoopMode, parse_loop_mode
from rs_core.agent.runtime_core.definition import AgentDefinition, AgentHandler, AgentRunRequest, AgentRunResult
from rs_core.agent.runtime_core.events import CommitIntent, RuntimePatch, ToolResult, ToolSummary, TraceEvent
from rs_core.agent.runtime_core.loop import (
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
from rs_core.agent.runtime_core.output_adapter import OutputAdapter, OutputProjectionPolicy, ProjectionViolation
from rs_core.agent.runtime_core.registry import AgentRegistry
from rs_core.agent.runtime_core.runner import AgentRunner
from rs_core.agent.runtime_core.tools import ToolSpec

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
