from __future__ import annotations

from dataclasses import dataclass, field
from inspect import Parameter, signature
from typing import Any, Protocol

from rs_core.agent.context import ContextBudget, budget_value, build_context_bundle, constraints_summary, ensure_session_context_state
from rs_core.agent.reward import build_reward_evidence, compute_turn_reward
from rs_core.agent.contracts.schema import AgentSession, AgentTurn, FeedbackConstraints


RUNTIME_TRACE_STEP_ORDER = [
    "observe_input",
    "memory_prefetch",
    "context_compact",
    "tool_result_budget",
    "plan_dialogue",
    "apply_constraints",
    "execute_pre_recommendation_tools",
    "recommend_or_dialogue",
    "build_turn",
    "execute_post_recommendation_tools",
    "stop_check",
    "attach_diagnostics",
    "update_session_summary",
]


class DialoguePlanLike(Protocol):
    intent: str
    action: str
    assistant_response: str
    should_recommend: bool
    diagnostics: dict[str, Any]
    response_directive: str


class AgentRuntimeHost(Protocol):
    def plan_dialogue(self, user_input: str, session: AgentSession, explanation_item_id: str | None) -> DialoguePlanLike: ...

    def apply_dialogue_plan(self, session: AgentSession, plan: DialoguePlanLike) -> FeedbackConstraints: ...

    def build_recommendation_turn(
        self,
        session: AgentSession,
        user_input: str,
        assistant_response: str,
        merge_user_input: bool,
        tool_context: dict[str, Any] | None = None,
    ) -> AgentTurn: ...

    def build_dialogue_turn(self, session: AgentSession, user_input: str, assistant_response: str) -> AgentTurn: ...


@dataclass
class RuntimeBudget:
    max_list_items: int = 5
    max_dict_items: int = 12
    max_string_chars: int = 240
    retained: int = 0
    truncated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_list_items": self.max_list_items,
            "max_dict_items": self.max_dict_items,
            "max_string_chars": self.max_string_chars,
            "retained": self.retained,
            "truncated": self.truncated,
        }


@dataclass
class RuntimeStep:
    name: str
    status: str = "ok"
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "summary": self.summary}


