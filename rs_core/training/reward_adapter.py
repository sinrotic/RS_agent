from __future__ import annotations

import json
from typing import Any


def compute_grpo_reward(sample: dict[str, Any], completion: str | None = None) -> float:
    """Convert an rs_agent reward_sample-style record into a scalar GRPO reward."""
    reward_sample = sample.get("reward_sample", sample)
    if not isinstance(reward_sample, dict):
        return 0.0

    reward = reward_sample.get("reward")
    if isinstance(reward, dict) and isinstance(reward.get("total"), int | float):
        score = float(reward["total"])
    else:
        evidence = reward_sample.get("reward_evidence")
        if not isinstance(evidence, dict):
            score = 0.0
        else:
            score = _score_from_evidence(evidence, reward_sample)
    if completion is not None:
        score += _completion_adjustment(sample, completion)
    return round(_clamp(score), 6)


def grpo_reward_function(completions: list[str] | None = None, **kwargs: Any) -> list[float]:
    """TRL-compatible reward function wrapper for scaffold smoke checks."""
    samples = kwargs.get("samples") or kwargs.get("reward_samples") or []
    completions = completions or []
    if samples:
        return [compute_grpo_reward(sample, completions[index] if index < len(completions) else None) for index, sample in enumerate(samples)]
    return [0.0 for _ in completions]


def _score_from_evidence(evidence: dict[str, Any], reward_sample: dict[str, Any]) -> float:
    score = 0.0
    if evidence.get("holdout_hits"):
        score += 0.4
    satisfied = evidence.get("feedback_constraints_satisfied", {})
    if isinstance(satisfied, dict):
        if satisfied.get("disliked_item_ids", True):
            score += 0.10
        if satisfied.get("disliked_categories", True):
            score += 0.10
        if satisfied.get("preferred_represented", True):
            score += 0.05
        if satisfied.get("prior_turn_filter", True):
            score += 0.05
        if not satisfied.get("feedback_effect_observed", True):
            score = min(score, 0.10)
    unsupported = evidence.get("unsupported_explanation_claims", [])
    if isinstance(unsupported, list):
        score += max(0.0, 0.20 - 0.10 * len(unsupported))
    risk_flags = set(evidence.get("risk_flags", []) or reward_sample.get("risk_flags", []))
    if "popular_fallback_used" in risk_flags:
        score -= 0.05
    if "empty_recommendation_list" in risk_flags:
        score -= 0.05
    return score


def _completion_adjustment(sample: dict[str, Any], completion: str) -> float:
    target_action = sample.get("target_action", {})
    if not isinstance(target_action, dict):
        return 0.0
    allowed = {str(item_id) for item_id in target_action.get("allowed_item_ids", []) if str(item_id)}
    expected = {str(item_id) for item_id in target_action.get("selected_item_ids", []) if str(item_id)}
    selected = _selected_item_ids_from_completion(completion)
    if not selected:
        return -0.20
    if allowed and not selected <= allowed:
        return -0.50
    if expected and selected == expected:
        return 0.10
    return 0.03


def _selected_item_ids_from_completion(completion: str) -> set[str]:
    text = completion.strip()
    if not text:
        return set()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {part.strip() for part in text.replace(",", " ").split() if part.strip()}
    if isinstance(payload, dict):
        value = payload.get("selected_item_ids") or payload.get("item_ids") or payload.get("item_id")
        if isinstance(value, list):
            return {str(item_id) for item_id in value if str(item_id)}
        if value:
            return {str(value)}
    if isinstance(payload, list):
        return {str(item_id) for item_id in payload if str(item_id)}
    if isinstance(payload, str) and payload.strip():
        return {payload.strip()}
    return set()


def _clamp(value: float) -> float:
    return min(1.0, max(-1.0, value))
