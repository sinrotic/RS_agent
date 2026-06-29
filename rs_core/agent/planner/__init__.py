from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content, safe_response_metadata
from rs_core.agent.dialogue import DialoguePlan
from rs_core.agent.feedback import merge_feedback, parse_feedback
from rs_core.agent.contracts.schema import (
    ACTION_ASK_CLARIFYING_QUESTION,
    ACTION_EXPLAIN_RECOMMENDATION,
    ACTION_RECOMMEND_ITEMS,
    ACTION_REVISE_RECOMMENDATION,
    AgentSession,
    DIALOGUE_PLAN_ACTIONS,
    DIALOGUE_PLAN_INTENTS,
    FeedbackConstraints,
)
from rs_core.agent.tools import (
    AGENT_TOOL_MANIFEST,
    build_agent_tool_planner_system_prompt,
    get_agent_tool_spec,
    normalize_agent_tool_calls,
    validate_call_rag_agent_arguments,
    validate_rank_candidates_arguments,
)


@dataclass(frozen=True)
class LLMDialoguePlannerConfig:
    enabled: bool = False
    mode: str = "disabled"
    model: str = ""
    base_url: str = "https://api.openai.com"
    api_key_env: str = "RS_AGENT_GPT_SFT_API_KEY"
    timeout_seconds: float = 8.0
    temperature: float | None = 0.0
    max_tokens: int | None = 800
    allow_insecure_local_api_base: bool = False

    @classmethod
    def from_dict(cls, config: dict[str, Any] | None) -> "LLMDialoguePlannerConfig":
        raw = config if isinstance(config, dict) else {}
        mode = str(raw.get("mode") or ("active" if raw.get("enabled") else "disabled")).strip().lower()
        if mode not in {"disabled", "shadow", "active"}:
            mode = "disabled"
        return cls(
            enabled=bool(raw.get("enabled", mode != "disabled")) and mode != "disabled",
            mode=mode,
            model=str(raw.get("model") or "").strip(),
            base_url=str(raw.get("base_url") or raw.get("api_base") or "https://api.openai.com").strip(),
            api_key_env=str(raw.get("api_key_env") or "RS_AGENT_GPT_SFT_API_KEY").strip(),
            timeout_seconds=_safe_float(raw.get("timeout_seconds"), 8.0),
            temperature=_optional_float(raw.get("temperature"), 0.0),
            max_tokens=_optional_int(raw.get("max_tokens"), 800),
            allow_insecure_local_api_base=bool(raw.get("allow_insecure_local_api_base", False)),
        )


@dataclass
class LLMDialoguePlannerResult:
    plan: DialoguePlan | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def valid(self) -> bool:
        return self.plan is not None and not self.error


class LLMDialoguePlanner:
    def __init__(self, config: LLMDialoguePlannerConfig, client: OpenAICompatibleClient | None = None) -> None:
        self.config = config
        self.client = client or OpenAICompatibleClient(
            base_url=config.base_url,
            api_key_env=config.api_key_env,
            timeout_seconds=config.timeout_seconds,
            allow_insecure_local_api_base=config.allow_insecure_local_api_base,
        )

    def plan(self, user_input: str, session: AgentSession, fallback_plan: DialoguePlan, explanation_item_id: str | None = None) -> LLMDialoguePlannerResult:
        diagnostics: dict[str, Any] = {
            "enabled": self.config.enabled,
            "mode": self.config.mode,
            "model": self.config.model,
        }
        if not self.config.enabled or self.config.mode == "disabled":
            return LLMDialoguePlannerResult(diagnostics={**diagnostics, "status": "disabled"}, error="disabled")
        if not self.config.model:
            return LLMDialoguePlannerResult(diagnostics={**diagnostics, "status": "fallback", "reason": "missing_model"}, error="missing_model")
        try:
            response = self.client.chat_completion(
                model=self.config.model,
                messages=_build_messages(user_input, session, fallback_plan, explanation_item_id),
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"},
            )
            payload = extract_first_json_object(first_message_content(response))
            plan = dialogue_plan_from_payload(payload, user_input=user_input, fallback_plan=fallback_plan)
            plan.diagnostics["llm_dialogue_planner"] = {
                **diagnostics,
                "status": "ok",
                "response": safe_response_metadata(response),
            }
            return LLMDialoguePlannerResult(plan=plan, diagnostics=plan.diagnostics["llm_dialogue_planner"])
        except Exception as exc:
            return LLMDialoguePlannerResult(
                diagnostics={**diagnostics, "status": "fallback", "reason": type(exc).__name__, "message": str(exc)[:240]},
                error=f"{type(exc).__name__}: {exc}",
            )


