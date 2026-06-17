from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rs_core.rsagent.explanation import build_recommendation_explanation, latest_recommendation_turn, requested_item_id
from rs_core.rsagent.policy import merge_feedback, parse_feedback
from rs_core.rsagent.schema import (
    ACTION_ASK_CLARIFYING_QUESTION,
    ACTION_EXPLAIN_RECOMMENDATION,
    ACTION_RECOMMEND_ITEMS,
    ACTION_REVISE_RECOMMENDATION,
    INTENT_ASK_EXPLANATION,
    INTENT_CLARIFICATION_ANSWER,
    INTENT_PREFERENCE_FEEDBACK,
    INTENT_RECOMMEND_REQUEST,
    INTENT_UNSUPPORTED,
    AgentSession,
    FeedbackConstraints,
)


@dataclass
class DialoguePlan:
    intent: str
    action: str
    assistant_response: str
    constraints_update: FeedbackConstraints = field(default_factory=FeedbackConstraints)
    should_recommend: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def plan_dialogue_turn(user_input: str, session: AgentSession, explanation_item_id: str | None = None) -> DialoguePlan:
    text = user_input.strip()
    if not text:
        return DialoguePlan(
            intent=INTENT_RECOMMEND_REQUEST,
            action=ACTION_RECOMMEND_ITEMS,
            assistant_response="Here are the current recommendations from the hybrid recommendation pipeline.",
            should_recommend=True,
            tool_calls=_recommendation_tool_calls(INTENT_RECOMMEND_REQUEST, FeedbackConstraints(), text),
        )

    lowered = text.lower()
    if _is_explanation_request(lowered):
        source_turn = latest_recommendation_turn(session)
        return DialoguePlan(
            intent=INTENT_ASK_EXPLANATION,
            action=ACTION_EXPLAIN_RECOMMENDATION,
            assistant_response=build_recommendation_explanation(session, explanation_item_id or requested_item_id(text)),
            diagnostics={"explanation_source_turn": source_turn.turn_index if source_turn else None},
            tool_calls=[
                {"name": "get_user_context", "phase": "pre_recommendation"},
                {"name": "get_item_evidence", "phase": "post_recommendation"},
            ],
        )

    parsed = parse_feedback(text)
    if session.conversation_state.pending_clarification:
        parsed = _clarification_constraints(text, parsed)
        return DialoguePlan(
            intent=INTENT_CLARIFICATION_ANSWER,
            action=ACTION_RECOMMEND_ITEMS,
            assistant_response="Thanks, I updated the recommendation constraints from your clarification.",
            constraints_update=parsed,
            should_recommend=True,
            diagnostics={"answered_clarification": session.conversation_state.pending_clarification},
            tool_calls=_recommendation_tool_calls(INTENT_CLARIFICATION_ANSWER, parsed, text),
        )

    if _has_supported_constraint(parsed):
        return DialoguePlan(
            intent=INTENT_PREFERENCE_FEEDBACK,
            action=ACTION_REVISE_RECOMMENDATION,
            assistant_response="Thanks, I updated the recommendations using your feedback.",
            constraints_update=parsed,
            should_recommend=True,
            tool_calls=_recommendation_tool_calls(INTENT_PREFERENCE_FEEDBACK, parsed, text),
        )

    if _is_vague_recommendation_request(lowered):
        if _has_retrievable_query_terms(lowered):
            return DialoguePlan(
                intent=INTENT_RECOMMEND_REQUEST,
                action=ACTION_RECOMMEND_ITEMS,
                assistant_response="I will use your request and recent context to build recommendations.",
                constraints_update=parsed,
                should_recommend=True,
                diagnostics={"retrieval_query_source": "natural_language_request"},
                tool_calls=_recommendation_tool_calls(INTENT_RECOMMEND_REQUEST, parsed, text),
            )
        question = "Do you care more about commute use, audio quality, budget, wireless features, or avoiding a specific category?"
        return DialoguePlan(
            intent=INTENT_RECOMMEND_REQUEST,
            action=ACTION_ASK_CLARIFYING_QUESTION,
            assistant_response=question,
            constraints_update=parsed,
            diagnostics={"clarification_question": question},
        )

    return DialoguePlan(
        intent=INTENT_UNSUPPORTED,
        action=ACTION_ASK_CLARIFYING_QUESTION,
        assistant_response="I could not safely turn that into recommendation constraints yet. Could you name a category, keyword, or item to avoid?",
        constraints_update=parsed,
        diagnostics={"unsupported_user_input": text},
    )


def _recommendation_tool_calls(intent: str, constraints: FeedbackConstraints, query: str = "") -> list[dict[str, Any]]:
    retrieve_arguments: dict[str, Any] = {
        "semantic_mode": "hybrid_query_history" if query else "history_profile",
        "use_history_profile": True,
        "use_behavioral_recall": True,
    }
    if query:
        retrieve_arguments["query"] = query
    tool_calls = [{"name": "get_user_context", "phase": "pre_recommendation"}]
    if query:
        tool_calls.append({
            "name": "query_rag",
            "phase": "pre_recommendation",
            "arguments": {"query": query, "purpose": "query_planning"},
        })
    tool_calls.extend([
        {"name": "retrieve_candidates", "phase": "pre_recommendation", "arguments": retrieve_arguments},
        {"name": "rank_candidates", "phase": "post_recommendation"},
        {"name": "get_item_evidence", "phase": "post_recommendation"},
        {"name": "build_recommendation_slate", "phase": "post_recommendation"},
    ])
    return tool_calls


def apply_dialogue_plan(session: AgentSession, plan: DialoguePlan) -> FeedbackConstraints:
    if _has_any_constraint_or_unsupported(plan.constraints_update):
        session.active_constraints = merge_feedback(session.active_constraints, plan.constraints_update)
    session.conversation_state.last_intent = plan.intent
    session.conversation_state.last_agent_action = plan.action
    if plan.action == ACTION_ASK_CLARIFYING_QUESTION:
        session.conversation_state.pending_clarification = plan.assistant_response
        session.conversation_state.clarification_history.append(plan.assistant_response)
    elif plan.intent == INTENT_CLARIFICATION_ANSWER:
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


def _has_retrievable_query_terms(lowered: str) -> bool:
    cleaned = re.sub(r"\b(i|want|need|am|looking|for|recommend|suggest|buy|me|some|something|anything|items?|products?)\b", " ", lowered)
    cleaned = re.sub(r"想要|推荐|买|东西|商品|一些|一个|一点", " ", cleaned)
    generic_terms = {"good", "nice", "best", "great", "cool", "premium", "quality", "better"}
    tokens_left = [token for token in re.findall(r"[a-z0-9_]+", cleaned) if token not in generic_terms]
    if any(len(token) >= 3 or token in {"tv", "pc", "vr"} for token in tokens_left):
        return True
    return bool(re.search(r"[一-鿿]{2,}", cleaned))


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
