from __future__ import annotations

from copy import deepcopy
from typing import Any

SFT_SAMPLE_SCHEMA_VERSION = "rs_agent_sft_sample_v1"
GRPO_SAMPLE_SCHEMA_VERSION = "rs_agent_grpo_sample_v1"


def synthetic_sft_samples() -> list[dict[str, Any]]:
    """Return tiny in-memory SFT samples that mirror rollout.training_samples.sft_sample."""
    return [
        {
            "schema_version": SFT_SAMPLE_SCHEMA_VERSION,
            "sample": {
                "user_input": "I want portable audio options and dislike wired accessories.",
                "assistant_response": "Here are portable audio products selected from the candidate pool.",
                "feedback_constraints": {
                    "disliked_item_ids": ["wired_1"],
                    "disliked_categories": ["Accessories"],
                    "preferred_categories": {"Audio": 1.0},
                    "preferred_sources": {"itemcf_weak": 1.0},
                    "filter_prior_turn_items": True,
                },
                "candidate_summary": [
                    {"item_id": "speaker_1", "sources": ["itemcf_weak", "semantic"], "category": "Audio"},
                    {"item_id": "wired_1", "sources": ["popular"], "category": "Accessories"},
                ],
                "target_action": {
                    "strategy_name": "feedback_aware_rerank",
                    "trigger_reason": "ranked_hybrid_candidates_available",
                    "selected_item_ids": ["speaker_1"],
                    "allowed_item_ids": ["speaker_1", "wired_1"],
                    "must_select_from_candidates": True,
                },
                "target_explanation": "Selected an Audio candidate from itemcf_weak while respecting feedback.",
            },
        }
    ]


def synthetic_grpo_samples() -> list[dict[str, Any]]:
    """Return tiny in-memory GRPO samples with rollout reward context only."""
    return [
        {
            "schema_version": GRPO_SAMPLE_SCHEMA_VERSION,
            "prompt": "User prefers Audio and asks to avoid prior wired accessories. Select from candidates.",
            "completion": "speaker_1",
            "reward_sample": {
                "policy_type": "deterministic_baseline",
                "reward": {
                    "total": 0.7,
                    "recommendation_quality": 0.0,
                    "feedback_alignment": 0.3,
                    "explanation_faithfulness": 0.2,
                    "risk_penalty": 0.0,
                },
                "reward_evidence": {
                    "holdout_hits": [],
                    "feedback_constraints_satisfied": {
                        "disliked_item_ids": True,
                        "disliked_categories": True,
                        "preferred_represented": True,
                        "prior_turn_filter": True,
                        "feedback_effect_observed": True,
                    },
                    "unsupported_explanation_claims": [],
                    "risk_flags": [],
                },
                "feedback_effect_observed": True,
                "risk_flags": [],
            },
            "target_action": {
                "selected_item_ids": ["speaker_1"],
                "allowed_item_ids": ["speaker_1", "wired_1"],
                "must_select_from_candidates": True,
            },
        }
    ]


def validate_sft_sample(record: dict[str, Any]) -> None:
    if record.get("schema_version") != SFT_SAMPLE_SCHEMA_VERSION:
        raise ValueError(f"SFT sample schema_version must be {SFT_SAMPLE_SCHEMA_VERSION}")
    sample = _as_dict(record.get("sample"))
    required = ["user_input", "assistant_response", "feedback_constraints", "candidate_summary", "target_action", "target_explanation"]
    missing = [key for key in required if key not in sample]
    if missing:
        raise ValueError(f"SFT sample missing required keys: {missing}")
    if not str(sample.get("user_input", "")).strip():
        raise ValueError("SFT sample user_input is required")
    target_action = _as_dict(sample.get("target_action"))
    _validate_target_action(target_action)
    candidate_ids = {str(candidate.get("item_id")) for candidate in _as_list(sample.get("candidate_summary")) if candidate.get("item_id")}
    if target_action.get("must_select_from_candidates") and not set(target_action["selected_item_ids"]) <= candidate_ids:
        raise ValueError("SFT selected_item_ids must be present in candidate_summary when constrained")


def validate_grpo_sample(record: dict[str, Any]) -> None:
    if record.get("schema_version") != GRPO_SAMPLE_SCHEMA_VERSION:
        raise ValueError(f"GRPO sample schema_version must be {GRPO_SAMPLE_SCHEMA_VERSION}")
    if not str(record.get("prompt", "")).strip():
        raise ValueError("GRPO sample prompt is required")
    if "completion" not in record:
        raise ValueError("GRPO sample completion is required")
    _validate_target_action(_as_dict(record.get("target_action")))
    reward_sample = _as_dict(record.get("reward_sample"))
    if not reward_sample:
        raise ValueError("GRPO sample reward_sample is required")


def validate_sft_samples(records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError("SFT samples must not be empty")
    for record in records:
        validate_sft_sample(record)


def validate_grpo_samples(records: list[dict[str, Any]]) -> None:
    if not records:
        raise ValueError("GRPO samples must not be empty")
    for record in records:
        validate_grpo_sample(record)


def sft_messages_from_sample(record: dict[str, Any]) -> list[dict[str, str]]:
    validate_sft_sample(record)
    sample = deepcopy(record["sample"])
    return [
        {"role": "user", "content": str(sample["user_input"])},
        {"role": "assistant", "content": str(sample["assistant_response"])},
    ]


def _validate_target_action(target_action: dict[str, Any]) -> None:
    selected = [str(item_id) for item_id in _as_list(target_action.get("selected_item_ids")) if str(item_id)]
    allowed = [str(item_id) for item_id in _as_list(target_action.get("allowed_item_ids")) if str(item_id)]
    if not allowed:
        raise ValueError("target_action.allowed_item_ids must not be empty")
    if target_action.get("must_select_from_candidates", False) and not set(selected) <= set(allowed):
        raise ValueError("target_action.selected_item_ids must be a subset of allowed_item_ids")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