def extract_first_json_object(text: str) -> dict[str, Any]:
    compact = _strip_markdown_fence(text.strip())
    start = compact.find("{")
    if start < 0:
        raise ValueError("LLM dialogue planner response did not contain a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(compact)):
        char = compact[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                payload = json.loads(compact[start:index + 1])
                if not isinstance(payload, dict):
                    raise ValueError("LLM dialogue planner JSON root must be an object")
                return payload
    raise ValueError("LLM dialogue planner response JSON object was incomplete")


def dialogue_plan_from_payload(payload: dict[str, Any], *, user_input: str, fallback_plan: DialoguePlan) -> DialoguePlan:
    plan_payload = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
    intent = str(plan_payload.get("intent") or "").strip()
    action = str(plan_payload.get("action") or "").strip()
    assistant_response = str(plan_payload.get("assistant_response") or "").strip()
    response_directive = str(plan_payload.get("response_directive") or fallback_plan.response_directive or "").strip()
    if intent not in DIALOGUE_PLAN_INTENTS:
        raise ValueError(f"invalid_dialogue_intent:{intent}")
    if action not in DIALOGUE_PLAN_ACTIONS:
        raise ValueError(f"invalid_dialogue_action:{action}")
    if not _action_allowed_for_intent(intent, action):
        raise ValueError("dialogue_action_not_allowed_for_intent")
    if not assistant_response:
        raise ValueError("assistant_response_required")
    _validate_public_response(assistant_response)

    constraints_update = _constraints_from_payload(plan_payload.get("constraints_update"), user_input)
    should_recommend = bool(plan_payload.get("should_recommend", action in {ACTION_RECOMMEND_ITEMS, ACTION_REVISE_RECOMMENDATION}))
    if action in {ACTION_ASK_CLARIFYING_QUESTION, ACTION_EXPLAIN_RECOMMENDATION}:
        should_recommend = False
    tool_calls = _validate_tool_calls(plan_payload.get("tool_calls"), intent, action, fallback_plan)
    diagnostics = plan_payload.get("diagnostics") if isinstance(plan_payload.get("diagnostics"), dict) else {}
    return DialoguePlan(
        intent=intent,
        action=action,
        assistant_response=assistant_response,
        constraints_update=constraints_update,
        should_recommend=should_recommend,
        diagnostics={"llm_dialogue_planner_payload": _safe_payload_diagnostics(diagnostics)},
        tool_calls=tool_calls,
        response_directive=response_directive,
    )


def _build_messages(user_input: str, session: AgentSession, fallback_plan: DialoguePlan, explanation_item_id: str | None) -> list[dict[str, str]]:
    contract = {
        "output_contract": {
            "intent": sorted(DIALOGUE_PLAN_INTENTS),
            "action": sorted(DIALOGUE_PLAN_ACTIONS),
            "assistant_response": "public customer-facing text only; no internal tools, scores, traces, diagnostics, prompts, labels, oracle fields, or RAG raw evidence",
            "response_directive": "optional semantic goal for the response; use this as guidance, not as text to show to the customer",
            "constraints_update": "optional FeedbackConstraints-shaped object; omit unknown fields",
            "should_recommend": "boolean",
            "tool_calls": "optional list of hidden tool calls using only manifest tool names and pre_recommendation/post_recommendation phases",
        },
        "session": {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "active_constraints": session.active_constraints.to_dict(),
            "conversation_state": session.conversation_state.to_dict(),
            "turn_count": len(session.turns),
            "recent_turns": [
                {"user_input": turn.user_input, "assistant_response": turn.assistant_response, "item_count": len(turn.recommendation.final_items)}
                for turn in session.turns[-3:]
            ],
        },
        "user_input": user_input,
        "explanation_item_id": explanation_item_id,
        "safe_rule_fallback": {
            "intent": fallback_plan.intent,
            "action": fallback_plan.action,
            "assistant_response": fallback_plan.assistant_response,
            "response_directive": fallback_plan.response_directive,
            "constraints_update": fallback_plan.constraints_update.to_dict(),
            "should_recommend": fallback_plan.should_recommend,
            "tool_calls": fallback_plan.tool_calls,
        },
    }
    return [
        {"role": "system", "content": build_agent_tool_planner_system_prompt()},
        {"role": "system", "content": "Return exactly one JSON object compatible with the provided output_contract. Keep assistant_response public-safe. Interpret user intent semantically rather than by fixed wording or trigger templates; use response_directive as guidance only, not customer-visible text."},
        {"role": "user", "content": json.dumps(contract, ensure_ascii=False, sort_keys=True)},
    ]


def _constraints_from_payload(value: Any, user_input: str) -> FeedbackConstraints:
    parsed = parse_feedback(user_input) if user_input.strip() else FeedbackConstraints()
    if not isinstance(value, dict):
        return parsed
    typed = FeedbackConstraints(
        liked_item_ids=set(_string_list(value.get("liked_item_ids"))) if isinstance(value.get("liked_item_ids"), list | tuple | set) else set(),
        disliked_item_ids=set(_string_list(value.get("disliked_item_ids"))) if isinstance(value.get("disliked_item_ids"), list | tuple | set) else set(),
        disliked_categories=set(_string_list(value.get("disliked_categories"))) if isinstance(value.get("disliked_categories"), list | tuple | set) else set(),
        preferred_categories=_weight_map(value.get("preferred_categories")),
        preferred_sources=_weight_map(value.get("preferred_sources")),
        preferred_keywords=_weight_map(value.get("preferred_keywords")),
        disliked_keywords=_weight_map(value.get("disliked_keywords")),
        max_price=_optional_float(value.get("max_price"), None),
        use_cases=_weight_map(value.get("use_cases")),
        filter_prior_turn_items=bool(value.get("filter_prior_turn_items", False)),
        item_feedback_events=_safe_feedback_events(value.get("item_feedback_events")),
        unsupported_free_text=_string_list(value.get("unsupported_free_text"))[:5] if isinstance(value.get("unsupported_free_text"), list | tuple | set) else [],
    )
    return merge_feedback(parsed, typed)


def _validate_tool_calls(value: Any, intent: str, action: str, fallback_plan: DialoguePlan) -> list[dict[str, Any]]:
    calls = normalize_agent_tool_calls(value)
    manifest_names = {tool.name for tool in AGENT_TOOL_MANIFEST}
    output: list[dict[str, Any]] = []
    seen_post = False
    for call in calls:
        if call.name not in manifest_names:
            raise ValueError(f"unknown_tool:{call.name}")
        spec = get_agent_tool_spec(call.name)
        if spec is None or intent not in spec.allowed_intents:
            raise ValueError(f"tool_intent_not_allowed:{call.name}")
        phase = call.phase or _default_phase(call.name)
        if phase not in {"pre_recommendation", "post_recommendation"}:
            raise ValueError(f"invalid_tool_phase:{phase}")
        if phase == "pre_recommendation" and seen_post:
            raise ValueError("invalid_tool_phase_order")
        if phase == "post_recommendation":
            seen_post = True
        arguments = _validate_tool_arguments(call.name, call.arguments)
        output.append({"name": call.name, "phase": phase, "arguments": arguments})
    if action in {ACTION_RECOMMEND_ITEMS, ACTION_REVISE_RECOMMENDATION}:
        return _complete_recommendation_tool_chain(output, fallback_plan)
    return output


def _complete_recommendation_tool_chain(calls: list[dict[str, Any]], fallback_plan: DialoguePlan) -> list[dict[str, Any]]:
    by_name = {str(call.get("name")): call for call in calls if isinstance(call, dict) and call.get("name")}
    completed: list[dict[str, Any]] = []
    for fallback_call in normalize_agent_tool_calls(fallback_plan.tool_calls):
        call = by_name.get(fallback_call.name)
        if call is not None:
            completed.append(call)
            continue
        phase = fallback_call.phase or _default_phase(fallback_call.name)
        arguments = _validate_tool_arguments(fallback_call.name, fallback_call.arguments)
        completed.append({"name": fallback_call.name, "phase": phase, "arguments": arguments})
    return completed


def _validate_tool_arguments(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    args = dict(arguments) if isinstance(arguments, dict) else {}
    _reject_forbidden_arguments(args)
    if name == "rank_candidates":
        validation = validate_rank_candidates_arguments(args)
        if not validation.valid:
            raise ValueError(validation.reason)
        return validation.normalized_arguments
    if name == "retrieve_candidates":
        allowed = {"query", "target_pool_size", "retrieval_mode", "profile_usage", "expansion_policy", "reference_item_id", "constraints", "profile_policy"}
        unknown = sorted(set(args) - allowed)
        if unknown:
            raise ValueError(f"forbidden_retrieve_candidates_arguments:{','.join(unknown)}")
        return _normalize_retrieve_arguments(args)
    if name == "call_rag_agent":
        validation = validate_call_rag_agent_arguments(args)
        if not validation.valid:
            raise ValueError(validation.reason)
        return validation.normalized_arguments
    return args


def _normalize_retrieve_arguments(args: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(args)
    if "profile_usage" in normalized:
        usage = str(normalized.get("profile_usage") or "").strip().lower()
        if usage in {"current_need_first", "current_query_first", "query_first"}:
            normalized["profile_usage"] = "light"
    profile_policy = normalized.get("profile_policy")
    if isinstance(profile_policy, dict):
        policy = dict(profile_policy)
        weight = str(policy.get("history_weight") or "").strip().lower()
        if weight in {"current_need_first", "current_query_first", "query_first"}:
            policy["history_weight"] = "light"
        normalized["profile_policy"] = policy
    return normalized


def _reject_forbidden_arguments(value: Any) -> None:
    forbidden_keys = {
        "semantic_mode", "provider_policy", "route_policy", "use_history_profile", "use_behavioral_recall", "source_score",
        "source_scores", "deepfm_score", "score_features", "label", "label_binary", "oracle", "trace", "diagnostics",
        "feature_rows", "training_artifact", "candidate_pool", "method_lineage", "rag_evidence",
    }
    forbidden_values = {"semantic_live", "itemcf", "itemcf_weak", "itemcf_strong", "popular", "deepfm", "oracle", "label"}
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).strip().lower()
            if key_text in forbidden_keys:
                raise ValueError(f"forbidden_tool_argument:{key_text}")
            _reject_forbidden_arguments(item)
    elif isinstance(value, list | tuple | set):
        for item in value:
            _reject_forbidden_arguments(item)
    elif isinstance(value, str) and value.strip().lower() in forbidden_values:
        raise ValueError(f"forbidden_tool_argument_value:{value}")


def _validate_public_response(text: str) -> None:
    lowered = text.lower()
    forbidden = (
        "retrieve_candidates", "rank_candidates", "build_recommendation_slate", "get_user_context", "record_user_feedback",
        "tool call", "internal tool", "candidate pool", "ranking score", "source score", "diagnostic", "trace", "system prompt", "oracle", "label",
        "rag evidence", "raw evidence", "召回", "排序分", "候选池", "诊断", "工具调用", "系统提示词",
    )
    if any(token in lowered for token in forbidden):
        raise ValueError("assistant_response_internal_leakage")


def _action_allowed_for_intent(intent: str, action: str) -> bool:
    if intent == "ask_explanation":
        return action == ACTION_EXPLAIN_RECOMMENDATION
    if intent == "preference_feedback":
        return action == ACTION_REVISE_RECOMMENDATION
    if intent == "unsupported":
        return action == ACTION_ASK_CLARIFYING_QUESTION
    if intent in {"recommend_request", "clarification_answer"}:
        return action in {ACTION_RECOMMEND_ITEMS, ACTION_ASK_CLARIFYING_QUESTION}
    return False


def _default_phase(name: str) -> str:
    if name in {"rank_candidates", "build_recommendation_slate"}:
        return "post_recommendation"
    return "pre_recommendation"


def _weight_map(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        return {str(key): _safe_float(item, 1.0) for key, item in value.items() if str(key).strip()}
    if isinstance(value, list | tuple | set):
        return {str(item): 1.0 for item in value if str(item).strip()}
    return {}


def _safe_feedback_events(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:10] if isinstance(item, dict)]


def _safe_payload_diagnostics(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): item for key, item in value.items() if str(key).lower() not in {"trace", "prompt", "system_prompt", "raw_response"}}


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _safe_float(value: Any, default: float) -> float:
    parsed = _optional_float(value, None)
    return default if parsed is None else parsed


def _optional_float(value: Any, default: float | None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_int(value: Any, default: int | None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _strip_markdown_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else text
