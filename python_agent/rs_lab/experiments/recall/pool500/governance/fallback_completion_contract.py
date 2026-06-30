from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class UserSegment(StrEnum):
    ZERO_HISTORY = "ZERO_HISTORY"
    ZERO_POSITIVE_HISTORY = "ZERO_POSITIVE_HISTORY"
    LOW_HISTORY_SINGLE_SEED = "LOW_HISTORY_SINGLE_SEED"
    LOW_HISTORY_MULTI_SEED = "LOW_HISTORY_MULTI_SEED"
    NORMAL_HISTORY = "NORMAL_HISTORY"


class FallbackSource(StrEnum):
    PERSONALIZED_PRIMARY = "personalized_primary"
    SEED_CATEGORY_SIBLING = "fallback_seed_category_sibling"
    SEED_METADATA_NEIGHBOR = "fallback_seed_metadata_neighbor"
    SEED_SEMANTIC_TOKEN = "fallback_seed_semantic_token"
    CATEGORY_POPULAR = "fallback_category_popular"
    SESSION_OR_CONTEXT_POPULAR = "fallback_context_popular"
    GLOBAL_DIVERSITY_POPULAR = "fallback_global_diversity_popular"


FALLBACK_SOURCE_LADDER = tuple(FallbackSource)
POPULAR_FALLBACK_SOURCES = {
    FallbackSource.CATEGORY_POPULAR.value,
    FallbackSource.SESSION_OR_CONTEXT_POPULAR.value,
    FallbackSource.GLOBAL_DIVERSITY_POPULAR.value,
}


@dataclass
class FallbackCompletionConfig:
    target_candidate_count: int = 500
    normal_threshold: int = 3
    seed_category_sibling_cap: int = 260
    seed_metadata_neighbor_cap: int = 160
    seed_semantic_token_cap: int = 160
    category_popular_cap: int = 160
    context_popular_cap: int = 160
    global_diversity_popular_cap: int = 500
    candidate_generation_allowed: bool = False
    ranking_input_replacement_allowed: bool = False
    ranking_replacement_allowed: bool = False
    promotion_allowed: bool = False
    pool1000_allowed: bool = False
    full_pool500_ready_declared: bool = False
    source_caps: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        self.source_caps = {
            FallbackSource.SEED_CATEGORY_SIBLING.value: self.seed_category_sibling_cap,
            FallbackSource.SEED_METADATA_NEIGHBOR.value: self.seed_metadata_neighbor_cap,
            FallbackSource.SEED_SEMANTIC_TOKEN.value: self.seed_semantic_token_cap,
            FallbackSource.CATEGORY_POPULAR.value: self.category_popular_cap,
            FallbackSource.SESSION_OR_CONTEXT_POPULAR.value: self.context_popular_cap,
            FallbackSource.GLOBAL_DIVERSITY_POPULAR.value: self.global_diversity_popular_cap,
        }


def classify_user_segment(sequence_len: int, positive_sequence_len: int, normal_threshold: int = 3) -> UserSegment:
    if sequence_len < 0 or positive_sequence_len < 0 or normal_threshold <= 0:
        raise ValueError("sequence lengths must be non-negative and normal_threshold must be positive")
    if sequence_len == 0:
        return UserSegment.ZERO_HISTORY
    if positive_sequence_len == 0:
        return UserSegment.ZERO_POSITIVE_HISTORY
    if positive_sequence_len == 1:
        return UserSegment.LOW_HISTORY_SINGLE_SEED
    if positive_sequence_len < normal_threshold:
        return UserSegment.LOW_HISTORY_MULTI_SEED
    return UserSegment.NORMAL_HISTORY


