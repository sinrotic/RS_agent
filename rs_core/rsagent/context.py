from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rs_core.rsagent.schema import (
    INTENT_RECOMMEND_REQUEST,
    AgentSession,
    AgentTurn,
    ArchivedTurnSummary,
    FeedbackConstraints,
    UserPreferenceProfile,
)


@dataclass
class ContextBudget:
    recent_turns: int = 3
    archived_turns: int = 30
    shown_item_ids: int = 50
    liked_item_ids: int = 30
    disliked_item_ids: int = 30
    preference_terms: int = 20
    max_string_chars: int = 240
    tool_max_list_items: int = 5
    tool_max_dict_items: int = 12
    tool_max_string_chars: int = 240
    rag_max_evidence_per_item: int = 3
    rag_max_evidence_total: int = 12
    rag_max_text_chars: int = 180

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BudgetStats:
    max_list_items: int = 5
    max_dict_items: int = 12
    max_string_chars: int = 240
    retained: int = 0
    truncated: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextBundle:
    session_id: str
    user_id: str
    current_goal: str
    latest_intent: str | None
    latest_action: str | None
    pending_clarification: str | None
    conversation_state: dict[str, Any]
    active_constraints: dict[str, Any]
    user_profile: dict[str, Any]
    shown_item_ids: list[str]
    recent_turns: list[dict[str, Any]]
    archived_turn_summaries: list[dict[str, Any]]
    turn_count: int
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def memory_snapshot(self, session_summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_summary": dict(session_summary),
            "active_constraints": self.active_constraints,
            "conversation_state": self.conversation_state,
            "prior_turn_count": self.turn_count,
            "recent_turns": self.recent_turns,
            "user_profile": self.user_profile,
            "archived_turn_summaries": self.archived_turn_summaries,
            "context_budget": self.diagnostics.get("budget", {}),
        }

    def session_summary(self, constraints: FeedbackConstraints) -> dict[str, Any]:
        return {
            "current_goal": self.current_goal,
            "latest_intent": self.latest_intent or "",
            "pending_clarification": self.pending_clarification or "",
            "clarification_history": list(self.conversation_state.get("clarification_history", []))[-5:],
            "shown_item_ids": self.shown_item_ids[-20:],
            "liked_item_ids": _limit_list(sorted(constraints.liked_item_ids), 30),
            "disliked_item_ids": _limit_list(sorted(constraints.disliked_item_ids), 30),
            "disliked_categories": _limit_list(sorted(constraints.disliked_categories), 20),
            "preferred_categories": _limit_mapping(constraints.preferred_categories, 20),
            "preferred_sources": _limit_mapping(constraints.preferred_sources, 20),
            "preferred_keywords": _limit_mapping(constraints.preferred_keywords, 20),
            "disliked_keywords": _limit_mapping(constraints.disliked_keywords, 20),
            "max_price": constraints.max_price,
            "filter_prior_turn_items": constraints.filter_prior_turn_items,
            "constraints_summary": constraints_summary(constraints),
            "recent_action": self.latest_action or "",
            "turn_count": self.turn_count,
            "user_profile": self.user_profile,
            "archived_turn_count": _archived_turn_count(self.turn_count, self.diagnostics.get("budget", {})),
            "context_budget": self.diagnostics.get("budget", {}),
        }


def build_context_bundle(session: AgentSession, budget: ContextBudget | None = None) -> ContextBundle:
    active_budget = budget or ContextBudget()
    ensure_session_context_state(session, active_budget)
    shown_item_ids = _shown_item_ids(session, active_budget.shown_item_ids)
    recent_turns = [
        summarize_turn(turn, active_budget).to_dict()
        for turn in session.turns[-max(0, active_budget.recent_turns):]
    ] if active_budget.recent_turns else []
    recent_turn_indices = {turn.get("turn_index") for turn in recent_turns}
    archived = [
        summary.to_dict()
        for summary in session.archived_turn_summaries[-active_budget.archived_turns:]
        if summary.turn_index not in recent_turn_indices
    ]
    state = session.conversation_state
    return ContextBundle(
        session_id=session.session_id,
        user_id=session.user_id,
        current_goal=state.last_intent or INTENT_RECOMMEND_REQUEST,
        latest_intent=state.last_intent or None,
        latest_action=state.last_agent_action or None,
        pending_clarification=state.pending_clarification or None,
        conversation_state=state.to_dict(),
        active_constraints=constraints_summary(session.active_constraints, active_budget),
        user_profile=session.user_profile.to_dict(),
        shown_item_ids=shown_item_ids,
        recent_turns=recent_turns,
        archived_turn_summaries=archived,
        turn_count=len(session.turns),
        diagnostics={
            "compact": True,
            "budget": active_budget.to_dict(),
            "archived_turn_count": len(session.archived_turn_summaries),
        },
    )


