from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rs_core.offline.training.data_contracts import synthetic_grpo_samples
from rs_core.offline.training.reward_adapter import compute_grpo_reward, grpo_reward_function


def test_compute_grpo_reward_uses_existing_total_when_present() -> None:
    sample = synthetic_grpo_samples()[0]

    assert compute_grpo_reward(sample) == 0.7


def test_compute_grpo_reward_can_reconstruct_from_evidence() -> None:
    sample = synthetic_grpo_samples()[0]
    sample["reward_sample"].pop("reward")

    assert compute_grpo_reward(sample) == 0.5


def test_compute_grpo_reward_penalizes_risk_flags_and_clamps() -> None:
    sample = {
        "reward_sample": {
            "reward": {"total": 3.0},
            "risk_flags": ["popular_fallback_used"],
        }
    }
    assert compute_grpo_reward(sample) == 1.0

    evidence_only = {
        "reward_evidence": {
            "feedback_constraints_satisfied": {
                "disliked_item_ids": True,
                "disliked_categories": True,
                "preferred_represented": True,
                "prior_turn_filter": True,
                "feedback_effect_observed": True,
            },
            "unsupported_explanation_claims": ["source:semantic", "feedback", "source:popular"],
            "risk_flags": ["popular_fallback_used", "empty_recommendation_list"],
        }
    }
    assert compute_grpo_reward(evidence_only) == 0.2


def test_compute_grpo_reward_adjusts_for_completion_validity() -> None:
    sample = synthetic_grpo_samples()[0]

    assert compute_grpo_reward(sample, completion='{"selected_item_ids":["speaker_1"]}') == 0.8
    assert compute_grpo_reward(sample, completion='{"selected_item_ids":["printer_ink"]}') == 0.2
    assert compute_grpo_reward(sample, completion='{}') == 0.5


def test_grpo_reward_function_is_trl_compatible() -> None:
    samples = synthetic_grpo_samples()

    assert grpo_reward_function(samples=samples, completions=["speaker_1"]) == [0.8]
    assert grpo_reward_function(completions=["a", "b"]) == [0.0, 0.0]