def quality_risk_level(
    user_segment: UserSegment | str,
    personalized_candidate_count: int,
    fallback_ratio: float,
    popular_ratio: float,
) -> dict[str, Any]:
    segment = UserSegment(user_segment)
    reasons: list[str] = []
    if segment in {UserSegment.ZERO_HISTORY, UserSegment.ZERO_POSITIVE_HISTORY}:
        reasons.append("insufficient_behavior_history")
    elif segment in {UserSegment.LOW_HISTORY_SINGLE_SEED, UserSegment.LOW_HISTORY_MULTI_SEED}:
        reasons.append("low_positive_seed_count")
    if personalized_candidate_count <= 0:
        reasons.append("no_personalized_candidates")
    if fallback_ratio >= 0.8:
        reasons.append("fallback_dominant_pool")
    if popular_ratio >= 0.5:
        reasons.append("popular_dominant_pool")

    if segment in {UserSegment.ZERO_HISTORY, UserSegment.ZERO_POSITIVE_HISTORY}:
        level = "HIGH"
    elif fallback_ratio > 0.5:
        level = "HIGH"
    elif popular_ratio > 0.3:
        level = "HIGH"
    elif personalized_candidate_count >= 400 and fallback_ratio <= 0.2:
        level = "LOW"
    elif personalized_candidate_count >= 250 and fallback_ratio <= 0.5:
        level = "MEDIUM"
    else:
        level = "HIGH"
    return {"level": level, "reasons": reasons}


def build_fallback_completion_audit(
    per_user_inputs: Iterable[dict[str, Any]],
    config: FallbackCompletionConfig | None = None,
) -> dict[str, Any]:
    config = config or FallbackCompletionConfig()
    per_user: list[dict[str, Any]] = []
    segment_counts: Counter[str] = Counter()
    fallback_source_contribution: Counter[str] = Counter()
    fallback_ratios: list[float] = []
    popular_ratios: list[float] = []
    duplicate_item_per_user_count = 0
    per_user_over_target_count = 0
    users_with_target_candidates = 0
    high_risk_user_count = 0

    for record in per_user_inputs:
        if "user_id" not in record:
            raise ValueError("per_user_inputs record missing user_id")
        sequence_len = int(record.get("sequence_len", 0))
        positive_sequence_len = int(record.get("positive_sequence_len", 0))
        strong_positive_sequence_len = int(record.get("strong_positive_sequence_len", positive_sequence_len))
        personalized_count = int(record.get("personalized_candidate_count_before_fallback", 0))
        final_count = int(record.get("final_candidate_count", personalized_count))
        source_mix = {str(source): int(count) for source, count in dict(record.get("source_mix", {})).items()}
        fallback_added_count = int(record.get("fallback_added_count", max(0, final_count - personalized_count)))
        fallback_count_from_mix = sum(
            count for source, count in source_mix.items() if source != FallbackSource.PERSONALIZED_PRIMARY.value
        )
        popular_count = sum(count for source, count in source_mix.items() if source in POPULAR_FALLBACK_SOURCES)
        if fallback_count_from_mix > 0:
            fallback_added_count = fallback_count_from_mix
        fallback_ratio = _ratio(fallback_added_count, final_count)
        popular_ratio = _ratio(popular_count, final_count)
        segment = classify_user_segment(sequence_len, positive_sequence_len, config.normal_threshold)
        risk = quality_risk_level(segment, personalized_count, fallback_ratio, popular_ratio)
        duplicate_count = int(record.get("duplicate_item_per_user_count", _duplicate_count(record.get("candidate_item_ids"))))
        completion_status = "TARGET_MET" if final_count >= config.target_candidate_count else "UNDERFILLED"
        if final_count > config.target_candidate_count:
            completion_status = "OVER_TARGET"
            per_user_over_target_count += 1
        if final_count >= config.target_candidate_count:
            users_with_target_candidates += 1
        if duplicate_count > 0:
            duplicate_item_per_user_count += 1
        if risk["level"] == "HIGH":
            high_risk_user_count += 1

        segment_counts[segment.value] += 1
        fallback_ratios.append(fallback_ratio)
        popular_ratios.append(popular_ratio)
        for source, count in source_mix.items():
            fallback_source_contribution[source] += count

        per_user.append(
            {
                "user_id": str(record["user_id"]),
                "user_segment": segment.value,
                "sequence_len": sequence_len,
                "positive_sequence_len": positive_sequence_len,
                "strong_positive_sequence_len": strong_positive_sequence_len,
                "target_candidate_count": config.target_candidate_count,
                "personalized_candidate_count_before_fallback": personalized_count,
                "fallback_added_count": fallback_added_count,
                "final_candidate_count": final_count,
                "fallback_ratio": fallback_ratio,
                "popular_ratio": popular_ratio,
                "source_mix": source_mix,
                "quality_risk_level": risk["level"],
                "risk_reasons": risk["reasons"],
                "completion_status": completion_status,
            }
        )

    target_user_count = len(per_user)
    return {
        "schema_version": "pool500_fallback_completion_contract_v1",
        "policy_role": "pre_promotion_governance_contract_not_full_pool500_ready",
        "config": _config_contract_dict(config),
        "per_user": per_user,
        "global": {
            "target_user_count": target_user_count,
            "users_with_target_candidates": users_with_target_candidates,
            "underfilled_user_count": target_user_count - users_with_target_candidates,
            "user_segment_counts": dict(segment_counts),
            "average_fallback_ratio": _average(fallback_ratios),
            "average_popular_ratio": _average(popular_ratios),
            "high_risk_user_count": high_risk_user_count,
            "fallback_source_contribution": dict(fallback_source_contribution),
            "duplicate_item_per_user_count": duplicate_item_per_user_count,
            "per_user_over_target_count": per_user_over_target_count,
        },
    }


