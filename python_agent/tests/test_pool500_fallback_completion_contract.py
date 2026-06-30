from __future__ import annotations

from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import (
    FALLBACK_SOURCE_LADDER,
    FallbackCompletionConfig,
    FallbackSource,
    UserSegment,
    build_fallback_completion_audit,
    classify_user_segment,
    quality_risk_level,
    validate_fallback_completion_contract,
)


def test_classify_zero_history() -> None:
    assert classify_user_segment(sequence_len=0, positive_sequence_len=0) == UserSegment.ZERO_HISTORY


def test_classify_zero_positive_history() -> None:
    assert classify_user_segment(sequence_len=3, positive_sequence_len=0) == UserSegment.ZERO_POSITIVE_HISTORY


def test_classify_low_history_single_seed() -> None:
    assert classify_user_segment(sequence_len=3, positive_sequence_len=1) == UserSegment.LOW_HISTORY_SINGLE_SEED


def test_classify_low_history_multi_seed() -> None:
    assert classify_user_segment(sequence_len=3, positive_sequence_len=2, normal_threshold=3) == UserSegment.LOW_HISTORY_MULTI_SEED


def test_classify_normal_history() -> None:
    assert classify_user_segment(sequence_len=3, positive_sequence_len=3, normal_threshold=3) == UserSegment.NORMAL_HISTORY


def test_zero_history_full_fallback_is_high_risk() -> None:
    risk = quality_risk_level(UserSegment.ZERO_HISTORY, personalized_candidate_count=0, fallback_ratio=1.0, popular_ratio=1.0)

    assert risk["level"] == "HIGH"
    assert "insufficient_behavior_history" in risk["reasons"]


def test_nearly_full_personalized_pool_is_low_risk() -> None:
    risk = quality_risk_level(UserSegment.NORMAL_HISTORY, personalized_candidate_count=400, fallback_ratio=0.2, popular_ratio=0.1)

    assert risk["level"] == "LOW"


def test_medium_risk_personalized_threshold() -> None:
    risk = quality_risk_level(UserSegment.NORMAL_HISTORY, personalized_candidate_count=250, fallback_ratio=0.5, popular_ratio=0.1)

    assert risk["level"] == "MEDIUM"


def test_high_risk_when_fallback_ratio_exceeds_half() -> None:
    risk = quality_risk_level(UserSegment.NORMAL_HISTORY, personalized_candidate_count=399, fallback_ratio=0.51, popular_ratio=0.1)

    assert risk["level"] == "HIGH"


def test_high_risk_when_popular_ratio_exceeds_threshold() -> None:
    risk = quality_risk_level(UserSegment.NORMAL_HISTORY, personalized_candidate_count=500, fallback_ratio=0.1, popular_ratio=0.31)

    assert risk["level"] == "HIGH"


def test_fallback_config_governance_flags_stay_false() -> None:
    config = FallbackCompletionConfig()

    assert config.candidate_generation_allowed is False
    assert config.ranking_input_replacement_allowed is False
    assert config.ranking_replacement_allowed is False
    assert config.promotion_allowed is False
    assert config.pool1000_allowed is False
    assert config.full_pool500_ready_declared is False


def test_validation_fails_when_audit_config_governance_flag_is_true() -> None:
    audit = build_fallback_completion_audit(
        [
            {
                "user_id": "u1",
                "sequence_len": 5,
                "positive_sequence_len": 5,
                "personalized_candidate_count_before_fallback": 500,
                "final_candidate_count": 500,
                "source_mix": {FallbackSource.PERSONALIZED_PRIMARY.value: 500},
            }
        ]
    )
    audit["config"]["promotion_allowed"] = True

    result = validate_fallback_completion_contract(audit)

    assert result["valid"] is False
    assert "audit config governance flag must stay false: promotion_allowed" in result["errors"]


def test_validation_fails_when_user_exceeds_target() -> None:
    audit = build_fallback_completion_audit(
        [
            {
                "user_id": "u1",
                "sequence_len": 5,
                "positive_sequence_len": 5,
                "personalized_candidate_count_before_fallback": 500,
                "final_candidate_count": 501,
                "source_mix": {FallbackSource.PERSONALIZED_PRIMARY.value: 501},
            }
        ]
    )

    result = validate_fallback_completion_contract(audit)

    assert result["valid"] is False
    assert any("exceeds target" in error for error in result["errors"])


def test_validation_fails_when_duplicate_item_per_user_count_positive() -> None:
    audit = build_fallback_completion_audit(
        [
            {
                "user_id": "u1",
                "sequence_len": 5,
                "positive_sequence_len": 5,
                "personalized_candidate_count_before_fallback": 499,
                "final_candidate_count": 500,
                "source_mix": {
                    FallbackSource.PERSONALIZED_PRIMARY.value: 499,
                    FallbackSource.SEED_CATEGORY_SIBLING.value: 1,
                },
                "duplicate_item_per_user_count": 1,
            }
        ]
    )

    result = validate_fallback_completion_contract(audit)

    assert result["valid"] is False
    assert "duplicate_item_per_user_count must be 0" in result["errors"]


def test_global_diversity_popular_can_complete_zero_history_but_remains_high_risk() -> None:
    audit = build_fallback_completion_audit(
        [
            {
                "user_id": "cold_user",
                "sequence_len": 0,
                "positive_sequence_len": 0,
                "strong_positive_sequence_len": 0,
                "personalized_candidate_count_before_fallback": 0,
                "final_candidate_count": 500,
                "source_mix": {FallbackSource.GLOBAL_DIVERSITY_POPULAR.value: 500},
            }
        ]
    )

    user_audit = audit["per_user"][0]

    assert user_audit["completion_status"] == "TARGET_MET"
    assert user_audit["quality_risk_level"] == "HIGH"
    assert user_audit["fallback_ratio"] == 1.0
    assert user_audit["popular_ratio"] == 1.0
    assert audit["global"]["users_with_target_candidates"] == 1


def test_source_priority_places_popular_after_seed_metadata_semantic_fallback() -> None:
    ladder = [source.value for source in FALLBACK_SOURCE_LADDER]

    assert ladder.index(FallbackSource.CATEGORY_POPULAR.value) > ladder.index(FallbackSource.SEED_CATEGORY_SIBLING.value)
    assert ladder.index(FallbackSource.CATEGORY_POPULAR.value) > ladder.index(FallbackSource.SEED_METADATA_NEIGHBOR.value)
    assert ladder.index(FallbackSource.CATEGORY_POPULAR.value) > ladder.index(FallbackSource.SEED_SEMANTIC_TOKEN.value)
    assert ladder.index(FallbackSource.SESSION_OR_CONTEXT_POPULAR.value) > ladder.index(FallbackSource.SEED_SEMANTIC_TOKEN.value)
    assert ladder.index(FallbackSource.GLOBAL_DIVERSITY_POPULAR.value) > ladder.index(FallbackSource.CATEGORY_POPULAR.value)
