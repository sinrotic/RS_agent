from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rs_core.rsagent.policy import merge_feedback, parse_feedback
from rs_core.rsagent.schema import AgentSession, FeedbackConstraints


@dataclass
class DialoguePlan:
    intent: str
    action: str
    assistant_response: str
    constraints_update: FeedbackConstraints = field(default_factory=FeedbackConstraints)
    should_recommend: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)


def plan_dialogue_turn(user_input: str, session: AgentSession) -> DialoguePlan:
    text = user_input.strip()
    if not text:
        return DialoguePlan(
            intent="recommend_request",
            action="recommend_items",
            assistant_response="Here are the current recommendations from the hybrid recommendation pipeline.",
            should_recommend=True,
        )

    lowered = text.lower()
    if _is_explanation_request(lowered):
        return DialoguePlan(
            intent="ask_explanation",
            action="explain_recommendation",
            assistant_response=_prior_recommendation_explanation(session),
            diagnostics={"explanation_source_turn": session.turns[-1].turn_index if session.turns else None},
        )

    parsed = parse_feedback(text)
    if session.conversation_state.pending_clarification:
        parsed = _clarification_constraints(text, parsed)
        return DialoguePlan(
            intent="clarification_answer",
            action="recommend_items",
            assistant_response="Thanks, I updated the recommendation constraints from your clarification.",
            constraints_update=parsed,
            should_recommend=True,
            diagnostics={"answered_clarification": session.conversation_state.pending_clarification},
        )

    if _has_supported_constraint(parsed):
        return DialoguePlan(
            intent="preference_feedback",
            action="revise_recommendation",
            assistant_response="Thanks, I updated the recommendations using your feedback.",
            constraints_update=parsed,
            should_recommend=True,
        )

    if _is_vague_recommendation_request(lowered):
        question = "Do you care more about commute use, audio quality, budget, wireless features, or avoiding a specific category?"
        return DialoguePlan(
            intent="recommend_request",
            action="ask_clarifying_question",
            assistant_response=question,
            constraints_update=parsed,
            diagnostics={"clarification_question": question},
        )

    return DialoguePlan(
        intent="unsupported",
        action="ask_clarifying_question",
        assistant_response="I could not safely turn that into recommendation constraints yet. Could you name a category, source, keyword, or item to avoid?",
        constraints_update=parsed,
        diagnostics={"unsupported_user_input": text},
    )


def apply_dialogue_plan(session: AgentSession, plan: DialoguePlan) -> FeedbackConstraints:
    if _has_any_constraint_or_unsupported(plan.constraints_update):
        session.active_constraints = merge_feedback(session.active_constraints, plan.constraints_update)
    session.conversation_state.last_intent = plan.intent
    session.conversation_state.last_agent_action = plan.action
    if plan.action == "ask_clarifying_question":
        session.conversation_state.pending_clarification = plan.assistant_response
        session.conversation_state.clarification_history.append(plan.assistant_response)
    elif plan.intent == "clarification_answer":
        session.conversation_state.pending_clarification = ""
    return session.active_constraints


def _clarification_constraints(text: str, parsed: FeedbackConstraints) -> FeedbackConstraints:
    inferred = parse_feedback(f"prefer {_prefix_before_intent(text)}")
    merged = merge_feedback(inferred, parsed)
    if _has_supported_constraint(merged):
        return merged
    inferred = parse_feedback(f"prefer {text}")
    inferred.unsupported_free_text = list(parsed.unsupported_free_text)
    return inferred


def _prefix_before_intent(text: str) -> str:
    match = re.search(r"\b(dislike|avoid|exclude|prefer|like)\b|不喜欢|不要|排除|喜欢|偏好", text, re.IGNORECASE)
    prefix = text[: match.start()] if match else text
    return prefix.strip(" ,.;:，。；：")


def _is_explanation_request(lowered: str) -> bool:
    return bool(re.search(r"\bwhy\b|\bexplain\b|为什么|解释", lowered))


def _is_vague_recommendation_request(lowered: str) -> bool:
    return bool(re.search(r"\b(want|need|looking for|recommend|suggest|buy)\b|想要|推荐", lowered))


def _prior_recommendation_explanation(session: AgentSession) -> str:
    if not session.turns:
        return "There is no previous recommendation to explain yet."
    previous = session.turns[-1]
    items = [str(item.get("parent_asin")) for item in previous.ranking[:3] if item.get("parent_asin")]
    sources = sorted({source for item in previous.ranking[:3] for source in item.get("sources", [])})
    item_text = ", ".join(items) if items else "the previous recommendation"
    source_text = ", ".join(sources) if sources else "the available recall sources"
    return f"I recommended {item_text} because they ranked highest after applying the current hybrid recall, feedback constraints, and sources: {source_text}."


def _has_supported_constraint(constraints: FeedbackConstraints) -> bool:
    return bool(
        constraints.disliked_item_ids
        or constraints.disliked_categories
        or constraints.preferred_categories
        or constraints.preferred_sources
        or constraints.preferred_keywords
        or constraints.disliked_keywords
        or constraints.filter_prior_turn_items
    )


def _has_any_constraint_or_unsupported(constraints: FeedbackConstraints) -> bool:
    return _has_supported_constraint(constraints) or bool(constraints.unsupported_free_text)
