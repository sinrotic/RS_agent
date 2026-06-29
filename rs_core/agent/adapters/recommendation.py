from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rs_core.agent.runtime_core.contracts import LEGACY_RUNTIME_TRACE_STEP_ORDER, assert_legacy_trace_order
from rs_core.agent.contracts.schema import AgentTurn


@dataclass(frozen=True)
class RecommendationShadowReport:
    """Internal-only compatibility report for Recommendation generic shadow mode."""

    loop_mode: str = "generic_shadow"
    write_mode: str = "legacy_only"
    output_mode: str = "legacy_only"
    external_tool_mode: str = "replay_legacy_results"
    append_count: int = 0
    trace_order_valid: bool = False
    trace_steps: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RecommendationShadowAdapter:
    """Builds a non-writing shadow report from a completed legacy turn.

    The adapter intentionally does not run tools, build turns, or append to the
    recommendation session. It only checks observable compatibility metadata
    produced by the legacy path so Phase 2 can be introduced without changing
    public output or SFT-visible behavior.
    """

    diagnostics_key = "agent_runtime_shadow"

    def build_report(self, turn: AgentTurn, *, before_turn_count: int, after_turn_count: int) -> RecommendationShadowReport:
        trace = _trace_payload(turn)
        errors: list[str] = []
        try:
            assert_legacy_trace_order(trace)
            trace_order_valid = True
        except AssertionError as exc:
            trace_order_valid = False
            errors.append(str(exc))
        return RecommendationShadowReport(
            append_count=max(0, after_turn_count - before_turn_count),
            trace_order_valid=trace_order_valid,
            trace_steps=[str(step.get("name") or step.get("step") or "") for step in trace],
            errors=errors,
        )

    def attach_shadow_report(self, turn: AgentTurn, *, before_turn_count: int, after_turn_count: int) -> RecommendationShadowReport:
        report = self.build_report(turn, before_turn_count=before_turn_count, after_turn_count=after_turn_count)
        turn.diagnostics[self.diagnostics_key] = report.to_dict()
        return report


def _trace_payload(turn: AgentTurn) -> list[dict[str, Any]]:
    trace = turn.diagnostics.get("agent_runtime_trace", [])
    if isinstance(trace, list):
        return [step for step in trace if isinstance(step, dict)]
    return []


__all__ = [
    "LEGACY_RUNTIME_TRACE_STEP_ORDER",
    "RecommendationShadowAdapter",
    "RecommendationShadowReport",
]
