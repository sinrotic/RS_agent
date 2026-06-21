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
from rs_core.serving.service import RecommendationService
from rs_core.simulation.policy import ModelDrivenRolePolicy, RolePolicy
from rs_core.simulation.schema import RoleAction, RoleActionType, RoleState, SimulatedCustomerRole

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
        if self.adapter is None:
            return original, {"mode": "deterministic_display_message", "api_called": False}
        display_items = [_public_item(item) for item in display.get("items", []) if isinstance(item, dict)]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the recommendation agent in a recommender-system SFT data generation run. "
                    "Rewrite the assistant response as natural, concise dialogue grounded only in the displayed items. "
                    "Do not reveal hidden tools, scores, diagnostics, raw RAG evidence, or internal traces. "
                    "Return JSON: {\"assistant_message\": string}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "persona": persona,
                        "latest_user_message": user_message,
                        "service_assistant_message": original,
                        "display_items": display_items,
                        "recent_dialogue": history[-4:],
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


class PersonaBuilder:
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
                    "You summarize a simulated shopping persona from train-history-only evidence. "
                    "Do not invent brands, labels, future positives, or evaluation targets. "
                    "Return JSON with keys: persona, shopping_goal, budget_sensitivity, category_preferences, "
                    "keyword_preferences, negative_preferences, decision_style, feedback_style, memory."
                ),
            },
            {"role": "user", "content": json.dumps({"base_persona": base, "history_evidence": evidence}, ensure_ascii=False)},
        ]
        payload = _parse_json_object(self.adapter.complete(messages))
        persona = _sanitize_persona_payload(user_id, segment, sequence, evidence, payload)
        return _role_from_persona(persona), persona


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
    service = RecommendationService(
        config=generation.get("service_config") or DEFAULT_SERVICE_CONFIG,
        limit_users=limit_users,
    )
    client = _openai_client(model_config) if execute else None
    adapter = (
        OpenAICompletionAdapter(
            client=client,
            model=str(model_config.get("model") or "gpt5.3codexspark"),
            temperature=float(model_config.get("temperature", 0.4)),
            max_tokens=int(model_config.get("max_tokens", 1200)),
            response_format=dict(model_config.get("response_format") or {"type": "json_object"}),
        )
        if client is not None
        else None
    )
    persona_builder = PersonaBuilder(adapter if execute else None)
    user_policy = ModelDrivenRolePolicy(adapter, fallback_policy=RolePolicy(), strict=bool(generation.get("strict_model_policy", False))) if execute else RolePolicy()
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
                policy=user_policy,
                recommendation_composer=recommendation_composer,
                model_name=str(model_config.get("model") or "gpt5.3codexspark"),
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
        allowed_ids = set(turn.get("target_action", {}).get("allowed_item_ids", []))
        if selected_ids and not selected_ids <= display_ids:
            raise ValueError("selected_item_ids must be a subset of display_item_ids")
        if selected_ids and allowed_ids and not selected_ids <= allowed_ids:
            raise ValueError("selected_item_ids must be a subset of target_action.allowed_item_ids")
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
    policy: Any,
    recommendation_composer: RecommendationAgentComposer,
    model_name: str,
    execute: bool,
) -> dict[str, Any]:
    state = RoleState()
    session_id = service.start_session(user_id=user_id)
    dialogue: list[dict[str, Any]] = []
    composer_metadata: list[dict[str, Any]] = []
    first_action = RoleAction.chat(role.initial_prompt())
    result = service.chat(session_id, first_action.message)
    assistant_message, metadata = recommendation_composer.compose(persona=persona, user_message=first_action.message, display=result.display, history=dialogue)
    composer_metadata.append(metadata)
    dialogue.append(_turn_record(1, first_action, result.display, assistant_message))
    final_action = first_action

    for turn_index in range(2, max(2, max_turns) + 1):
        next_action = policy.next_action(role, state, result.display)
        final_action = next_action
        if next_action.type == RoleActionType.ACCEPT:
            if turn_index >= min_turns:
                dialogue.append(_terminal_turn_record(turn_index, next_action, result.display, "用户接受了当前推荐。"))
                break
            next_action = RoleAction.why(next_action.item_id)
        if next_action.type == RoleActionType.CHAT:
            result = service.chat(session_id, next_action.message)
            user_message = next_action.message
        else:
            action_type = next_action.action_type or next_action.type.value
            result = service.feedback(session_id, action_type, next_action.item_id, next_action.comment)
            user_message = _feedback_user_message(action_type, next_action.item_id, next_action.comment)
        assistant_message, metadata = recommendation_composer.compose(persona=persona, user_message=user_message, display=result.display, history=dialogue)
        composer_metadata.append(metadata)
        dialogue.append(_turn_record(turn_index, next_action, result.display, assistant_message, user_message=user_message))

    session_export = service.feedback_session_facade.export_session(session_id)
    display_ids_union = sorted({item_id for turn in dialogue for item_id in turn.get("display_item_ids", [])})
    return {
        "schema_version": MULTI_TURN_SFT_SCHEMA_VERSION,
        "sample_id": f"multi-turn-{sample_index:05d}-{uuid4().hex[:8]}",
        "user_id": user_id,
        "segment": persona.get("segment", "unknown"),
        "persona": persona,
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
            "forbidden_eval_fields_present": _contains_forbidden_public_keys({"dialogue": dialogue, "session": session_export}),
        },
        "metadata": {
            "recommendation_agent_model": model_name if execute else "deterministic_display_message",
            "simulated_user_agent_model": model_name if execute else "deterministic_role_policy",
            "service_config_path": service.env.config_path,
            "composer_metadata": composer_metadata,
        },
    }


