from __future__ import annotations

import json
import os
import random
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from rs_core.common.config import load_config
from rs_core.common.io import write_json, write_jsonl
from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content, safe_response_metadata
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.offline.simulation.policy import RolePolicy
from rs_core.offline.simulation.schema import RoleAction, RoleActionType, RoleState, SimulatedCustomerRole

MULTI_TURN_SFT_SCHEMA_VERSION = "rs_agent_multi_turn_sft_sample_v1"
MULTI_TURN_RUN_SCHEMA_VERSION = "rs_agent_multi_turn_sft_generation_run_v1"
DEFAULT_CONFIG = "configs/training/multi_turn_sft_gpt53.yaml"
DEFAULT_SERVICE_CONFIG = "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml"
FORBIDDEN_PUBLIC_KEYS = {
    "diagnostics",
    "agent_runtime_trace",
    "agent_tool_summary",
    "tool_traces",
    "source_scores",
    "rag_context",
    "rag_agent_support",
    "rag_agent_shadow",
    "raw_rag_evidence",
    "trace_events",
    "commit_intents",
    "internal_output",
    "manifest",
    "retriever",
    "reward",
    "training_samples",
    "label_binary",
    "target_item",
    "ground_truth",
    "oracle",
}


@dataclass(frozen=True)
class OpenAICompletionAdapter:
    client: OpenAICompatibleClient
    model: str
    temperature: float = 0.4
    max_tokens: int = 1200
    response_format: dict[str, Any] | None = None

    def complete(self, messages: list[dict[str, str]]) -> str:
        return first_message_content(
            self.client.chat_completion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format=self.response_format,
            )
        )

    def complete_with_metadata(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        response = self.client.chat_completion(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            response_format=self.response_format,
        )
        return first_message_content(response), safe_response_metadata(response)


class RecommendationAgentComposer:
    def __init__(self, adapter: OpenAICompletionAdapter | None = None) -> None:
        self.adapter = adapter

    def compose(self, *, persona: dict[str, Any], user_message: str, display: dict[str, Any], history: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        original = str(display.get("assistant_message") or "").strip()
        display_items = [_public_item(item) for item in display.get("items", []) if isinstance(item, dict)]
        if not display_items:
            return original, {"mode": "composer_skipped_no_grounding", "api_called": False}
        if self.adapter is None:
            return _deterministic_display_message(user_message=user_message, display_items=display_items), {"mode": "deterministic_display_message", "api_called": False}
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the recommendation agent in a recommender-system SFT data generation run. "
                    "Rewrite the assistant response as natural customer-facing shopping advice grounded only in the displayed items. "
                    "Use the visible dialogue semantically rather than matching fixed user phrases: infer whether the customer is exploring, changing preferences, dissatisfied, or making progress. "
                    "Assume the customer does not know or care about internal recommendation mechanisms such as history use, retrieval, ranking, candidates, or display construction; never mention those mechanics. "
                    "Recommend 2-3 products with short product names and concrete use-case reasons, not long raw titles. "
                    "Say what problem each product itself helps solve for the customer's current situation; do not turn internal evidence into a public explanation. "
                    "When the dialogue shows weak progress or unresolved preference changes, acknowledge the semantic feedback, explain how this response adjusts the recommendation strategy, and add one focused question that helps narrow the next decision. "
                    "Only state product attributes that are explicitly present in the public title, category, summary, description, features, or price; when unsure, frame it as a possible use case rather than a factual spec. "
                    "Do not explain how the evidence was inferred from product naming or fields; customers should hear the product benefit rather than source-analysis wording. "
                    "Keep the explanation helpful enough for a customer to decide, but do not reveal hidden tools, scores, diagnostics, raw RAG evidence, or internal traces. "
                    "Return JSON: {\"assistant_message\": string}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "public_persona_summary": _public_persona_summary(persona),
                        "latest_user_message": user_message,
                        "service_assistant_message": original,
                        "display_items": display_items,
                        "visible_dialogue": _visible_dialogue(history),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        content, metadata = self.adapter.complete_with_metadata(messages)
        payload = _parse_json_object(content)
        rewritten = str(payload.get("assistant_message") or "").strip()
        if not rewritten:
            raise ValueError("recommendation agent composer returned empty assistant_message")
        return rewritten, {"mode": "gpt_recommendation_composer", "api_called": True, "response": metadata}


def _deterministic_display_message(*, user_message: str, display_items: list[dict[str, Any]]) -> str:
    selected_items = [item for item in display_items if _item_label(item) or _public_item_reason(item)][:3]
    if not selected_items:
        return "我先推荐几件比较稳妥的选择，你可以先看哪一类更接近你的需求。"

    lines = ["我推荐这几件："]
    for index, item in enumerate(selected_items, start=1):
        label = _item_label(item)
        prefix = f"{index}. {label}" if label else f"{index}. 这件商品"
        reason = _public_item_reason(item) or "适合作为日常使用的稳妥备选"
        lines.append(f"{prefix}：{reason}。")
    lines.append("如果你想再缩小范围，我可以继续按预算、使用场景或外观偏好帮你筛。")
    return "\n".join(lines)


def _item_label(item: dict[str, Any]) -> str:
    return _compact_public_title(_clean_public_text(item.get("title")))


def _item_title(item: dict[str, Any]) -> str:
    return _item_label(item)


def _compact_public_title(title: str) -> str:
    if not title:
        return ""
    cleaned = re.sub(r"\s*\([^)]*\)", " ", title)
    cleaned = re.sub(r"\b\d+\s*(?:pack|pcs?|pieces|count|ct)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:white|black|clear|charcoal|latest release)\b", " ", cleaned, flags=re.IGNORECASE)
    parts = [part.strip(" -|,;:/") for part in re.split(r"\s[-|]\s|,\s*", cleaned) if part.strip(" -|,;:/")]
    candidates: list[str] = []
    for part in parts or [cleaned]:
        part = re.sub(r"\s+", " ", part).strip()
        part = re.sub(r"\s+with\s+.*$", "", part, flags=re.IGNORECASE).strip()
        part = re.sub(r"\s+for\s+.*$", "", part, flags=re.IGNORECASE).strip()
        part = re.sub(r"\s+by\s+.*$", "", part, flags=re.IGNORECASE).strip()
        if len(part) >= 4 and re.search(r"[A-Za-z一-鿿]", part):
            candidates.append(part)
    label = min(candidates, key=len) if candidates else cleaned.strip()
    return _truncate_public_text(label, 32)


def _public_item_reason(item: dict[str, Any]) -> str:
    reasons: list[str] = []
    title = _clean_public_text(item.get("title"))
    summary = _clean_public_text(item.get("summary")) or _clean_public_text(item.get("description"))
    features = [_clean_public_text(feature) for feature in item.get("features", []) if _clean_public_text(feature)]
    price = _clean_public_text(item.get("price"))
    label = _compact_public_title(title)
    title_context = _public_title_context(title, label)
    if summary and summary.lower() not in title.lower():
        reasons.append(_truncate_public_text(summary, 54))
    elif features:
        reasons.append("有" + "、".join(features[:2]) + "这些实用点")
    elif title_context:
        reasons.append(f"可作为{title_context}相关需求的备选，适合先判断是否贴近你的使用场景")
    elif label:
        reasons.append(f"偏{label}这个方向，适合先判断是否贴近你的使用场景")
    if price:
        reasons.append(f"价格是{price}，方便你一起衡量预算")
    return "；".join(reasons[:3])


def _public_title_context(title: str, label: str) -> str:
    if not title:
        return ""
    cleaned = re.sub(r"\s*\([^)]*\)", " ", title)
    cleaned = re.sub(r"\b\d+\s*(?:pack|pcs?|pieces|count|ct)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:white|black|clear|charcoal|latest release|made in)\b", " ", cleaned, flags=re.IGNORECASE)
    phrases = [part.strip(" -|,;:/") for part in re.split(r"\s[-|]\s|,\s*", cleaned) if part.strip(" -|,;:/")]
    useful_phrases = []
    for phrase in phrases:
        phrase = re.sub(r"\s+", " ", phrase).strip()
        if label and phrase.lower() == label.lower():
            continue
        if len(phrase) < 6 or not re.search(r"[A-Za-z一-鿿]", phrase):
            continue
        useful_phrases.append(_truncate_public_text(phrase, 42))
    if useful_phrases:
        return "、".join(useful_phrases[:2])
    if label:
        return f"它主要对应{label}"
    return ""


def _clean_public_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text


def _truncate_public_text(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[:max_chars].rstrip() + "..."


class PersonaCondenserAgent:
    def __init__(self, adapter: OpenAICompletionAdapter | None = None) -> None:
        self.adapter = adapter

    def build(self, user_id: str, segment: str, sequence: dict[str, Any], item_metadata: dict[str, dict[str, Any]]) -> tuple[SimulatedCustomerRole, dict[str, Any]]:
        evidence = _history_evidence(sequence, item_metadata)
        base = _deterministic_persona(user_id, segment, sequence, evidence)
        if self.adapter is None:
            return _role_from_persona(base), base
        messages = [
            {
                "role": "system",
                "content": (
                    "You are PersonaCondenserAgent for recommender-system simulation data generation. "
                    "Read only train-history evidence and condense it into simulator_private_context/persona for a hidden simulated user. "
                    "This private context is not the recommendation agent's visible input. "
                    "Do not decide the public user request here, do not expose labels, future positives, oracle targets, scores, or hidden catalog assumptions. "
                    "Return JSON with keys: persona, shopping_goal, budget_sensitivity, category_preferences, "
                    "keyword_preferences, negative_preferences, decision_style, feedback_style, memory, past_interactions_summary."
                ),
            },
            {"role": "user", "content": json.dumps({"base_persona": base, "train_history_evidence": evidence}, ensure_ascii=False)},
        ]
        payload = _parse_json_object(self.adapter.complete(messages))
        persona = _sanitize_persona_payload(user_id, segment, sequence, evidence, payload)
        return _role_from_persona(persona), persona


PersonaBuilder = PersonaCondenserAgent


class SimulatedUserAgent:
    def __init__(self, adapter: OpenAICompletionAdapter | None = None, *, strict: bool = False) -> None:
        self.adapter = adapter
        self.strict = strict
        self.fallback_policy = RolePolicy()

    def initial_action(self, role: SimulatedCustomerRole, history: list[dict[str, Any]], last_display: dict[str, Any] | None = None) -> RoleAction:
        if self.adapter is None:
            return RoleAction.chat(_clean_initial_request(role.initial_prompt()))
        try:
            payload = self._model_action_payload(role, RoleState(), history, last_display or {}, phase="initial_action")
            message = str(payload.get("message") or payload.get("intent") or "").strip()
            if not message:
                raise ValueError("SimulatedUserAgent initial_action requires message")
            return RoleAction.chat(message)
        except Exception as exc:
            if self.strict:
                raise exc
            return RoleAction.chat(_clean_initial_request(role.initial_prompt()))

    def next_action(self, role: SimulatedCustomerRole, state: RoleState, history: list[dict[str, Any]], last_display: dict[str, Any]) -> RoleAction:
        if self.adapter is None:
            return self.fallback_policy.next_action(role, state, last_display)
        try:
            payload = self._model_action_payload(role, state, history, last_display, phase="next_action")
            action = _role_action_from_payload(payload, last_display)
            state.remember_display(last_display)
            return action
        except Exception as exc:
            if self.strict:
                raise exc
            return self.fallback_policy.next_action(role, state, last_display)

    def _model_action_payload(
        self,
        role: SimulatedCustomerRole,
        state: RoleState,
        history: list[dict[str, Any]],
        last_display: dict[str, Any],
        *,
        phase: str,
    ) -> dict[str, Any]:
        assert self.adapter is not None
        return _parse_json_object(self.adapter.complete(_simulated_user_messages(role, state, history, last_display, phase=phase)))


def run_multi_turn_sft_generation(
    config_path: str | Path = DEFAULT_CONFIG,
    *,
    execute: bool = False,
    limit: int | None = None,
    dry_run_override: bool | None = None,
) -> dict[str, Any]:
    config = _load_multi_turn_config(config_path)
    generation = config["generation"]
    model_config = config["model"]
    target_samples = int(limit or generation.get("target_samples") or 1)
    dry_run = bool(generation.get("dry_run", True) if dry_run_override is None else dry_run_override) and not execute
    if execute and not bool(generation.get("enabled", False)):
        raise RuntimeError("multi-turn SFT execution requires generation.enabled=true in config")
    rng = random.Random(int(generation.get("seed", 20260621)))

    output_path = _project_path(generation.get("output_path") or "outputs/training/multi_turn_sft/samples.jsonl")
    manifest_path = _project_path(generation.get("manifest_path") or str(output_path.with_name("manifest.json")))
    rejects_path = _project_path(generation.get("rejects_path") or str(output_path.with_name("rejects.jsonl")))
    flat_output_path = _project_path(generation.get("flat_output_path") or str(output_path.with_name("turns_flattened.jsonl")))

    limit_users_value = generation.get("limit_users")
    limit_users = int(limit_users_value) if limit_users_value not in (None, "", 0, "0") else None
    service_config_path = _project_path(generation.get("service_config") or DEFAULT_SERVICE_CONFIG)
    service_overrides = {"evaluation_mode": "public_serving"}
    service = RecommendationService(
        config=service_config_path,
        limit_users=limit_users,
        config_overrides=service_overrides,
    )
    client = _openai_client(model_config) if execute else None
    adapter = (
        OpenAICompletionAdapter(
            client=client,
            model=str(model_config.get("model") or "gpt-5.3-codex-spark"),
            temperature=float(model_config.get("temperature", 0.4)),
            max_tokens=int(model_config.get("max_tokens", 1200)),
            response_format=dict(model_config.get("response_format") or {"type": "json_object"}),
        )
        if client is not None
        else None
    )
    persona_builder = PersonaCondenserAgent(adapter if execute else None)
    simulated_user = SimulatedUserAgent(adapter if execute else None, strict=bool(generation.get("strict_model_policy", False)))
    recommendation_composer = RecommendationAgentComposer(adapter if execute else None)

    selected_users = _sample_mid_high_users(service.env.sequences_by_user, target_samples, rng)
    samples: list[dict[str, Any]] = []
    flat_samples: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    max_turns = int(generation.get("max_turns_per_scene", 6))
    min_turns = int(generation.get("min_turns_per_scene", 2))
    max_consecutive_rejects = int(generation.get("max_consecutive_rejects", 10))
    consecutive_rejects = 0

    for index, (user_id, segment, sequence) in enumerate(selected_users, start=1):
        if len(samples) >= target_samples:
            break
        try:
            role, persona = persona_builder.build(user_id, segment, sequence, service.env.item_metadata)
            sample = _run_one_scene(
                service=service,
                user_id=user_id,
                role=role,
                persona=persona,
                sample_index=index,
                min_turns=min_turns,
                max_turns=max_turns,
                simulated_user=simulated_user,
                recommendation_composer=recommendation_composer,
                model_name=str(model_config.get("model") or "gpt-5.3-codex-spark"),
                execute=execute,
            )
            validate_multi_turn_sft_sample(sample, min_turns=min_turns)
            samples.append(sample)
            flat_samples.extend(_flatten_turn_samples(sample))
            consecutive_rejects = 0
            if not dry_run:
                _write_partial_outputs(output_path, flat_output_path, rejects_path, samples, flat_samples, rejects)
        except Exception as exc:  # batch job records rejects and continues.
            consecutive_rejects += 1
            rejects.append({"user_id": user_id, "segment": segment, "reason": type(exc).__name__, "message": str(exc)[:500]})
            if not dry_run:
                _write_partial_outputs(output_path, flat_output_path, rejects_path, samples, flat_samples, rejects)
            if consecutive_rejects >= max_consecutive_rejects:
                break

    if not dry_run:
        _write_partial_outputs(output_path, flat_output_path, rejects_path, samples, flat_samples, rejects)
    manifest = _manifest(
        config_path=str(config_path),
        output_path=output_path,
        flat_output_path=flat_output_path,
        rejects_path=rejects_path,
        target_samples=target_samples,
        samples=samples,
        rejects=rejects,
        model_config=model_config,
        dry_run=dry_run,
        execute=execute,
    )
    if not dry_run:
        write_json(manifest_path, manifest)
    return {
        **manifest,
        "manifest_path": str(manifest_path),
        "api_called": bool(execute),
        "first_sample_preview": _sample_preview(samples[0]) if samples else None,
    }


def validate_multi_turn_sft_sample(record: dict[str, Any], *, min_turns: int = 2) -> None:
    if record.get("schema_version") != MULTI_TURN_SFT_SCHEMA_VERSION:
        raise ValueError(f"sample schema_version must be {MULTI_TURN_SFT_SCHEMA_VERSION}")
    dialogue = record.get("dialogue")
    if not isinstance(dialogue, list) or len(dialogue) < min_turns:
        raise ValueError("multi-turn sample dialogue is shorter than required")
    for turn in dialogue:
        user_message = str(turn.get("user_message") or "").strip()
        assistant_message = str(turn.get("assistant_message") or "").strip()
        if not user_message or not assistant_message:
            raise ValueError("each dialogue turn requires user_message and assistant_message")
        display_ids = {str(item_id) for item_id in turn.get("display_item_ids", []) if str(item_id)}
        selected_ids = {str(item_id) for item_id in turn.get("selected_item_ids", []) if str(item_id)}
        target_action = turn.get("target_action", {}) if isinstance(turn.get("target_action"), dict) else {}
        target_selected_ids = {str(item_id) for item_id in target_action.get("selected_item_ids", []) if str(item_id)}
        allowed_ids = {str(item_id) for item_id in target_action.get("allowed_item_ids", []) if str(item_id)}
        must_select = bool(target_action.get("must_select_from_candidates"))
        action_type = str(turn.get("action_type") or target_action.get("trigger_reason") or "").strip().lower()
        strategy_name = str(target_action.get("strategy_name") or "").strip()
        if selected_ids != target_selected_ids:
            raise ValueError("selected_item_ids must match target_action.selected_item_ids")
        if selected_ids and not selected_ids <= display_ids:
            raise ValueError("selected_item_ids must be a subset of display_item_ids")
        if target_selected_ids and not target_selected_ids <= display_ids:
            raise ValueError("target_action.selected_item_ids must be a subset of display_item_ids")
        if allowed_ids and not allowed_ids <= display_ids:
            raise ValueError("target_action.allowed_item_ids must be a subset of display_item_ids")
        tool_supervision = turn.get("tool_supervision") if isinstance(turn.get("tool_supervision"), dict) else {}
        turn_should_recommend = bool(tool_supervision.get("should_recommend", bool(display_ids)))
        if selected_ids and allowed_ids and not selected_ids <= allowed_ids:
            raise ValueError("selected_item_ids must be a subset of target_action.allowed_item_ids")
        if target_selected_ids and allowed_ids and not target_selected_ids <= allowed_ids:
            raise ValueError("target_action.selected_item_ids must be a subset of target_action.allowed_item_ids")
        if must_select and not display_ids:
            raise ValueError("must_select_from_candidates requires non-empty display_item_ids")
        if not turn_should_recommend and strategy_name == "public_display_grounded_response":
            raise ValueError("no-recommend turn cannot use public_display_grounded_response")
        if (not display_ids or not turn_should_recommend) and _looks_like_recommendation_list(assistant_message):
            raise ValueError("no-display/no-recommend turn cannot contain an obvious recommendation list")
        if must_select and allowed_ids and not selected_ids and strategy_name == "public_display_grounded_response":
            raise ValueError("public_display_grounded_response must_select_from_candidates requires selected_item_ids")
        if must_select and allowed_ids and not selected_ids and (action_type == RoleActionType.ACCEPT.value or strategy_name == "accept_displayed_item"):
            raise ValueError("accept must_select_from_candidates requires selected_item_ids")
        _assert_no_forbidden_public_keys(turn)
    grounding = record.get("grounding") or {}
    if grounding.get("forbidden_eval_fields_present"):
        raise ValueError("sample contains forbidden eval/internal fields")


def _run_one_scene(
    *,
    service: RecommendationService,
    user_id: str,
    role: SimulatedCustomerRole,
    persona: dict[str, Any],
    sample_index: int,
    min_turns: int,
    max_turns: int,
    simulated_user: SimulatedUserAgent,
    recommendation_composer: RecommendationAgentComposer,
    model_name: str,
    execute: bool,
) -> dict[str, Any]:
    state = RoleState()
    session_id = service.start_session(user_id=user_id)
    dialogue: list[dict[str, Any]] = []
    composer_metadata: list[dict[str, Any]] = []
    first_action = simulated_user.initial_action(role, dialogue, None)
    result = service.chat(session_id, first_action.message)
    diagnostics = _service_turn_diagnostics(service, session_id)
    assistant_message, metadata = _compose_grounded_response(
        recommendation_composer,
        persona=persona,
        user_message=first_action.message,
        display=result.display,
        history=dialogue,
        diagnostics=diagnostics,
    )
    composer_metadata.append(metadata)
    result.display["assistant_message"] = assistant_message
    dialogue.append(_turn_record(1, first_action, result.display, assistant_message, diagnostics=diagnostics))
    final_action = first_action

    for turn_index in range(2, max(2, max_turns) + 1):
        next_action = simulated_user.next_action(role, state, dialogue, result.display)
        final_action = next_action
        if next_action.type == RoleActionType.ACCEPT:
            if turn_index >= min_turns:
                display_item_ids = _display_item_ids(result.display)
                if not display_item_ids:
                    next_action = RoleAction.chat("Please show me concrete options first.")
                    final_action = next_action
                elif not next_action.item_id:
                    next_action = RoleAction.why(display_item_ids[0])
                    final_action = next_action
                else:
                    accepted_display = result.display
                    try:
                        service.feedback(session_id, RoleActionType.ACCEPT.value, next_action.item_id, next_action.comment)
                        accept_diagnostics = _accept_terminal_diagnostics(recorded=True)
                        assistant_message = "好的，已记录你接受当前推荐。"
                    except ValueError:
                        accept_diagnostics = _accept_terminal_diagnostics(recorded=False)
                        assistant_message = "我理解你想接受当前推荐，但系统没有成功记录这次接受动作。"
                    dialogue.append(
                        _terminal_turn_record(
                            turn_index,
                            next_action,
                            accepted_display,
                            assistant_message,
                            diagnostics=accept_diagnostics,
                        )
                    )
                    break
            else:
                next_action = RoleAction.why(next_action.item_id)
                final_action = next_action
        if next_action.type == RoleActionType.CHAT:
            result = service.chat(session_id, next_action.message)
            user_message = next_action.message
        else:
            action_type = next_action.action_type or next_action.type.value
            result = service.feedback(session_id, action_type, next_action.item_id, next_action.comment)
            user_message = _feedback_user_message(action_type, next_action.item_id, next_action.comment)
        diagnostics = _service_turn_diagnostics(service, session_id)
        assistant_message, metadata = _compose_grounded_response(
            recommendation_composer,
            persona=persona,
            user_message=user_message,
            display=result.display,
            history=dialogue,
            diagnostics=diagnostics,
        )
        composer_metadata.append(metadata)
        result.display["assistant_message"] = assistant_message
        dialogue.append(_turn_record(turn_index, next_action, result.display, assistant_message, user_message=user_message, diagnostics=diagnostics))

    session_export = service.feedback_session_facade.export_session(session_id)
    display_ids_union = sorted({item_id for turn in dialogue for item_id in turn.get("display_item_ids", [])})
    return {
        "schema_version": MULTI_TURN_SFT_SCHEMA_VERSION,
        "sample_id": f"multi-turn-{sample_index:05d}-{uuid4().hex[:8]}",
        "user_id": user_id,
        "segment": persona.get("segment", "unknown"),
        "persona": persona,
        "simulator_private_context": role.private_context,
        "dialogue": dialogue,
        "session_summary": {
            "session_id": session_id,
            "turn_count": int(session_export.get("turn_count", len(dialogue))),
            "dialogue_turn_count": len(dialogue),
            "final_action": final_action.type.value,
            "accepted_item_id": final_action.item_id if final_action.type == RoleActionType.ACCEPT else None,
        },
        "grounding": {
            "display_item_ids_union": display_ids_union,
            "candidate_item_ids_union": display_ids_union,
            "forbidden_eval_fields_present": _contains_forbidden_public_keys({"dialogue": dialogue}),
        },
        "metadata": {
            "recommendation_agent_model": model_name if execute else "deterministic_display_message",
            "simulated_user_agent_model": model_name if execute else "deterministic_role_policy",
            "service_config_path": service.env.config_path,
            "composer_metadata": composer_metadata,
        },
    }


def _compose_grounded_response(
    composer: RecommendationAgentComposer,
    *,
    persona: dict[str, Any],
    user_message: str,
    display: dict[str, Any],
    history: list[dict[str, Any]],
    diagnostics: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    original = str(display.get("assistant_message") or "").strip()
    if not (_should_recommend(diagnostics, display) and _display_item_ids(display)):
        if _is_grounded_explanation_response(original, diagnostics, history):
            sanitized = _sanitize_grounded_explanation_message(original, history)
            metadata = {"mode": "grounded_explanation_passthrough", "api_called": False, "composer_skipped_no_grounding": True}
            if sanitized != original:
                metadata["sanitized"] = True
            return sanitized, metadata
        sanitized = _sanitize_dialogue_only_assistant_message(original)
        metadata = {"mode": "dialogue_only_passthrough", "api_called": False, "composer_skipped_no_grounding": True}
        if sanitized != original:
            metadata["sanitized"] = True
        return sanitized, metadata
    return composer.compose(persona=persona, user_message=user_message, display=display, history=history)


def _is_grounded_explanation_response(text: str, diagnostics: dict[str, Any], history: list[dict[str, Any]]) -> bool:
    if diagnostics.get("agent_action") != "explain_recommendation":
        return False
    if not any(turn.get("display_item_ids") for turn in history if isinstance(turn, dict)):
        return False
    return bool(re.search(r"最近一次推荐列表里推荐|我推荐.+主要是因为|主要因为|因为它", text))


def _sanitize_grounded_explanation_message(text: str, history: list[dict[str, Any]]) -> str:
    allowed_ids: set[str] = set()
    for turn in history:
        if not isinstance(turn, dict):
            continue
        ids = {str(item_id) for item_id in turn.get("display_item_ids", []) if str(item_id)}
        if ids:
            allowed_ids = ids
    if _outside_public_item_ids(text, allowed_ids):
        return "我只能解释最近一次展示列表里的商品。你可以点选当前列表中的商品让我说明原因。"
    sanitized = re.sub(r"展示评分为\s*[0-9.]+[。.]?", "", text).strip()
    sanitized = re.sub(r";\s*。", "。", sanitized).strip()
    return sanitized or text


def _sanitize_dialogue_only_assistant_message(text: str) -> str:
    sanitized = re.sub(r"展示评分为\s*[0-9.]+[。.]?", "", text).strip()
    sanitized = re.sub(r"(?<![A-Za-z0-9_])B[A-Z0-9]{9}(?![A-Za-z0-9_])", "", sanitized)
    sanitized = re.sub(r"(?<![\w])(?:parent_asin|item_id|商品ID|商品编号)\s*[:：=#-]?\s*[A-Za-z0-9_-]+", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"最近一次推荐列表里推荐|\b推荐\b", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"[（）()]", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized)
    sanitized = re.sub(r"\s*([，。；：,.!?])\s*", r"\1", sanitized)
    sanitized = re.sub(r";\s*。", "。", sanitized).strip(" ，,;；")
    return sanitized or "dialogue_only_response_requires_display_grounding"


def _outside_public_item_ids(text: str, allowed_ids: set[str]) -> set[str]:
    referenced = {match.group(1) for match in re.finditer(r"(?<![\w])(?:item_id|parent_asin|asin|商品ID|商品编号)\s*[:：=#-]?\s*([A-Za-z0-9][A-Za-z0-9_-]*)(?![\w])", text, re.IGNORECASE)}
    referenced.update(match.group(0) for match in re.finditer(r"(?<![A-Za-z0-9_])B[A-Z0-9]{9}(?![A-Za-z0-9_])", text))
    return {item_id for item_id in referenced if item_id not in allowed_ids}


def _turn_record(
    turn_index: int,
    action: RoleAction,
    display: dict[str, Any],
    assistant_message: str,
    *,
    user_message: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostics = diagnostics or {}
    display_item_ids = [str(item.get("parent_asin")) for item in display.get("items", []) if isinstance(item, dict) and item.get("parent_asin")]
    message = user_message or action.message or _feedback_user_message(action.action_type or action.type.value, action.item_id, action.comment)
    should_recommend = _should_recommend(diagnostics, display)
    if display_item_ids and should_recommend:
        strategy_name = "public_display_grounded_response"
        allowed_item_ids = display_item_ids
        selected = display_item_ids
        must_select = True
    else:
        strategy_name = "clarification_response" if diagnostics.get("agent_action") == "ask_clarifying_question" else "dialogue_only_response"
        allowed_item_ids = []
        selected = []
        must_select = False
    return {
        "turn_index": turn_index,
        "user_message": message,
        "assistant_message": assistant_message,
        "action_type": action.action_type or action.type.value,
        "display_item_ids": display_item_ids,
        "selected_item_ids": selected,
        "feedback_constraints": {},
        "target_action": {
            "strategy_name": strategy_name,
            "trigger_reason": action.action_type or action.type.value,
            "selected_item_ids": selected,
            "allowed_item_ids": allowed_item_ids,
            "must_select_from_candidates": must_select,
        },
        "target_explanation": str(display.get("assistant_message") or assistant_message),
        "tool_supervision": _tool_supervision(display, action, diagnostics),
    }


def _terminal_turn_record(
    turn_index: int,
    action: RoleAction,
    display: dict[str, Any],
    assistant_message: str,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    display_item_ids = _display_item_ids(display)
    selected = [action.item_id] if action.item_id and action.item_id in display_item_ids else []
    return {
        "turn_index": turn_index,
        "user_message": action.comment or _feedback_user_message(action.type.value, action.item_id, None),
        "assistant_message": assistant_message,
        "action_type": action.type.value,
        "display_item_ids": display_item_ids,
        "selected_item_ids": selected,
        "feedback_constraints": {},
        "target_action": {
            "strategy_name": "accept_displayed_item",
            "trigger_reason": "simulated_user_acceptance",
            "selected_item_ids": selected,
            "allowed_item_ids": display_item_ids,
            "must_select_from_candidates": True,
        },
        "target_explanation": action.comment or "The user accepted a displayed item.",
        "tool_supervision": _tool_supervision(display, action, diagnostics or {}),
    }


def _display_item_ids(display: dict[str, Any]) -> list[str]:
    return [str(item.get("parent_asin")) for item in display.get("items", []) if isinstance(item, dict) and item.get("parent_asin")]


def _role_action_from_payload(payload: dict[str, Any], display_response: dict[str, Any]) -> RoleAction:
    allowed_item_ids = {
        str(item.get("parent_asin"))
        for item in display_response.get("items", [])
        if isinstance(item, dict) and item.get("parent_asin")
    }
    action_type = str(payload.get("action_type") or "").strip().lower()
    item_id = str(payload.get("item_id") or "").strip() or None
    message = str(payload.get("message") or payload.get("intent") or "").strip()
    comment = str(payload.get("comment") or "").strip()
    if item_id is not None and item_id not in allowed_item_ids:
        raise ValueError(f"Model selected item outside display: {item_id}")
    if action_type == RoleActionType.CHAT.value:
        if not message:
            raise ValueError("SimulatedUserAgent chat action requires message")
        return RoleAction.chat(message)
    if action_type == RoleActionType.WHY.value:
        return RoleAction.why(item_id)
    if action_type in {RoleActionType.SHOW_DIFFERENT.value, "dislike"}:
        return RoleAction.feedback(action_type, item_id, comment)
    if action_type == RoleActionType.ACCEPT.value:
        if not allowed_item_ids:
            raise ValueError("SimulatedUserAgent accept action requires a displayed item")
        if item_id is None:
            raise ValueError("SimulatedUserAgent accept action requires item_id from display")
        return RoleAction.accept(item_id, comment or "This fits what I was trying to solve.")
    raise ValueError(f"Unsupported simulated user action_type: {action_type}")


def _simulated_user_messages(
    role: SimulatedCustomerRole,
    state: RoleState,
    history: list[dict[str, Any]],
    last_display: dict[str, Any],
    *,
    phase: str,
) -> list[dict[str, str]]:
    display_items = [_public_item(item) for item in last_display.get("items", []) if isinstance(item, dict)]
    context = {
        "phase": phase,
        "private_context": role.private_context,
        "visible_dialogue_history": _visible_dialogue(history),
        "last_display": {
            "assistant_message": last_display.get("assistant_message", ""),
            "items": display_items,
        },
        "state": {
            "seen_item_ids": sorted(state.seen_item_ids),
            "turns_observed": state.turns_observed,
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "You are SimulatedUserAgent in a recommender-system data generation run. "
                "Use only private_context, visible_dialogue_history, and last_display to produce the simulated customer's action. "
                "Do not assume knowledge of the hidden catalog, candidate pool, scores, labels, oracle targets, or unavailable parent_asin values. "
                "For initial_action, return JSON {\"action_type\": \"chat\", \"message\": string} with a natural first request; express the current need in your own words instead of reciting category or keyword lists. "
                "For next_action, return one JSON action with action_type in chat, why, show_different, dislike, accept; item_id may only be from last_display.items. "
                "Judge the dialogue by semantic progress, not exact trigger phrases: decide whether the assistant understood the need, answered a concern, adjusted after feedback, or still needs more context. "
                "Only accept after the assistant has given concrete, item-specific public reasons that would satisfy a real customer. "
                "If the recommendation is generic, too short, or does not explain why displayed products fit your need, ask why or request a clearer/different set instead."
            ),
        },
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]


def _public_persona_summary(persona: dict[str, Any]) -> dict[str, Any]:
    return {
        "persona": str(persona.get("persona") or "")[:300],
        "budget_sensitivity": str(persona.get("budget_sensitivity") or "")[:80],
        "decision_style": str(persona.get("decision_style") or "")[:80],
        "feedback_style": str(persona.get("feedback_style") or "")[:80],
    }


def _visible_dialogue(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "turn_index": turn.get("turn_index"),
            "user_message": turn.get("user_message", ""),
            "assistant_message": turn.get("assistant_message", ""),
            "display_item_ids": list(turn.get("display_item_ids", [])),
            "action_type": turn.get("action_type", ""),
        }
        for turn in history[-6:]
        if isinstance(turn, dict)
    ]


def _tool_supervision(display: dict[str, Any], action: RoleAction, diagnostics: dict[str, Any]) -> dict[str, Any]:
    agent_tool_events = _safe_tool_events(diagnostics.get("agent_tool_events", []))
    return {
        "conversation_intent": diagnostics.get("conversation_intent", ""),
        "agent_action": diagnostics.get("agent_action", ""),
        "should_recommend": _should_recommend(diagnostics, display),
        "expected_tool_calls": [event["tool_name"] for event in agent_tool_events if event.get("tool_name") and event.get("status") != "skipped"],
        "agent_tool_events": agent_tool_events,
        "tool_call_summary": _safe_tool_summary(diagnostics.get("agent_tool_summary", {}), agent_tool_events),
        "simulated_user_action": action.action_type or action.type.value,
    }


def _service_turn_diagnostics(service: RecommendationService, session_id: str) -> dict[str, Any]:
    try:
        session = service.get_agent_session(session_id)
    except Exception:
        return {}
    if not session.turns:
        return {}
    diagnostics = session.turns[-1].diagnostics
    return diagnostics if isinstance(diagnostics, dict) else {}


def _accept_terminal_diagnostics(*, recorded: bool = True) -> dict[str, Any]:
    status = "ok" if recorded else "error"
    return {
        "conversation_intent": "preference_feedback",
        "agent_action": "record_acceptance" if recorded else "acceptance_not_recorded",
        "should_recommend": False,
        "agent_tool_events": [
            {"tool_name": "record_user_feedback", "phase": "post_recommendation", "status": status},
        ],
        "agent_tool_summary": {"event_count": 1, "executed_count": 1 if recorded else 0, "skipped_count": 0, "error_count": 0 if recorded else 1},
    }


def _should_recommend(diagnostics: dict[str, Any], display: dict[str, Any]) -> bool:
    if "should_recommend" in diagnostics:
        return bool(diagnostics.get("should_recommend"))
    return bool(display.get("items"))


def _looks_like_recommendation_list(text: str) -> bool:
    lowered = text.lower()
    if len(re.findall(r"(?:^|\n)\s*(?:[-*]|\d+[.)]|[一二三四五六七八九十]+[、.])\s+", text)) >= 2:
        return True
    return bool(re.search(r"\b(?:recommend|try|consider)\b.*\b(?:item|product)\b|推荐.*(?:商品|产品|这几件|以下)", lowered, re.DOTALL))



def _safe_tool_events(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    safe_events: list[dict[str, Any]] = []
    for event in events[:8]:
        if not isinstance(event, dict):
            continue
        safe_events.append(
            {
                "tool_name": str(event.get("tool_name") or event.get("name") or ""),
                "phase": str(event.get("phase") or ""),
                "status": str(event.get("status") or ""),
            }
        )
    return safe_events


def _safe_tool_summary(summary: Any, events: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(summary, dict):
        summary = {}
    return {
        "event_count": int(summary.get("event_count", len(events)) or 0),
        "executed_count": int(summary.get("executed_count", len([event for event in events if event.get("status") not in {"", "skipped"}])) or 0),
        "skipped_count": int(summary.get("skipped_count", len([event for event in events if event.get("status") == "skipped"])) or 0),
        "error_count": int(summary.get("error_count", len([event for event in events if event.get("status") == "error"])) or 0),
    }


def _flatten_turn_samples(sample: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for turn in sample.get("dialogue", []):
        target_action = turn.get("target_action") if isinstance(turn.get("target_action"), dict) else {}
        tool_supervision = turn.get("tool_supervision") if isinstance(turn.get("tool_supervision"), dict) else {}
        if not bool(tool_supervision.get("should_recommend", False)):
            continue
        if target_action.get("strategy_name") != "public_display_grounded_response":
            continue
        if not target_action.get("allowed_item_ids"):
            continue
        candidate_summary = [{"item_id": item_id, "sources": ["display"], "category": ""} for item_id in turn.get("display_item_ids", [])]
        if not candidate_summary:
            continue
        records.append(
            {
                "schema_version": "rs_agent_sft_sample_v1",
                "sample": {
                    "user_input": turn["user_message"],
                    "assistant_response": turn["assistant_message"],
                    "feedback_constraints": turn.get("feedback_constraints", {}),
                    "candidate_summary": candidate_summary,
                    "target_action": turn["target_action"],
                    "target_explanation": turn.get("target_explanation", ""),
                },
                "metadata": {
                    "source_schema": MULTI_TURN_SFT_SCHEMA_VERSION,
                    "source_sample_id": sample.get("sample_id"),
                    "turn_index": turn.get("turn_index"),
                    "tool_supervision": turn.get("tool_supervision", {}),
                },
            }
        )
    return records


def _flatten_turn_sample_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    dialogue_turn_count = sum(len(sample.get("dialogue", [])) for sample in samples)
    flattened_turn_count = sum(len(_flatten_turn_samples(sample)) for sample in samples)
    return {
        "flat_artifact_contract": "display_only",
        "dialogue_turn_samples_total": dialogue_turn_count,
        "flattened_turn_samples": flattened_turn_count,
        "dropped_no_display_turn_samples": max(0, dialogue_turn_count - flattened_turn_count),
    }


def _sample_mid_high_users(sequences_by_user: dict[str, dict[str, Any]], target_samples: int, rng: random.Random) -> list[tuple[str, str, dict[str, Any]]]:
    candidates = [
        (user_id, sequence, _history_count(sequence))
        for user_id, sequence in sequences_by_user.items()
        if user_id and _history_count(sequence) >= 2
    ]
    if not candidates:
        raise ValueError("no eligible user sequences found")
    counts = sorted(count for _, _, count in candidates)
    warm_cut = counts[max(0, int(len(counts) * 0.5) - 1)]
    hot_cut = counts[max(0, int(len(counts) * 0.8) - 1)]
    mid_high = [
        (user_id, "hot" if count >= hot_cut else "warm", sequence)
        for user_id, sequence, count in candidates
        if count >= warm_cut
    ]
    rng.shuffle(mid_high)
    if len(mid_high) >= target_samples:
        return mid_high[:target_samples]
    repeated: list[tuple[str, str, dict[str, Any]]] = []
    while len(repeated) < target_samples:
        repeated.extend(mid_high)
    return repeated[:target_samples]


def _history_evidence(sequence: dict[str, Any], item_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    item_ids = [str(item_id) for item_id in sequence.get("recent_positive_item_sequence") or sequence.get("recent_item_sequence") or [] if item_id]
    recent_ids = item_ids[-20:]
    categories: Counter[str] = Counter()
    keywords: Counter[str] = Counter()
    titles: list[str] = []
    item_summaries: list[dict[str, Any]] = []
    for item_id in recent_ids:
        metadata = item_metadata.get(item_id, {})
        category = str(metadata.get("main_category") or metadata.get("category") or "").strip()
        if category:
            categories[category] += 1
        title = str(metadata.get("title_clean") or metadata.get("title") or "").strip()
        summary = str(metadata.get("summary") or metadata.get("description") or "").strip()
        if title:
            titles.append(title[:120])
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", title.lower()):
                if token not in {"the", "and", "with", "for", "from", "pack", "case", "new"}:
                    keywords[token] += 1
        if title or category or summary:
            item_summaries.append(
                {
                    "item_id": item_id,
                    "title": title[:120],
                    "category": category,
                    "short_description": summary[:180] if summary else title[:120],
                }
            )
    return {
        "history_count": _history_count(sequence),
        "recent_item_ids_sample": recent_ids[-10:],
        "top_categories": [category for category, _ in categories.most_common(5)],
        "top_keywords": [keyword for keyword, _ in keywords.most_common(8)],
        "recent_titles_sample": titles[-5:],
        "recent_item_summaries": item_summaries[-8:],
        "derived_from": "train_history_only",
    }


def _deterministic_persona(user_id: str, segment: str, sequence: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    categories = evidence.get("top_categories") or ["Electronics"]
    keywords = evidence.get("top_keywords") or ["quality", "reliable"]
    past_interactions_summary = _past_interactions_summary(evidence)
    return {
        "schema_version": "simulated_persona_v1",
        "user_id": user_id,
        "segment": segment,
        "persona_id": f"persona-{user_id[:8]}",
        "persona": f"A {segment} historical shopper with {evidence.get('history_count', 0)} train-history interactions.",
        "shopping_goal": "Let the simulated customer decide a current shopping need from persona and past history.",
        "initial_request": _deterministic_initial_request(categories, keywords),
        "budget_sensitivity": "medium",
        "category_preferences": categories[:4],
        "keyword_preferences": keywords[:6],
        "negative_preferences": [],
        "decision_style": "cautious" if segment == "warm" else "balanced",
        "feedback_style": "exploratory" if segment == "warm" else "direct",
        "memory": [f"Recent train-history contains {int(evidence.get('history_count', 0) or 0)} interactions."],
        "past_interactions_summary": past_interactions_summary,
        "evidence_summary": {"derived_from": "train_history_only", "history_count": _history_count(sequence)},
    }


def _sanitize_persona_payload(user_id: str, segment: str, sequence: dict[str, Any], evidence: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    base = _deterministic_persona(user_id, segment, sequence, evidence)
    result = {**base}
    for key in ["persona", "shopping_goal", "initial_request", "budget_sensitivity", "decision_style", "feedback_style"]:
        if str(payload.get(key) or "").strip():
            result[key] = str(payload[key]).strip()[:600]
    for key in ["category_preferences", "keyword_preferences", "negative_preferences", "memory"]:
        values = payload.get(key)
        if isinstance(values, list):
            result[key] = [str(value).strip()[:80] for value in values if str(value).strip()][:8]
    result["initial_request"] = _clean_initial_request(str(result.get("initial_request", "")))
    if isinstance(payload.get("past_interactions_summary"), dict):
        result["past_interactions_summary"] = _sanitize_past_interactions_summary(payload["past_interactions_summary"], evidence)
    result["evidence_summary"] = {"derived_from": "train_history_only", "history_count": _history_count(sequence)}
    return result


def _past_interactions_summary(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "history_count": evidence.get("history_count", 0),
        "recent_categories": list(evidence.get("top_categories") or [])[:5],
        "recent_item_summaries": [_private_history_summary(item) for item in list(evidence.get("recent_item_summaries") or [])[:8]],
        "inferred_preferences": [
            f"Often interacts with {category}." for category in list(evidence.get("top_categories") or [])[:3]
        ]
        + [f"Shows interest in {keyword}." for keyword in list(evidence.get("top_keywords") or [])[:4]],
        "derived_from": "train_history_only",
    }


def _private_history_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(item.get("title") or "").strip()[:120],
        "category": str(item.get("category") or "").strip()[:80],
        "short_description": str(item.get("short_description") or "").strip()[:180],
    }


def _sanitize_past_interactions_summary(payload: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    base = _past_interactions_summary(evidence)
    result = {**base}
    for key in ["recent_categories", "inferred_preferences"]:
        values = payload.get(key)
        if isinstance(values, list):
            result[key] = [str(value).strip()[:160] for value in values if str(value).strip()][:8]
    values = payload.get("recent_item_summaries")
    if isinstance(values, list):
        summaries: list[dict[str, Any]] = []
        for value in values[:8]:
            if isinstance(value, dict):
                summaries.append(
                    {
                        "title": str(value.get("title") or "").strip()[:120],
                        "category": str(value.get("category") or "").strip()[:80],
                        "short_description": str(value.get("short_description") or value.get("description") or "").strip()[:180],
                    }
                )
            elif str(value).strip():
                summaries.append({"title": str(value).strip()[:120], "category": "", "short_description": str(value).strip()[:180]})
        if summaries:
            result["recent_item_summaries"] = summaries
    result["derived_from"] = "train_history_only"
    return result


def _deterministic_initial_request(categories: list[str], keywords: list[str]) -> str:
    need = _current_need_seed(categories, keywords)
    return f"I'm looking for {need}, but I am not sure what exact product to choose. Can you suggest a few good options?"


def _clean_initial_request(message: str) -> str:
    cleaned = re.sub(r"Prefer categories?:[^.?!]*(?:[.?!]|$)", "", message, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"Prefer features?:[^.?!]*(?:[.?!]|$)", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"parent_asin\s*[:=]?\s*[A-Za-z0-9_-]+", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or "I'm looking for something practical, but I am not sure what exact product to choose. Can you suggest a few good options?"


def _current_need_seed(categories: list[str], keywords: list[str]) -> str:
    text = " ".join([*categories[:3], *keywords[:5]]).lower()
    if any(token in text for token in ["office", "desk", "card", "holder", "paper"]):
        return "something practical to organize my workspace or handle everyday office tasks"
    if any(token in text for token in ["computer", "electronics", "cable", "usb", "charger"]):
        return "a practical electronics or computer accessory for daily use"
    if any(token in text for token in ["audio", "speaker", "headphone", "earbud", "bluetooth"]):
        return "something useful for listening or commuting"
    if any(token in text for token in ["kitchen", "home", "storage"]):
        return "a practical home item that makes daily routines easier"
    return "something practical for my current needs"


def _natural_join(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return ", ".join(cleaned[:-1]) + f" and {cleaned[-1]}"


def _role_from_persona(persona: dict[str, Any]) -> SimulatedCustomerRole:
    return SimulatedCustomerRole(
        role_id=str(persona.get("persona_id") or persona.get("user_id") or uuid4()),
        persona=str(persona.get("persona") or "Historical shopper"),
        shopping_goal=str(persona.get("shopping_goal") or "Recommend useful products."),
        budget_sensitivity=str(persona.get("budget_sensitivity") or "medium"),
        category_preferences=tuple(str(value) for value in persona.get("category_preferences", []) if str(value)),
        keyword_preferences=tuple(str(value) for value in persona.get("keyword_preferences", []) if str(value)),
        negative_preferences=tuple(str(value) for value in persona.get("negative_preferences", []) if str(value)),
        decision_style=str(persona.get("decision_style") or "balanced"),
        feedback_style=str(persona.get("feedback_style") or "direct"),
        memory=tuple(str(value) for value in persona.get("memory", []) if str(value)),
        initial_request=str(persona.get("initial_request") or "").strip(),
        private_context={
            "persona": {
                "persona": persona.get("persona"),
                "shopping_goal": persona.get("shopping_goal"),
                "budget_sensitivity": persona.get("budget_sensitivity"),
                "decision_style": persona.get("decision_style"),
                "feedback_style": persona.get("feedback_style"),
            },
            "past_interactions_summary": persona.get("past_interactions_summary", {}),
            "simulation_instruction": (
                "You are this customer. Use your persona and past interaction summary to decide what you want now. "
                "Do not assume you know what exists in the recommender catalog."
            ),
        },
    )


def _manifest(
    *,
    config_path: str,
    output_path: Path,
    flat_output_path: Path,
    rejects_path: Path,
    target_samples: int,
    samples: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
    model_config: dict[str, Any],
    dry_run: bool,
    execute: bool,
) -> dict[str, Any]:
    turn_counts = [len(sample.get("dialogue", [])) for sample in samples]
    flatten_stats = _flatten_turn_sample_stats(samples)
    return {
        "schema_version": MULTI_TURN_RUN_SCHEMA_VERSION,
        "config_path": config_path,
        "dry_run": dry_run,
        "execute": execute,
        "target_samples": target_samples,
        "generated_count": len(samples),
        "rejected_count": len(rejects),
        "output_path": str(output_path),
        "flat_output_path": str(flat_output_path),
        "rejects_path": str(rejects_path),
        "model": {
            "provider": "openai_compatible",
            "model": model_config.get("model"),
            "api_base": model_config.get("api_base"),
            "api_key_env": model_config.get("api_key_env"),
        },
        "quality_summary": {
            "avg_dialogue_turn_count": round(sum(turn_counts) / len(turn_counts), 4) if turn_counts else 0.0,
            "min_dialogue_turn_count": min(turn_counts) if turn_counts else 0,
            "max_dialogue_turn_count": max(turn_counts) if turn_counts else 0,
            **flatten_stats,
            "reject_reasons": dict(Counter(reject.get("reason") for reject in rejects)),
        },
        "leakage_policy": {
            "train_history_only": True,
            "no_label_in_candidate_generation": True,
            "no_oracle_candidate_injection": True,
        },
    }


def _write_partial_outputs(
    output_path: Path,
    flat_output_path: Path,
    rejects_path: Path,
    samples: list[dict[str, Any]],
    flat_samples: list[dict[str, Any]],
    rejects: list[dict[str, Any]],
) -> None:
    write_jsonl(output_path, samples)
    write_jsonl(flat_output_path, flat_samples)
    write_jsonl(rejects_path, rejects)


def _sample_preview(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id"),
        "user_id": sample.get("user_id"),
        "segment": sample.get("segment"),
        "dialogue_turn_count": len(sample.get("dialogue", [])),
        "first_turn": sample.get("dialogue", [{}])[0],
        "simulator_private_context": sample.get("simulator_private_context", {}),
    }


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "parent_asin": item.get("parent_asin"),
        "title": item.get("title"),
        "category": item.get("category"),
        "summary": item.get("summary"),
        "description": item.get("description"),
        "features": item.get("features", []),
        "price": item.get("price"),
    }


def _feedback_user_message(action_type: str, item_id: str | None, comment: str | None) -> str:
    if comment:
        return comment
    if action_type in {"why", "show_different", "dislike", "accept"}:
        parts = ["simulated_user_feedback", f"action={action_type}"]
        if item_id:
            parts.append(f"item_id={item_id}")
        return "; ".join(parts)
    return action_type


def _history_count(sequence: dict[str, Any]) -> int:
    for key in ("sequence_len", "positive_sequence_len", "history_count"):
        if sequence.get(key) is not None:
            try:
                return int(sequence[key])
            except (TypeError, ValueError):
                pass
    return len(sequence.get("recent_item_sequence") or [])


def _load_multi_turn_config(path: str | Path) -> dict[str, Any]:
    _load_local_env_files()
    config = load_config(_project_path(path))
    config.setdefault("generation", {})
    config.setdefault("model", {})
    config["model"]["model"] = os.environ.get("RS_AGENT_GPT_SFT_MODEL", config["model"].get("model", "gpt-5.3-codex-spark"))
    config["model"]["api_base"] = os.environ.get("RS_AGENT_GPT_SFT_API_BASE", config["model"].get("api_base", "https://cpa2api.sinrotic233.com"))
    config["model"].setdefault("api_key_env", "RS_agent")
    if not str(config["model"].get("api_base", "")).startswith("https://"):
        raise ValueError("multi-turn SFT api_base must use https")
    return config


def _openai_client(model_config: dict[str, Any]) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=str(model_config.get("api_base") or "https://cpa2api.sinrotic233.com"),
        api_key_env=str(model_config.get("api_key_env") or "RS_agent"),
        timeout_seconds=float(model_config.get("timeout_seconds", 60)),
    )


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise ValueError("model response must be a JSON object")
    return payload


def _contains_forbidden_public_keys(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_PUBLIC_KEYS:
                return True
            if _contains_forbidden_public_keys(child):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_public_keys(item) for item in value)
    return False


def _assert_no_forbidden_public_keys(value: Any) -> None:
    if _contains_forbidden_public_keys(value):
        raise ValueError("sample turn contains forbidden public/internal keys")


def _load_local_env_files() -> None:
    """Load local SFT secrets without importing serving/deploy env defaults."""
    for env_path in (Path(".env.local"), Path(".env")):
        path = _project_path(env_path)
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parents[3] / candidate