class AgentRuntime:
    def __init__(self, budget: RuntimeBudget | None = None, context_budget: ContextBudget | None = None) -> None:
        self.budget = budget or RuntimeBudget()
        self.context_budget = context_budget or ContextBudget()

    def run_turn(
        self,
        host: AgentRuntimeHost,
        session: AgentSession,
        user_input: str = "",
        explanation_item_id: str | None = None,
    ) -> AgentTurn:
        trace: list[RuntimeStep] = []
        normalized_input = user_input or ""
        trace.append(self._step("observe_input", {
            "has_input": bool(normalized_input),
            "input_length": len(normalized_input),
            "turn_index": len(session.turns) + 1,
            "explanation_item_id": explanation_item_id,
        }))

        memory_snapshot = self._memory_prefetch(session)
        trace.append(self._step("memory_prefetch", memory_snapshot))

        compact_before = self._compact_session(session)
        session.session_summary = compact_before
        trace.append(self._step("context_compact", compact_before))

        budget_preview = self._budget_preview(memory_snapshot, compact_before)
        trace.append(self._step("tool_result_budget", budget_preview))

        plan = host.plan_dialogue(normalized_input, session, explanation_item_id)
        trace.append(self._step("plan_dialogue", {
            "intent": plan.intent,
            "action": plan.action,
            "should_recommend": bool(plan.should_recommend),
            "diagnostic_keys": sorted(plan.diagnostics),
        }))

        before_constraints = session.active_constraints.to_dict()
        host.apply_dialogue_plan(session, plan)
        after_constraints = session.active_constraints.to_dict()
        trace.append(self._step("apply_constraints", {
            "changed": before_constraints != after_constraints,
            "active_constraints": self._constraints_summary(session.active_constraints),
        }))

        tool_context: dict[str, Any] = {}
        tool_reports = [self._execute_agent_tools(host, session, plan, "pre_recommendation", None, tool_context)]
        trace.append(self._step("execute_pre_recommendation_tools", tool_reports[-1].get("summary", {})))

        branch = "recommendation" if plan.should_recommend else "dialogue_only"
        trace.append(self._step("recommend_or_dialogue", {"branch": branch}))

        assistant_response = plan.assistant_response
        if plan.should_recommend:
            turn = self._build_recommendation_turn(
                host,
                session,
                normalized_input,
                assistant_response,
                merge_user_input=False,
                tool_context=tool_context,
            )
        else:
            turn = host.build_dialogue_turn(session, normalized_input, assistant_response)
        trace.append(self._step("build_turn", {
            "turn_index": turn.turn_index,
            "final_item_count": len(turn.recommendation.final_items),
            "candidate_count": len(turn.candidates),
            "ranking_count": len(turn.ranking),
            "fallback_used": bool(turn.fallback_used),
        }))

        tool_reports.append(self._execute_agent_tools(host, session, plan, "post_recommendation", turn, tool_context))
        trace.append(self._step("execute_post_recommendation_tools", tool_reports[-1].get("summary", {})))

        tool_diagnostics = self._tool_diagnostics(tool_reports)
        turn.diagnostics.update(tool_diagnostics)
        stop_check_result = self._stop_check(turn)
        trace.append(self._step("stop_check", stop_check_result))

        turn.diagnostics.update({
            "conversation_intent": plan.intent,
            "agent_action": plan.action,
            "should_recommend": bool(plan.should_recommend),
            "assistant_response": plan.assistant_response,
            "response_directive": getattr(plan, "response_directive", ""),
            **plan.diagnostics,
            **tool_diagnostics,
            "memory_snapshot": self._budget_value(memory_snapshot, RuntimeBudget()),
            "tool_result_budget": budget_preview,
            "stop_check_result": stop_check_result,
        })
        trace.append(self._step("attach_diagnostics", {
            "diagnostic_keys": sorted(turn.diagnostics),
            "runtime_diagnostic_keys": [
                "memory_snapshot",
                "tool_result_budget",
                "agent_tool_trace",
                "agent_tool_events",
                "agent_tool_summary",
                "stop_check_result",
                "agent_runtime_trace",
            ],
        }))

        ensure_session_context_state(session, self.context_budget)
        session.session_summary = self._compact_session(session)
        trace.append(self._step("update_session_summary", session.session_summary))

        trace_payload = self._trace_payload(trace)
        turn.diagnostics["agent_runtime_trace"] = trace_payload
        session.runtime_trace.append(self._session_trace_summary(turn, trace_payload, stop_check_result))
        session.runtime_trace[:] = session.runtime_trace[-20:]
        return turn

    def _step(self, name: str, summary: dict[str, Any]) -> RuntimeStep:
        return RuntimeStep(name=name, summary=self._budget_value(summary, RuntimeBudget()))

    def _build_recommendation_turn(
        self,
        host: AgentRuntimeHost,
        session: AgentSession,
        user_input: str,
        assistant_response: str,
        *,
        merge_user_input: bool,
        tool_context: dict[str, Any],
    ) -> AgentTurn:
        builder = host.build_recommendation_turn
        if self._callable_accepts_keyword(builder, "tool_context"):
            return builder(session, user_input, assistant_response, merge_user_input, tool_context=tool_context)
        return builder(session, user_input, assistant_response, merge_user_input)

    def _execute_agent_tools(
        self,
        host: AgentRuntimeHost,
        session: AgentSession,
        plan: DialoguePlanLike,
        phase: str,
        turn: AgentTurn | None,
        tool_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        executor = getattr(host, "execute_agent_tools", None)
        if not callable(executor):
            return {"phase": phase, "results": [], "summary": {"supported": False, "result_count": 0}}
        try:
            if self._callable_accepts_keyword(executor, "tool_context"):
                report = executor(session, plan, phase, turn, tool_context=tool_context)
            else:
                report = executor(session, plan, phase, turn)
        except Exception as exc:
            return {
                "phase": phase,
                "results": [{
                    "name": "agent_tool_dispatcher",
                    "phase": phase,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "event": {
                        "tool_name": "agent_tool_dispatcher",
                        "phase": phase,
                        "status": "error",
                        "error_type": type(exc).__name__,
                    },
                }],
                "summary": {"supported": True, "status": "error", "result_count": 1},
            }
        if hasattr(report, "to_dict"):
            report = report.to_dict()
        if not isinstance(report, dict):
            report = {}
        results = report.get("results", []) if isinstance(report.get("results"), list) else []
        summary = report.get("summary", {}) if isinstance(report.get("summary"), dict) else {}
        summary.setdefault("supported", True)
        summary.setdefault("result_count", len(results))
        return {"phase": report.get("phase", phase), "results": results, "summary": summary}

    def _callable_accepts_keyword(self, func: Any, keyword: str) -> bool:
        try:
            parameters = signature(func).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.kind is Parameter.VAR_KEYWORD or parameter.name == keyword
            for parameter in parameters
        )

    def _tool_diagnostics(self, reports: list[dict[str, Any]]) -> dict[str, Any]:
        trace: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        for report in reports:
            for result in report.get("results", []):
                if not isinstance(result, dict):
                    continue
                trace.append(result)
                event = result.get("event")
                if isinstance(event, dict) and event:
                    events.append(event)
        return {
            "agent_tool_trace": trace,
            "agent_tool_events": events,
            "agent_tool_summary": {
                "phase_count": len(reports),
                "result_count": len(trace),
                "event_count": len(events),
                "executed_count": sum(
                    int(report.get("summary", {}).get("executed_count", 0))
                    for report in reports
                    if isinstance(report.get("summary"), dict)
                ),
                "skipped_count": sum(1 for result in trace if result.get("status") == "skipped"),
                "error_count": sum(1 for result in trace if result.get("status") == "error"),
            },
        }

    def _memory_prefetch(self, session: AgentSession) -> dict[str, Any]:
        bundle = build_context_bundle(session, self.context_budget)
        return bundle.memory_snapshot(session.session_summary)

    def _compact_session(self, session: AgentSession) -> dict[str, Any]:
        bundle = build_context_bundle(session, self.context_budget)
        return bundle.session_summary(session.active_constraints)

    def _budget_preview(self, *payloads: dict[str, Any]) -> dict[str, Any]:
        budget = RuntimeBudget(
            max_list_items=self.budget.max_list_items,
            max_dict_items=self.budget.max_dict_items,
            max_string_chars=self.budget.max_string_chars,
        )
        for payload in payloads:
            self._budget_value(payload, budget)
        return budget.to_dict()

    def _trace_payload(self, trace: list[RuntimeStep]) -> list[dict[str, Any]]:
        budget = RuntimeBudget(
            max_list_items=self.budget.max_list_items,
            max_dict_items=self.budget.max_dict_items,
            max_string_chars=self.budget.max_string_chars,
        )
        return [
            {"name": step.name, "status": step.status, "summary": self._budget_value(step.summary, budget)}
            for step in trace
        ]

    def _budget_value(self, value: Any, budget: RuntimeBudget) -> Any:
        return budget_value(value, budget)

    def _stop_check(self, turn: AgentTurn) -> dict[str, Any]:
        original_constraints = turn.feedback_constraints.to_dict()
        constraints = turn.feedback_constraints
        disliked_ids = {str(item_id) for item_id in constraints.disliked_item_ids}
        disliked_categories = {str(category).lower() for category in constraints.disliked_categories}
        original_items = list(turn.recommendation.final_items)
        valid_items: list[dict[str, Any]] = []
        removed_items: list[dict[str, Any]] = []
        for item in original_items:
            item_id = str(item.get("parent_asin") or item.get("item_id") or "")
            category = str(item.get("category") or item.get("main_category") or "").lower()
            reasons: list[str] = []
            if item_id and item_id in disliked_ids:
                reasons.append("disliked_item_id")
            if category and category in disliked_categories:
                reasons.append("disliked_category")
            if reasons:
                removed_items.append({"parent_asin": item_id, "category": category, "reasons": reasons})
                continue
            valid_items.append(item)

        if removed_items:
            removed_ids = {item["parent_asin"] for item in removed_items if item.get("parent_asin")}
            turn.recommendation.final_items = valid_items
            turn.ranking = [
                item for item in turn.ranking
                if str(item.get("parent_asin") or item.get("item_id") or "") not in removed_ids
            ]
            self._append_unique(turn.recommendation.risk_flags, "runtime_stop_check_repaired_constraints")
            turn.diagnostics["runtime_stop_check_removed_items"] = removed_items
            turn.diagnostics["excluded_items"] = sorted(set(turn.diagnostics.get("excluded_items", [])) | removed_ids)
            if not valid_items:
                self._append_unique(turn.recommendation.risk_flags, "empty_recommendation_list")
                self._append_unique(turn.recommendation.limitations, "No final items remained after explicit feedback constraints were applied.")
                turn.fallback_used = True
                turn.assistant_response = "I removed items that conflicted with your explicit feedback, so there are no safe recommendations in this turn."
                turn.recommendation.agent_explanation = turn.assistant_response

        turn.reward_evidence = build_reward_evidence(turn, set())
        turn.reward = compute_turn_reward(turn)
        constraints_unchanged = original_constraints == turn.feedback_constraints.to_dict()
        risk_flags = list(turn.recommendation.risk_flags)
        if not constraints_unchanged:
            risk_flags.append("runtime_stop_check_constraint_mutation_detected")
        return {
            "checked": True,
            "passed": not removed_items and constraints_unchanged,
            "repaired": bool(removed_items),
            "violations": removed_items,
            "removed_count": len(removed_items),
            "removed_items": removed_items,
            "removed_item_ids": sorted(item["parent_asin"] for item in removed_items if item.get("parent_asin")),
            "final_item_count": len(turn.recommendation.final_items),
            "constraints_unchanged": constraints_unchanged,
            "risk_flags": risk_flags,
            "reward_feedback_constraints_satisfied": dict(turn.reward_evidence.feedback_constraints_satisfied),
        }

    def _session_trace_summary(self, turn: AgentTurn, trace_payload: list[dict[str, Any]], stop_check_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "turn_index": turn.turn_index,
            "steps": [step.get("name") for step in trace_payload],
            "final_item_count": len(turn.recommendation.final_items),
            "fallback_used": bool(turn.fallback_used),
            "stop_check_passed": bool(stop_check_result.get("passed")),
            "repaired": bool(stop_check_result.get("repaired")),
        }

    def _constraints_summary(self, constraints: FeedbackConstraints) -> dict[str, Any]:
        return constraints_summary(constraints, self.context_budget)

    def _item_ids(self, items: list[dict[str, Any]]) -> list[str]:
        return [str(item.get("parent_asin") or item.get("item_id")) for item in items if item.get("parent_asin") or item.get("item_id")]

    def _append_unique(self, values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)
