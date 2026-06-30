from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rs_core.agent.explanation import build_recommendation_explanation, latest_recommendation_turn, requested_item_id
from rs_core.agent.feedback import merge_feedback, parse_feedback
from rs_core.agent.contracts.schema import (
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
    assistant_response: str = ""
    constraints_update: FeedbackConstraints = field(default_factory=FeedbackConstraints)
    should_recommend: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    response_directive: str = ""


def plan_dialogue_turn(user_input: str, session: AgentSession, explanation_item_id: str | None = None) -> DialoguePlan:
    text = user_input.strip()
    if not text:
        return DialoguePlan(
            intent=INTENT_RECOMMEND_REQUEST,
            action=ACTION_RECOMMEND_ITEMS,
            should_recommend=True,
            diagnostics={"response_directive": _response_directive(INTENT_RECOMMEND_REQUEST, ACTION_RECOMMEND_ITEMS)},
            tool_calls=_recommendation_tool_calls(INTENT_RECOMMEND_REQUEST, FeedbackConstraints(), text),
            response_directive=_response_directive(INTENT_RECOMMEND_REQUEST, ACTION_RECOMMEND_ITEMS),
        )

    lowered = text.lower()
    parsed = parse_feedback(text)
    is_explanation_request = _is_explanation_request(lowered)
    clarification_update = _clarification_constraints(text, parsed) if session.conversation_state.pending_clarification else parsed
    should_treat_as_clarification = not is_explanation_request or _has_clarification_answer_signal(lowered, parsed)
    if session.conversation_state.pending_clarification and explanation_item_id is None and should_treat_as_clarification:
        parsed = clarification_update
        directive = _response_directive(INTENT_CLARIFICATION_ANSWER, ACTION_RECOMMEND_ITEMS)
        return DialoguePlan(
            intent=INTENT_CLARIFICATION_ANSWER,
            action=ACTION_RECOMMEND_ITEMS,
            constraints_update=parsed,
            should_recommend=True,
            diagnostics={
                "answered_clarification": session.conversation_state.pending_clarification,
                "clarification_route": "pending_clarification_priority",
                "response_directive": directive,
            },
            tool_calls=_recommendation_tool_calls(INTENT_CLARIFICATION_ANSWER, parsed, text),
            response_directive=directive,
        )

    if is_explanation_request:
        source_turn = latest_recommendation_turn(session)
        return DialoguePlan(
            intent=INTENT_ASK_EXPLANATION,
            action=ACTION_EXPLAIN_RECOMMENDATION,
            assistant_response=build_recommendation_explanation(session, explanation_item_id or requested_item_id(text)),
            diagnostics={
                "explanation_source_turn": source_turn.turn_index if source_turn else None,
                "response_directive": _response_directive(INTENT_ASK_EXPLANATION, ACTION_EXPLAIN_RECOMMENDATION),
            },
            response_directive=_response_directive(INTENT_ASK_EXPLANATION, ACTION_EXPLAIN_RECOMMENDATION),
            tool_calls=[
                {"name": "get_user_context", "phase": "pre_recommendation"},
            ],
        )

    if _has_supported_constraint(parsed):
        directive = _response_directive(INTENT_PREFERENCE_FEEDBACK, ACTION_REVISE_RECOMMENDATION)
        return DialoguePlan(
            intent=INTENT_PREFERENCE_FEEDBACK,
            action=ACTION_REVISE_RECOMMENDATION,
            constraints_update=parsed,
            should_recommend=True,
            diagnostics={"response_directive": directive},
            tool_calls=_recommendation_tool_calls(INTENT_PREFERENCE_FEEDBACK, parsed, text),
            response_directive=directive,
        )

    if _is_vague_recommendation_request(lowered):
        if _is_broad_browse_request(lowered):
            directive = _response_directive(INTENT_RECOMMEND_REQUEST, ACTION_RECOMMEND_ITEMS)
            return DialoguePlan(
                intent=INTENT_RECOMMEND_REQUEST,
                action=ACTION_RECOMMEND_ITEMS,
                constraints_update=parsed,
                should_recommend=True,
                diagnostics={"retrieval_query_source": "broad_browse_request", "response_directive": directive},
                tool_calls=_recommendation_tool_calls(INTENT_RECOMMEND_REQUEST, parsed, text),
                response_directive=directive,
            )
        if _has_retrievable_query_terms(lowered):
            directive = _response_directive(INTENT_RECOMMEND_REQUEST, ACTION_RECOMMEND_ITEMS)
            return DialoguePlan(
                intent=INTENT_RECOMMEND_REQUEST,
                action=ACTION_RECOMMEND_ITEMS,
                constraints_update=parsed,
                should_recommend=True,
                diagnostics={"retrieval_query_source": "natural_language_request", "response_directive": directive},
                tool_calls=_recommendation_tool_calls(INTENT_RECOMMEND_REQUEST, parsed, text),
                response_directive=directive,
            )
        directive = _response_directive(INTENT_RECOMMEND_REQUEST, ACTION_ASK_CLARIFYING_QUESTION)
        return DialoguePlan(
            intent=INTENT_RECOMMEND_REQUEST,
            action=ACTION_ASK_CLARIFYING_QUESTION,
            constraints_update=parsed,
            diagnostics={"clarification_question": directive, "response_directive": directive},
            response_directive=directive,
        )

    directive = _response_directive(INTENT_UNSUPPORTED, ACTION_ASK_CLARIFYING_QUESTION)
    return DialoguePlan(
        intent=INTENT_UNSUPPORTED,
        action=ACTION_ASK_CLARIFYING_QUESTION,
        constraints_update=parsed,
        diagnostics={"unsupported_user_input": text, "response_directive": directive},
        response_directive=directive,
    )


def _response_directive(intent: str, action: str) -> str:
    if action == ACTION_RECOMMEND_ITEMS:
        return "generate a natural shopping-advisor response that acknowledges the current semantic need and lets the product display carry the concrete recommendations"
    if action == ACTION_REVISE_RECOMMENDATION:
        return "generate a natural shopping-advisor response that acknowledges the user's semantic feedback and adapts the next recommendation without exposing internal mechanics"
    if action == ACTION_ASK_CLARIFYING_QUESTION:
        return "generate one concise, context-aware clarification question that helps the customer express the missing shopping preference"
    if action == ACTION_EXPLAIN_RECOMMENDATION:
        return "explain the relevant displayed item using only public item evidence and the current conversation context"
    return f"generate a public-safe shopping-advisor response for intent={intent} action={action}"


def _recommendation_tool_calls(intent: str, constraints: FeedbackConstraints, query: str = "") -> list[dict[str, Any]]:
    retrieval_mode, reference_item_id = _retrieve_business_mode(query)
    query = query.strip()
    has_retrievable_query = bool(query and _has_retrievable_query_terms(query.lower()))
    retrieve_arguments: dict[str, Any] = {
        "retrieval_mode": retrieval_mode,
        "profile_usage": "balanced",
        "expansion_policy": "balanced",
        "target_pool_size": 500,
        "reference_item_id": reference_item_id,
        "profile_policy": {
            "use_current_query": has_retrievable_query,
            "use_recent_history": True,
            "history_weight": "balanced",
        },
    }
    if has_retrievable_query:
        retrieve_arguments["query"] = query
    tool_calls = [{"name": "get_user_context", "phase": "pre_recommendation"}]
    if has_retrievable_query:
        tool_calls.append({
            "name": "call_rag_agent",
            "phase": "pre_recommendation",
            "arguments": {
                "stage": "pre_retrieval_query_support",
                "query": query,
                "reason": "support_recommendation_query_planning",
                "candidate_scope": "current_turn_only",
            },
        })
    tool_calls.extend([
        {"name": "retrieve_candidates", "phase": "pre_recommendation", "arguments": retrieve_arguments},
        {"name": "rank_candidates", "phase": "post_recommendation"},
        {"name": "build_recommendation_slate", "phase": "post_recommendation"},
    ])
    return tool_calls


def _retrieve_business_mode(query: str) -> tuple[str, str | None]:
    text = query.strip()
    lowered = text.lower()
    reference_item_id = requested_item_id(text)
    has_reference_cue = bool(reference_item_id or re.search(r"\b(like this|similar|alternative|more like)\b|像|类似|相似|同款|替代", lowered))
    has_constraint_cue = bool(re.search(r"\b(cheaper|lighter|smaller|larger|budget|wireless|bluetooth|avoid|without|with)\b|更便宜|更轻|更小|不要|避免|带|有", lowered))
    if has_reference_cue and has_constraint_cue:
        return "reference_with_constraints", reference_item_id
    if has_reference_cue:
        return "similar_to_item", reference_item_id
    if _has_retrievable_query_terms(lowered):
        return "specific_need", None
    if text:
        return "personalized_feed", None
    return "broad_browse", None


def apply_dialogue_plan(session: AgentSession, plan: DialoguePlan) -> FeedbackConstraints:
    if _has_any_constraint_or_unsupported(plan.constraints_update):
        session.active_constraints = merge_feedback(session.active_constraints, plan.constraints_update)
    session.conversation_state.last_intent = plan.intent
    session.conversation_state.last_agent_action = plan.action
    if plan.action == ACTION_ASK_CLARIFYING_QUESTION:
        clarification_marker = plan.assistant_response or plan.response_directive
        session.conversation_state.pending_clarification = clarification_marker
        session.conversation_state.clarification_history.append(clarification_marker)
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
    match = re.search(r"\b(dislike|avoid|exclude|prefer|like)\b|不喜欢|不要|排除|喜欢|偏好|偏重|优先|更偏|更想要|给我看|先看|看看|找|展示|来点|换成", text, re.IGNORECASE)
    prefix = text[: match.start()] if match else text
    return prefix.strip(" ,.;:，。；：")


def _is_explanation_request(lowered: str) -> bool:
    return bool(re.search(r"\bwhy\b|\bexplain\b|为什么|解释", lowered))


def _has_clarification_answer_signal(lowered: str, parsed: FeedbackConstraints) -> bool:
    if _has_supported_constraint(parsed):
        return True
    return bool(re.search(r"\bbudget\b|\bcheap\b|\bprice\b|便宜|预算|贵|价格", lowered))


def _is_vague_recommendation_request(lowered: str) -> bool:
    return bool(re.search(r"\b(want|need|looking for|recommend|suggest|buy)\b|想要|推荐|给我看|先看|看看|找|展示|来点|换成", lowered))


def _is_broad_browse_request(lowered: str) -> bool:
    cleaned = _remove_chinese_browse_terms(lowered)
    cleaned = re.sub(r"\s+", "", cleaned)
    return bool(lowered.strip()) and not cleaned


def _has_retrievable_query_terms(lowered: str) -> bool:
    cleaned = re.sub(r"\b(i|want|need|am|looking|for|recommend|suggest|buy|me|some|something|anything|items?|products?)\b", " ", lowered)
    cleaned = re.sub(r"想要|推荐|买|东西|商品|一些|一个|一点", " ", cleaned)
    cleaned = _remove_chinese_browse_terms(cleaned)
    generic_terms = {"good", "nice", "best", "great", "cool", "premium", "quality", "better"}
    tokens_left = [token for token in re.findall(r"[a-z0-9_]+", cleaned) if token not in generic_terms]
    if any(len(token) >= 3 or token in {"tv", "pc", "vr"} for token in tokens_left):
        return True
    return bool(re.search(r"[一-鿿]{2,}", cleaned))


def _remove_chinese_browse_terms(text: str) -> str:
    return re.sub(r"先随便看看|随便看看|随便逛逛|看一下|浏览一下|看看|逛逛|随便|先看|给我看|展示", " ", text)


def _has_supported_constraint(constraints: FeedbackConstraints) -> bool:
    return bool(
        constraints.liked_item_ids
        or constraints.disliked_item_ids
        or constraints.disliked_categories
        or constraints.preferred_categories
        or constraints.preferred_sources
        or constraints.preferred_keywords
        or constraints.disliked_keywords
        or constraints.max_price is not None
        or constraints.use_cases
        or constraints.filter_prior_turn_items
    )


def _has_any_constraint_or_unsupported(constraints: FeedbackConstraints) -> bool:
    return _has_supported_constraint(constraints) or bool(constraints.unsupported_free_text)
