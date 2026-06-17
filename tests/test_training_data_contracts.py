from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from rs_core.training.data_contracts import (
    GRPO_SAMPLE_SCHEMA_VERSION,
    SFT_SAMPLE_SCHEMA_VERSION,
    sft_messages_from_sample,
    synthetic_grpo_samples,
    synthetic_sft_samples,
    validate_grpo_sample,
    validate_grpo_samples,
    validate_sft_sample,
    validate_sft_samples,
)


def test_synthetic_sft_samples_match_rollout_contract() -> None:
    samples = synthetic_sft_samples()

    validate_sft_samples(samples)
    sample = samples[0]
    payload = sample["sample"]
    assert sample["schema_version"] == SFT_SAMPLE_SCHEMA_VERSION
    assert payload["target_action"]["must_select_from_candidates"] is True
    assert set(payload["target_action"]["selected_item_ids"]) <= set(payload["target_action"]["allowed_item_ids"])
    assert sft_messages_from_sample(sample) == [
        {"role": "user", "content": payload["user_input"]},
        {"role": "assistant", "content": payload["assistant_response"]},
    ]


def test_synthetic_grpo_samples_include_reward_context() -> None:
    samples = synthetic_grpo_samples()

    validate_grpo_samples(samples)
    sample = samples[0]
    assert sample["schema_version"] == GRPO_SAMPLE_SCHEMA_VERSION
    assert sample["reward_sample"]["reward"]["total"] == 0.7
    assert sample["target_action"]["must_select_from_candidates"] is True


def test_sft_contract_rejects_selection_outside_candidates() -> None:
    sample = synthetic_sft_samples()[0]
    sample["sample"]["target_action"]["selected_item_ids"] = ["missing"]
    sample["sample"]["target_action"]["allowed_item_ids"].append("missing")

    with pytest.raises(ValueError, match="candidate_summary"):
        validate_sft_sample(sample)


def test_grpo_contract_requires_reward_sample() -> None:
    sample = synthetic_grpo_samples()[0]
    sample.pop("reward_sample")

    with pytest.raises(ValueError, match="reward_sample"):
        validate_grpo_sample(sample)