def _turn_record(turn_index: int, action: RoleAction, display: dict[str, Any], assistant_message: str, *, user_message: str | None = None) -> dict[str, Any]:
    display_item_ids = [str(item.get("parent_asin")) for item in display.get("items", []) if isinstance(item, dict) and item.get("parent_asin")]
    selected = [action.item_id] if action.item_id and action.item_id in display_item_ids else []
    message = user_message or action.message or _feedback_user_message(action.action_type or action.type.value, action.item_id, action.comment)
    return {
        "turn_index": turn_index,
        "user_message": message,
        "assistant_message": assistant_message,
        "action_type": action.action_type or action.type.value,
        "display_item_ids": display_item_ids,
        "selected_item_ids": selected,
        "feedback_constraints": {},
        "target_action": {
            "strategy_name": "public_display_grounded_response",
            "trigger_reason": action.action_type or action.type.value,
            "selected_item_ids": selected,
            "allowed_item_ids": display_item_ids,
            "must_select_from_candidates": True,
        },
        "target_explanation": str(display.get("assistant_message") or assistant_message),
    }


def _terminal_turn_record(turn_index: int, action: RoleAction, display: dict[str, Any], assistant_message: str) -> dict[str, Any]:
    display_item_ids = [str(item.get("parent_asin")) for item in display.get("items", []) if isinstance(item, dict) and item.get("parent_asin")]
    selected = [action.item_id] if action.item_id and action.item_id in display_item_ids else []
    return {
        "turn_index": turn_index,
        "user_message": action.comment or "I will take this recommendation.",
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
    }


