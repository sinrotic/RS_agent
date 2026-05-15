from __future__ import annotations

from typing import Any

TOOL_EVENT_KEYS = ("constraint_filter_events", "feedback_rerank_events")


def collect_diagnostic_tool_events(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for key in TOOL_EVENT_KEYS:
        events.extend(event for event in diagnostics.get(key, []) if isinstance(event, dict))
    return events


def collect_turn_tool_events(turns: list[Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for turn in turns:
        events.extend(collect_diagnostic_tool_events(turn.diagnostics))
    return events


def collect_rollout_tool_events(rollouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for rollout in rollouts:
        diagnostics = rollout.get("diagnostics", {})
        events.extend(collect_diagnostic_tool_events(diagnostics))
    return events