def validate_fallback_completion_contract(
    audit: dict[str, Any],
    config: FallbackCompletionConfig | None = None,
) -> dict[str, Any]:
    if not isinstance(audit, dict):
        raise TypeError("audit must be a dict")
    config = config or FallbackCompletionConfig()
    errors: list[str] = []
    for flag in _governance_flag_names():
        if bool(getattr(config, flag)):
            errors.append(f"governance flag must stay false: {flag}")
    audit_config = audit.get("config", {})
    if not isinstance(audit_config, dict):
        raise ValueError("audit config must be a dict when present")
    for flag in _governance_flag_names():
        if bool(audit_config.get(flag, False)):
            errors.append(f"audit config governance flag must stay false: {flag}")
    if config.full_pool500_ready_declared or audit_config.get("full_pool500_ready_declared") is True:
        errors.append("FULL_POOL500_READY must not be declared by fallback completion governance")

    global_audit = audit.get("global")
    per_user_audit = audit.get("per_user")
    if not isinstance(global_audit, dict) or not isinstance(per_user_audit, list):
        raise ValueError("audit must contain global dict and per_user list")

    for user_audit in per_user_audit:
        if int(user_audit.get("final_candidate_count", 0)) > config.target_candidate_count:
            errors.append(f"user exceeds target candidate count: {user_audit.get('user_id')}")
    if int(global_audit.get("duplicate_item_per_user_count", 0)) > 0:
        errors.append("duplicate_item_per_user_count must be 0")
    if int(global_audit.get("per_user_over_target_count", 0)) > 0:
        errors.append("per_user_over_target_count must be 0")
    if audit.get("full_pool500_ready_declared") is True:
        errors.append("audit must not declare full_pool500_ready_declared")
    return {"valid": not errors, "errors": errors}


def _governance_flag_names() -> tuple[str, ...]:
    return (
        "candidate_generation_allowed",
        "ranking_input_replacement_allowed",
        "ranking_replacement_allowed",
        "promotion_allowed",
        "pool1000_allowed",
        "full_pool500_ready_declared",
    )


def _config_contract_dict(config: FallbackCompletionConfig) -> dict[str, Any]:
    return {
        "target_candidate_count": config.target_candidate_count,
        "normal_threshold": config.normal_threshold,
        "source_caps": config.source_caps,
        **{flag: getattr(config, flag) for flag in _governance_flag_names()},
    }


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _duplicate_count(candidate_item_ids: Any) -> int:
    if not candidate_item_ids:
        return 0
    item_ids = [str(item_id) for item_id in candidate_item_ids]
    return len(item_ids) - len(set(item_ids))