def _flatten_turn_samples(sample: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for turn in sample.get("dialogue", []):
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
                "metadata": {"source_schema": MULTI_TURN_SFT_SCHEMA_VERSION, "source_sample_id": sample.get("sample_id"), "turn_index": turn.get("turn_index")},
            }
        )
    return records


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
    for item_id in recent_ids:
        metadata = item_metadata.get(item_id, {})
        category = str(metadata.get("main_category") or metadata.get("category") or "").strip()
        if category:
            categories[category] += 1
        title = str(metadata.get("title_clean") or metadata.get("title") or "").strip()
        if title:
            titles.append(title[:120])
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", title.lower()):
                if token not in {"the", "and", "with", "for", "from", "pack", "case", "new"}:
                    keywords[token] += 1
    return {
        "history_count": _history_count(sequence),
        "recent_item_ids_sample": recent_ids[-10:],
        "top_categories": [category for category, _ in categories.most_common(5)],
        "top_keywords": [keyword for keyword, _ in keywords.most_common(8)],
        "recent_titles_sample": titles[-5:],
        "derived_from": "train_history_only",
    }


def _deterministic_persona(user_id: str, segment: str, sequence: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    categories = evidence.get("top_categories") or ["Electronics"]
    keywords = evidence.get("top_keywords") or ["quality", "reliable"]
    return {
        "schema_version": "simulated_persona_v1",
        "user_id": user_id,
        "segment": segment,
        "persona_id": f"persona-{user_id[:8]}",
        "persona": f"A {segment} historical shopper with {evidence.get('history_count', 0)} train-history interactions.",
        "shopping_goal": f"Recommend practical products related to {', '.join(categories[:2])} with attention to {', '.join(keywords[:3])}.",
        "budget_sensitivity": "medium",
        "category_preferences": categories[:4],
        "keyword_preferences": keywords[:6],
        "negative_preferences": [],
        "decision_style": "cautious" if segment == "warm" else "balanced",
        "feedback_style": "exploratory" if segment == "warm" else "direct",
        "memory": [f"Recent train-history items include {', '.join(evidence.get('recent_item_ids_sample', [])[:5])}."],
        "evidence_summary": {"derived_from": "train_history_only", "history_count": _history_count(sequence)},
    }


def _sanitize_persona_payload(user_id: str, segment: str, sequence: dict[str, Any], evidence: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    base = _deterministic_persona(user_id, segment, sequence, evidence)
    result = {**base}
    for key in ["persona", "shopping_goal", "budget_sensitivity", "decision_style", "feedback_style"]:
        if str(payload.get(key) or "").strip():
            result[key] = str(payload[key]).strip()[:600]
    for key in ["category_preferences", "keyword_preferences", "negative_preferences", "memory"]:
        values = payload.get(key)
        if isinstance(values, list):
            result[key] = [str(value).strip()[:80] for value in values if str(value).strip()][:8]
    result["evidence_summary"] = {"derived_from": "train_history_only", "history_count": _history_count(sequence)}
    return result


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
            "flattened_turn_samples": sum(len(_flatten_turn_samples(sample)) for sample in samples),
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
    }


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "parent_asin": item.get("parent_asin"),
        "title": item.get("title"),
        "category": item.get("category"),
        "summary": item.get("summary"),
        "price": item.get("price"),
    }


def _feedback_user_message(action_type: str, item_id: str | None, comment: str | None) -> str:
    if action_type == "why":
        return f"Why did you recommend {item_id}?" if item_id else "Why did you recommend this?"
    if action_type == "show_different":
        return comment or "Show me something different."
    if action_type == "dislike":
        return comment or f"I do not like {item_id or 'this item'}."
    return comment or action_type


def _history_count(sequence: dict[str, Any]) -> int:
    for key in ("sequence_len", "positive_sequence_len", "history_count"):
        if sequence.get(key) is not None:
            try:
                return int(sequence[key])
            except (TypeError, ValueError):
                pass
    return len(sequence.get("recent_item_sequence") or [])


def _load_multi_turn_config(path: str | Path) -> dict[str, Any]:
    config = load_config(_project_path(path))
    config.setdefault("generation", {})
    config.setdefault("model", {})
    config["model"]["model"] = os.environ.get("RS_AGENT_GPT_SFT_MODEL", config["model"].get("model", "gpt5.3codexspark"))
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


def _project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return Path(__file__).resolve().parents[2] / candidate
