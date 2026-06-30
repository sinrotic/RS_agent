from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from rs_core.agent.runtime_core.events import CommitIntent, RuntimePatch, ToolResult, ToolSummary, TraceEvent
from rs_core.agent.runtime_core.output_adapter import OutputAdapter


@dataclass(frozen=True)
class AgentLoopInput:
    agent_name: str
    user_input: str = ""
    session_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    phase: str = ""
    call_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentPlan:
    action: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    response_hints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "response_hints": self.response_hints,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class AgentLoopResult:
    plan: AgentPlan
    context: dict[str, Any]
    tool_results: list[ToolResult]
    tool_summary: ToolSummary
    response: dict[str, Any]
    patch: RuntimePatch
    commit_intents: list[CommitIntent]
    trace_events: list[TraceEvent]
    public_output: dict[str, Any]
    sft_output: dict[str, Any]
    internal_output: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "context": self.context,
            "tool_results": [result.to_dict() for result in self.tool_results],
            "tool_summary": self.tool_summary.to_dict(),
            "response": self.response,
            "patch": self.patch.to_dict(),
            "commit_intents": [intent.to_dict() for intent in self.commit_intents],
            "trace_events": [event.to_dict() for event in self.trace_events],
            "public_output": self.public_output,
            "sft_output": self.sft_output,
            "internal_output": self.internal_output,
        }


class ContextBuilder(Protocol):
    def build_context(self, loop_input: AgentLoopInput) -> dict[str, Any]: ...


class Planner(Protocol):
    def plan(self, loop_input: AgentLoopInput, context: dict[str, Any]) -> AgentPlan: ...


class ToolDispatcher(Protocol):
    def execute(self, plan: AgentPlan, context: dict[str, Any]) -> tuple[list[ToolResult], ToolSummary]: ...


class ResponseComposer(Protocol):
    def compose(self, loop_input: AgentLoopInput, context: dict[str, Any], plan: AgentPlan, tool_results: list[ToolResult]) -> dict[str, Any]: ...


class StateUpdater(Protocol):
    def build_patch(
        self,
        loop_input: AgentLoopInput,
        context: dict[str, Any],
        plan: AgentPlan,
        tool_results: list[ToolResult],
        response: dict[str, Any],
    ) -> tuple[RuntimePatch, list[CommitIntent]]: ...


@dataclass
class GenericAgentLoop:
    """Domain-agnostic agent loop skeleton.

    Components own all domain interpretation. The loop only coordinates the
    generic sequence and returns patches/intents; it never commits domain state.
    """

    context_builder: ContextBuilder
    planner: Planner
    tool_dispatcher: ToolDispatcher
    response_composer: ResponseComposer
    state_updater: StateUpdater
    output_adapter: OutputAdapter

    def run(self, loop_input: AgentLoopInput) -> AgentLoopResult:
        trace_events: list[TraceEvent] = [
            TraceEvent(
                step="observe_input",
                kind="input_observed",
                payload={
                    "agent_name": loop_input.agent_name,
                    "session_id": loop_input.session_id,
                    "has_input": bool(loop_input.user_input),
                    "input_length": len(loop_input.user_input),
                },
            )
        ]

        context = self.context_builder.build_context(loop_input)
        trace_events.append(TraceEvent(step="build_context", kind="context_built", payload={"context_keys": sorted(context)}))

        plan = self.planner.plan(loop_input, context)
        trace_events.append(TraceEvent(step="plan", kind="plan_created", payload={"action": plan.action, "tool_call_count": len(plan.tool_calls)}))

        tool_results, tool_summary = self.tool_dispatcher.execute(plan, context)
        trace_events.append(TraceEvent(step="execute_tools", kind="tools_executed", phase=tool_summary.phase, payload=tool_summary.to_dict()))

        response = self.response_composer.compose(loop_input, context, plan, tool_results)
        trace_events.append(TraceEvent(step="compose_response", kind="response_composed", payload={"response_keys": sorted(response)}))

        patch, commit_intents = self.state_updater.build_patch(loop_input, context, plan, tool_results, response)
        patch = RuntimePatch(
            trace_events=[*trace_events, *patch.trace_events],
            tool_results=[*tool_results, *patch.tool_results],
            diagnostics_patch=patch.diagnostics_patch,
            session_summary_patch=patch.session_summary_patch,
            output_patch=patch.output_patch,
        )
        trace_events = list(patch.trace_events)
        trace_events.append(TraceEvent(step="build_patch", kind="patch_built", payload={"commit_intent_count": len(commit_intents)}))
        patch = RuntimePatch(
            trace_events=trace_events,
            tool_results=patch.tool_results,
            diagnostics_patch=patch.diagnostics_patch,
            session_summary_patch=patch.session_summary_patch,
            output_patch=patch.output_patch,
        )

        projection_payload = {
            **response,
            "agent_name": loop_input.agent_name,
            "tool_summary": tool_summary.to_dict(),
            "diagnostics": patch.diagnostics_patch,
            "trace_events": [event.to_dict() for event in trace_events],
            "commit_intents": [intent.to_dict() for intent in commit_intents],
            **patch.output_patch,
        }
        public_output = self.output_adapter.project_public(projection_payload)
        sft_output = self.output_adapter.project_sft(projection_payload)
        internal_output = self.output_adapter.project_internal(projection_payload)
        trace_events.append(TraceEvent(step="project_output", kind="output_projected", payload={
            "public_keys": sorted(public_output),
            "sft_keys": sorted(sft_output),
            "internal_keys": sorted(internal_output),
        }))
        projection_payload = {
            **projection_payload,
            "trace_events": [event.to_dict() for event in trace_events],
        }
        public_output = self.output_adapter.project_public(projection_payload)
        sft_output = self.output_adapter.project_sft(projection_payload)
        internal_output = self.output_adapter.project_internal(projection_payload)
        patch = RuntimePatch(
            trace_events=trace_events,
            tool_results=patch.tool_results,
            diagnostics_patch=patch.diagnostics_patch,
            session_summary_patch=patch.session_summary_patch,
            output_patch=patch.output_patch,
        )

        return AgentLoopResult(
            plan=plan,
            context=context,
            tool_results=tool_results,
            tool_summary=tool_summary,
            response=response,
            patch=patch,
            commit_intents=commit_intents,
            trace_events=trace_events,
            public_output=public_output,
            sft_output=sft_output,
            internal_output=internal_output,
        )
