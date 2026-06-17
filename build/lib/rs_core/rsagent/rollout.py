from __future__ import annotations

from typing import Any

from rs_core.display import build_display_record
from rs_core.rsagent.schema import AgentSession, AgentTurn

SCHEMA_VERSION = "rs_agent_rollout_v1"
TRAINING_STATUS = "deferred_environment_reward_only"
MODEL_ROUTE = "qwen3.5-4b-8bit-qlora-grpo"


def turn_to_rollout_record(turn: AgentTurn, session: AgentSession, user_sequence: dict[str, Any] | None = None) -> dict[str, Any]:
    inference_policy = turn.diagnostics.get("inference_policy", {})
    prompt_context = {
        "user_sequence": user_sequence or {},
        "feedback_constraints": turn.feedback_constraints.to_dict(),
        "prior_turn_items": _prior_items_before_turn(session, turn.turn_index),
    }
    policy_type = str(inference_policy.get("policy_type", "deterministic_baseline"))
    reward_evidence = turn.reward_evidence.to_dict()
    reward = turn.reward.to_dict() if turn.reward else None
    return {
        "schema_version": SCHEMA_VERSION,
        "training_status": TRAINING_STATUS,
        "session_id": session.session_id,
        "user_id": session.user_id,
        "turn_index": turn.turn_index,
        "prompt_context": prompt_context,
        "policy_type": policy_type,
        "agent_decision": turn.recommendation.to_dict(),
        "display_response": build_display_record(turn, session),
        "ranking": turn.ranking,
        "candidates": turn.candidates,
        "diagnostics": turn.diagnostics,
        "reward_evidence": reward_evidence,
        "reward": reward,
        "training_samples": _training_samples(turn, prompt_context, policy_type, reward, reward_evidence),
        "metadata": _record_metadata(turn, inference_policy),
    }


def session_to_rollout_records(session: AgentSession, user_sequence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [turn_to_rollout_record(turn, session, user_sequence) for turn in session.turns]


def _record_metadata(turn: AgentTurn, inference_policy: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "model_route": MODEL_ROUTE,
        "training_deferred": True,
        "inference_policy_enabled": bool(inference_policy.get("enabled", False)),
        "inference_policy_fallback_used": bool(inference_policy.get("fallback_used", False)),
        "inference_policy_route": inference_policy.get("route", "disabled"),
        "model_id": inference_policy.get("model_id"),
    }
    if turn.rag_context is not None:
        metadata["rag_context"] = turn.rag_context
    return metadata


def _training_samples(
    turn: AgentTurn,
    prompt_context: dict[str, Any],
    policy_type: str,
    reward: dict[str, Any] | None,
    reward_evidence: dict[str, Any],
) -> dict[str, Any]:
    final_items = turn.recommendation.final_items
    allowed_item_ids = _unique_item_ids(turn.candidates)
    return {
        "sft_sample": {
            "user_input": turn.user_input,
            "assistant_response": turn.assistant_response or turn.recommendation.agent_explanation,
            "feedback_constraints": prompt_context["feedback_constraints"],
            "candidate_summary": _candidate_summary(turn.candidates),
            "target_action": {
                "strategy_name": turn.recommendation.strategy_name,
                "trigger_reason": turn.recommendation.trigger_reason,
                "selected_item_ids": [str(item.get("parent_asin")) for item in final_items if item.get("parent_asin")],
                "allowed_item_ids": allowed_item_ids,
                "must_select_from_candidates": True,
            },
            "target_explanation": turn.recommendation.agent_explanation,
        },
        "reward_sample": {
            "policy_type": policy_type,
            "reward": reward,
            "reward_evidence": reward_evidence,
            "feedback_effect_observed": reward_evidence.get("feedback_constraints_satisfied", {}).get("feedback_effect_observed"),
            "risk_flags": list(turn.recommendation.risk_flags),
        },
    }


def _candidate_summary(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "item_id": str(candidate.get("item_id") or candidate.get("parent_asin")),
            "sources": list(candidate.get("sources", [])),
            "category": candidate.get("category", ""),
        }
        for candidate in candidates
    ]


def _unique_item_ids(candidates: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    item_ids: list[str] = []
    for candidate in candidates:
        item_id = str(candidate.get("item_id") or candidate.get("parent_asin") or "")
        if item_id and item_id not in seen:
            seen.add(item_id)
            item_ids.append(item_id)
    return item_ids


def _prior_items_before_turn(session: AgentSession, turn_index: int) -> list[str]:
    items: list[str] = []
    for turn in session.turns:
        if turn.turn_index >= turn_index:
            break
        items.extend(str(item.get("parent_asin")) for item in turn.ranking if item.get("parent_asin"))
    return sorted(set(items))