def ensure_session_context_state(session: AgentSession, budget: ContextBudget | None = None) -> None:
    update_user_profile(session, budget)
    refresh_archived_turn_summaries(session, budget)


def update_user_profile(session: AgentSession, budget: ContextBudget | None = None) -> UserPreferenceProfile:
    active_budget = budget or ContextBudget()
    constraints = session.active_constraints
    session.user_profile = UserPreferenceProfile(
        liked_item_ids=_limit_list(sorted(constraints.liked_item_ids), active_budget.liked_item_ids),
        disliked_item_ids=_limit_list(sorted(constraints.disliked_item_ids), active_budget.disliked_item_ids),
        disliked_categories=_limit_list(sorted(constraints.disliked_categories), active_budget.preference_terms),
        preferred_categories=_limit_mapping(constraints.preferred_categories, active_budget.preference_terms),
        preferred_sources=_limit_mapping(constraints.preferred_sources, active_budget.preference_terms),
        preferred_keywords=_limit_mapping(constraints.preferred_keywords, active_budget.preference_terms),
        disliked_keywords=_limit_mapping(constraints.disliked_keywords, active_budget.preference_terms),
        max_price=constraints.max_price,
        use_cases=_limit_mapping(constraints.use_cases, active_budget.preference_terms),
        updated_turn_index=len(session.turns),
    )
    return session.user_profile


def refresh_archived_turn_summaries(session: AgentSession, budget: ContextBudget | None = None) -> list[ArchivedTurnSummary]:
    active_budget = budget or ContextBudget()
    if active_budget.archived_turns <= 0:
        session.archived_turn_summaries = []
        return session.archived_turn_summaries
    summaries_by_turn = {summary.turn_index: summary for summary in session.archived_turn_summaries}
    for turn in session.turns[-active_budget.archived_turns:]:
        summaries_by_turn.setdefault(turn.turn_index, summarize_turn(turn, active_budget))
    retained_turn_indices = {turn.turn_index for turn in session.turns[-active_budget.archived_turns:]}
    ordered = [
        summaries_by_turn[index]
        for index in sorted(summaries_by_turn)
        if index in retained_turn_indices
    ]
    session.archived_turn_summaries = ordered[-active_budget.archived_turns:]
    return session.archived_turn_summaries


def summarize_turn(turn: AgentTurn, budget: ContextBudget | None = None) -> ArchivedTurnSummary:
    active_budget = budget or ContextBudget()
    assistant_response = turn.assistant_response or turn.recommendation.agent_explanation
    return ArchivedTurnSummary(
        turn_index=turn.turn_index,
        user_input=_truncate_text(turn.user_input, active_budget.max_string_chars),
        assistant_response=_truncate_text(assistant_response, active_budget.max_string_chars),
        intent=turn.diagnostics.get("conversation_intent"),
        agent_action=turn.diagnostics.get("agent_action"),
        item_ids=_item_ids(turn.recommendation.final_items),
        fallback_used=bool(turn.fallback_used),
    )


def _archived_turn_count(turn_count: int, budget: dict[str, Any]) -> int:
    recent_turns = int(budget.get("recent_turns", ContextBudget.recent_turns)) if isinstance(budget, dict) else ContextBudget.recent_turns
    archived_turns = int(budget.get("archived_turns", ContextBudget.archived_turns)) if isinstance(budget, dict) else ContextBudget.archived_turns
    return max(0, min(int(turn_count), archived_turns) - max(0, min(int(turn_count), recent_turns)))


