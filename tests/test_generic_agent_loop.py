from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit

from rs_core.agent.runtime_core import (
    AgentLoopInput,
    AgentPlan,
    CommitIntent,
    GenericAgentLoop,
    OutputAdapter,
    OutputProjectionPolicy,
    RuntimePatch,
    ToolCall,
    ToolResult,
    ToolSummary,
)


class FakeContextBuilder:
    def build_context(self, loop_input: AgentLoopInput) -> dict[str, Any]:
        return {
            "memory_summary": loop_input.state.get("memory_summary", ""),
            "safe_catalog_view": ["visible_item_1"],
        }


class FakePlanner:
    def plan(self, loop_input: AgentLoopInput, context: dict[str, Any]) -> AgentPlan:
        return AgentPlan(
            action="recommend",
            tool_calls=[ToolCall(tool_name="search_visible_catalog", arguments={"query": loop_input.user_input}, phase="pre_response")],
            response_hints={"style": "concise"},
        )


class FakeToolDispatcher:
    def execute(self, plan: AgentPlan, context: dict[str, Any]) -> tuple[list[ToolResult], ToolSummary]:
        results = [
            ToolResult(
                tool_name=plan.tool_calls[0].tool_name,
                phase="pre_response",
                status="ok",
                output={"display_items": context["safe_catalog_view"]},
            )
        ]
        return results, ToolSummary(
            supported=True,
            phase="pre_response",
            requested_count=len(plan.tool_calls),
            result_count=len(results),
            executed_count=1,
        )


class FakeResponseComposer:
    def compose(
        self,
        loop_input: AgentLoopInput,
        context: dict[str, Any],
        plan: AgentPlan,
        tool_results: list[ToolResult],
    ) -> dict[str, Any]:
        return {
            "assistant_message": "我先给你一个可见候选：visible_item_1。",
            "display_items": tool_results[0].output["display_items"],
            "raw_trace": ["must not be projected publicly"],
        }


class FakeStateUpdater:
    def build_patch(
        self,
        loop_input: AgentLoopInput,
        context: dict[str, Any],
        plan: AgentPlan,
        tool_results: list[ToolResult],
        response: dict[str, Any],
    ) -> tuple[RuntimePatch, list[CommitIntent]]:
        patch = RuntimePatch(
            diagnostics_patch={"tool_count": len(tool_results)},
            session_summary_patch={"last_action": plan.action},
            output_patch={"safe_reason": "来自可见候选摘要"},
        )
        intents = [CommitIntent(intent_type="update_summary", payload={"last_action": plan.action}, append_allowed=False)]
        return patch, intents


def _fake_loop() -> GenericAgentLoop:
    return GenericAgentLoop(
        context_builder=FakeContextBuilder(),
        planner=FakePlanner(),
        tool_dispatcher=FakeToolDispatcher(),
        response_composer=FakeResponseComposer(),
        state_updater=FakeStateUpdater(),
        output_adapter=OutputAdapter(
            OutputProjectionPolicy(
                public_fields=frozenset({"assistant_message", "display_items", "safe_reason"}),
                sft_fields=frozenset({"assistant_message", "display_items", "tool_summary", "safe_reason"}),
                internal_fields=frozenset({"assistant_message", "display_items", "diagnostics", "trace_events", "commit_intents"}),
            )
        ),
    )


def test_generic_agent_loop_runs_component_sequence_and_projects_outputs() -> None:
    result = _fake_loop().run(
        AgentLoopInput(
            agent_name="fake_recommender",
            user_input="想要一个轻便的礼物",
            session_id="s1",
            state={"memory_summary": "prefers compact items"},
        )
    )

    assert result.context["memory_summary"] == "prefers compact items"
    assert result.plan.action == "recommend"
    assert result.tool_summary.executed_count == 1
    assert result.tool_results[0].tool_name == "search_visible_catalog"
    assert result.response["raw_trace"] == ["must not be projected publicly"]
    assert result.patch.diagnostics_patch == {"tool_count": 1}
    assert result.commit_intents[0].append_allowed is False
    assert result.public_output == {
        "assistant_message": "我先给你一个可见候选：visible_item_1。",
        "display_items": ["visible_item_1"],
        "safe_reason": "来自可见候选摘要",
    }
    assert result.sft_output["tool_summary"]["executed_count"] == 1
    assert "raw_trace" not in result.public_output
    assert "raw_trace" not in result.sft_output
    assert [event.step for event in result.trace_events] == [
        "observe_input",
        "build_context",
        "plan",
        "execute_tools",
        "compose_response",
        "build_patch",
        "project_output",
    ]
    assert [event["step"] for event in result.internal_output["trace_events"]] == [event.step for event in result.trace_events]


def test_generic_agent_loop_does_not_commit_domain_state_directly() -> None:
    result = _fake_loop().run(AgentLoopInput(agent_name="fake_agent", user_input="hello"))

    assert result.commit_intents
    assert all(not intent.append_allowed for intent in result.commit_intents)
    assert result.patch.session_summary_patch == {"last_action": "recommend"}
