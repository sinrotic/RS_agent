from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol

from rs_core.rsagent.reward import build_reward_evidence, compute_turn_reward
from rs_core.rsagent.schema import AgentSession, AgentTurn, FeedbackConstraints


RUNTIME_TRACE_STEP_ORDER = [
    "observe_input",
    "memory_prefetch",
    "context_compact",
    "tool_result_budget",
    "plan_dialogue",
    "apply_constraints",
    "recommend_or_dialogue",
    "build_turn",
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


class AgentRuntimeHost(Protocol):
    def plan_dialogue(self, user_input: str, session: AgentSession, explanation_item_id: str | None) -> DialoguePlanLike: ...

    def apply_dialogue_plan(self, session: AgentSession, plan: DialoguePlanLike) -> FeedbackConstraints: ...

    def build_recommendation_turn(
        self,
        session: AgentSession,
        user_input: str,
        assistant_response: str,
        merge_user_input: bool,
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
    def __init__(self, budget: RuntimeBudget | None = None) -> None:
        self.budget = budget or RuntimeBudget()

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

        branch = "recommendation" if plan.should_recommend else "dialogue_only"
        trace.append(self._step("recommend_or_dialogue", {"branch": branch}))

        if plan.should_recommend:
            turn = host.build_recommendation_turn(session, normalized_input, plan.assistant_response, merge_user_input=False)
        else:
            turn = host.build_dialogue_turn(session, normalized_input, plan.assistant_response)
        trace.append(self._step("build_turn", {
            "turn_index": turn.turn_index,
            "final_item_count": len(turn.recommendation.final_items),
            "candidate_count": len(turn.candidates),
            "ranking_count": len(turn.ranking),
            "fallback_used": bool(turn.fallback_used),
        }))

        stop_check_result = self._stop_check(turn)
        trace.append(self._step("stop_check", stop_check_result))

        turn.diagnostics.update({
            "conversation_intent": plan.intent,
            "agent_action": plan.action,
            "assistant_response": plan.assistant_response,
            **plan.diagnostics,
            "memory_snapshot": self._budget_value(memory_snapshot, RuntimeBudget()),
            "tool_result_budget": budget_preview,
            "stop_check_result": stop_check_result,
        })
        trace.append(self._step("attach_diagnostics", {
            "diagnostic_keys": sorted(turn.diagnostics),
            "runtime_diagnostic_keys": ["memory_snapshot", "tool_result_budget", "stop_check_result", "agent_runtime_trace"],
        }))

        session.session_summary = self._compact_session(session)
        trace.append(self._step("update_session_summary", session.session_summary))

        trace_payload = self._trace_payload(trace)
        turn.diagnostics["agent_runtime_trace"] = trace_payload
        session.runtime_trace.append(self._session_trace_summary(turn, trace_payload, stop_check_result))
        session.runtime_trace[:] = session.runtime_trace[-20:]
        return turn

    def _step(self, name: str, summary: dict[str, Any]) -> RuntimeStep:
        return RuntimeStep(name=name, summary=self._budget_value(summary, RuntimeBudget()))

    def _memory_prefetch(self, session: AgentSession) -> dict[str, Any]:
        recent_turns = session.turns[-3:]
        return {
            "session_summary": deepcopy(session.session_summary),
            "active_constraints": self._constraints_summary(session.active_constraints),
            "conversation_state": session.conversation_state.to_dict(),
            "prior_turn_count": len(session.turns),
            "recent_turns": [
                {
                    "turn_index": turn.turn_index,
                    "user_input": turn.user_input,
                    "assistant_response": turn.assistant_response,
                    "intent": turn.diagnostics.get("conversation_intent"),
                    "agent_action": turn.diagnostics.get("agent_action"),
                    "item_ids": self._item_ids(turn.recommendation.final_items),
                    "fallback_used": bool(turn.fallback_used),
                }
                for turn in recent_turns
            ],
        }

    def _compact_session(self, session: AgentSession) -> dict[str, Any]:
        constraints = session.active_constraints
        shown_item_ids: list[str] = []
        for turn in session.turns:
            shown_item_ids.extend(self._item_ids(turn.recommendation.final_items))
        return {
            "current_goal": session.conversation_state.last_intent or "recommend_request",
            "latest_intent": session.conversation_state.last_intent,
            "pending_clarification": session.conversation_state.pending_clarification,
            "clarification_history": list(session.conversation_state.clarification_history[-5:]),
            "shown_item_ids": list(dict.fromkeys(shown_item_ids))[-20:],
            "liked_item_ids": sorted(constraints.liked_item_ids),
            "disliked_item_ids": sorted(constraints.disliked_item_ids),
            "disliked_categories": sorted(constraints.disliked_categories),
            "preferred_categories": dict(sorted(constraints.preferred_categories.items())),
            "preferred_sources": dict(sorted(constraints.preferred_sources.items())),
            "preferred_keywords": dict(sorted(constraints.preferred_keywords.items())),
            "disliked_keywords": dict(sorted(constraints.disliked_keywords.items())),
            "max_price": constraints.max_price,
            "filter_prior_turn_items": constraints.filter_prior_turn_items,
            "constraints_summary": self._constraints_summary(constraints),
            "recent_action": session.conversation_state.last_agent_action,
            "turn_count": len(session.turns),
        }

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
        if isinstance(value, dict):
            items = list(value.items())
            retained = items[: budget.max_dict_items]
            budget.retained += len(retained)
            if len(items) > len(retained):
                budget.truncated += len(items) - len(retained)
            result = {str(key): self._budget_value(item, budget) for key, item in retained}
            if len(items) > len(retained):
                result["_truncated_keys"] = len(items) - len(retained)
            return result
        if isinstance(value, (list, tuple, set)):
            values = sorted(value) if isinstance(value, set) else list(value)
            retained_values = values[: budget.max_list_items]
            budget.retained += len(retained_values)
            if len(values) > len(retained_values):
                budget.truncated += len(values) - len(retained_values)
            result = [self._budget_value(item, budget) for item in retained_values]
            if len(values) > len(retained_values):
                result.append({"_truncated_items": len(values) - len(retained_values)})
            return result
        if isinstance(value, str) and len(value) > budget.max_string_chars:
            budget.retained += 1
            budget.truncated += 1
            return value[: budget.max_string_chars] + "..."
        budget.retained += 1
        return value

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
        return {
            "liked_item_ids": sorted(constraints.liked_item_ids),
            "disliked_item_ids": sorted(constraints.disliked_item_ids),
            "disliked_categories": sorted(constraints.disliked_categories),
            "preferred_categories": dict(sorted(constraints.preferred_categories.items())),
            "preferred_sources": dict(sorted(constraints.preferred_sources.items())),
            "preferred_keywords": dict(sorted(constraints.preferred_keywords.items())),
            "disliked_keywords": dict(sorted(constraints.disliked_keywords.items())),
            "max_price": constraints.max_price,
            "filter_prior_turn_items": constraints.filter_prior_turn_items,
            "unsupported_free_text_count": len(constraints.unsupported_free_text),
        }

    def _item_ids(self, items: list[dict[str, Any]]) -> list[str]:
        return [str(item.get("parent_asin") or item.get("item_id")) for item in items if item.get("parent_asin") or item.get("item_id")]

    def _append_unique(self, values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)