def constraints_summary(constraints: FeedbackConstraints, budget: ContextBudget | None = None) -> dict[str, Any]:
    active_budget = budget or ContextBudget()
    return {
        "liked_item_ids": _limit_list(sorted(constraints.liked_item_ids), active_budget.liked_item_ids),
        "disliked_item_ids": _limit_list(sorted(constraints.disliked_item_ids), active_budget.disliked_item_ids),
        "disliked_categories": _limit_list(sorted(constraints.disliked_categories), active_budget.preference_terms),
        "preferred_categories": _limit_mapping(constraints.preferred_categories, active_budget.preference_terms),
        "preferred_sources": _limit_mapping(constraints.preferred_sources, active_budget.preference_terms),
        "preferred_keywords": _limit_mapping(constraints.preferred_keywords, active_budget.preference_terms),
        "disliked_keywords": _limit_mapping(constraints.disliked_keywords, active_budget.preference_terms),
        "max_price": constraints.max_price,
        "filter_prior_turn_items": constraints.filter_prior_turn_items,
        "unsupported_free_text_count": len(constraints.unsupported_free_text),
    }


def budget_value(value: Any, budget: Any) -> Any:
    max_dict_items = int(getattr(budget, "max_dict_items", getattr(budget, "tool_max_dict_items", 12)))
    max_list_items = int(getattr(budget, "max_list_items", getattr(budget, "tool_max_list_items", 5)))
    max_string_chars = int(getattr(budget, "max_string_chars", getattr(budget, "tool_max_string_chars", 240)))
    if isinstance(value, dict):
        items = list(value.items())
        retained = items[:max_dict_items]
        _add_budget_count(budget, "retained", len(retained))
        if len(items) > len(retained):
            _add_budget_count(budget, "truncated", len(items) - len(retained))
        result = {str(key): budget_value(item, budget) for key, item in retained}
        if len(items) > len(retained):
            result["_truncated_keys"] = len(items) - len(retained)
        return result
    if isinstance(value, (list, tuple, set)):
        values = sorted(value) if isinstance(value, set) else list(value)
        retained_values = values[:max_list_items]
        _add_budget_count(budget, "retained", len(retained_values))
        if len(values) > len(retained_values):
            _add_budget_count(budget, "truncated", len(values) - len(retained_values))
        result = [budget_value(item, budget) for item in retained_values]
        if len(values) > len(retained_values):
            result.append({"_truncated_items": len(values) - len(retained_values)})
        return result
    if isinstance(value, str) and len(value) > max_string_chars:
        _add_budget_count(budget, "retained", 1)
        _add_budget_count(budget, "truncated", 1)
        return _truncate_text(value, max_string_chars)
    _add_budget_count(budget, "retained", 1)
    return value


def _shown_item_ids(session: AgentSession, limit: int) -> list[str]:
    item_ids: list[str] = []
    for summary in session.archived_turn_summaries:
        item_ids.extend(summary.item_ids)
    for turn in session.turns:
        item_ids.extend(_item_ids(turn.recommendation.final_items))
    return list(dict.fromkeys(item_ids))[-limit:]


def _item_ids(items: list[dict[str, Any]]) -> list[str]:
    return [
        str(item.get("parent_asin") or item.get("item_id") or item.get("dst_item"))
        for item in items
        if item.get("parent_asin") or item.get("item_id") or item.get("dst_item")
    ]


def _truncate_text(value: Any, max_chars: int) -> str:
    text = "" if value in (None, "") else str(value).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def _limit_list(values: list[str], limit: int) -> list[str]:
    return list(values)[:max(0, limit)]


def _limit_mapping(values: dict[str, float], limit: int) -> dict[str, float]:
    return dict(sorted(values.items())[:max(0, limit)])


def _add_budget_count(budget: Any, field_name: str, value: int) -> None:
    if not hasattr(budget, field_name):
        return
    setattr(budget, field_name, int(getattr(budget, field_name)) + value)
