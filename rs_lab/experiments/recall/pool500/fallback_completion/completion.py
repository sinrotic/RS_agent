from __future__ import annotations

from collections import Counter
from typing import Any

from rs_core.recsys.recall import duplicate_count, merge_candidates_with_fallback
from rs_core.recsys.types import MergedCandidate
from rs_lab.experiments.recall.pool500.fallback_completion.config import Pool500FallbackCompletionConfig
from rs_lab.experiments.recall.pool500.fallback_completion.segment import segment_for_sequence
from rs_lab.experiments.recall.pool500.fallback_completion.sources import iter_source_candidates
from rs_lab.experiments.recall.pool500.fallback_completion.types import FallbackCandidate, FallbackCompletionContext, FallbackCompletionResult
from rs_lab.experiments.recall.pool500.governance.fallback_completion_contract import FallbackSource

CANONICAL_FALLBACK_SOURCES = {"category", "semantic_title_category_expansion", "co_visit_fallback_repair", "popular"}


def complete_pool500_for_user(
    *,
    sequence: dict[str, Any],
    existing_candidates: list[MergedCandidate],
    context: FallbackCompletionContext,
    config: Pool500FallbackCompletionConfig,
) -> FallbackCompletionResult:
    user_id = str(sequence.get("user_id") or sequence.get("reviewer_id") or "")
    history_items = set(_sequence_items(sequence))
    seed_items = _seed_items(sequence)
    user_segment = segment_for_sequence(sequence, config.normal_threshold).value

    merge_result = merge_candidates_with_fallback(
        existing_candidates=existing_candidates,
        fallback_candidates=iter_source_candidates(user_id=user_id, seed_items=seed_items, context=context, config=config),
        target_count=config.target_candidate_count,
        history_items=history_items,
        fallback_item_id=lambda fallback: fallback.item_id,
        fallback_source=lambda fallback: fallback.fallback_source,
        to_merged_candidate=lambda fallback: _to_merged_candidate(fallback, config, user_segment),
        source_caps=config.source_caps,
    )
    candidates = merge_result.candidates
    added_candidates = merge_result.added_candidates
    personalized_count = len(candidates) - len(added_candidates)
    source_mix: Counter[str] = Counter({FallbackSource.PERSONALIZED_PRIMARY.value: personalized_count})
    source_mix.update(merge_result.source_used)

    audit_input = {
        "user_id": user_id,
        "sequence_len": int(sequence.get("sequence_len") or len(sequence.get("recent_item_sequence", []) or [])),
        "positive_sequence_len": int(sequence.get("positive_sequence_len") or len(sequence.get("recent_positive_item_sequence", []) or [])),
        "strong_positive_sequence_len": int(sequence.get("strong_positive_sequence_len") or sequence.get("positive_sequence_len") or len(sequence.get("recent_positive_item_sequence", []) or [])),
        "personalized_candidate_count_before_fallback": personalized_count,
        "final_candidate_count": len(candidates),
        "fallback_added_count": len(added_candidates),
        "source_mix": dict(source_mix),
        "candidate_item_ids": [candidate.item_id for candidate in candidates],
        "duplicate_item_per_user_count": duplicate_count(candidate.item_id for candidate in candidates),
    }
    return FallbackCompletionResult(
        user_id=user_id,
        candidates=candidates,
        audit_input=audit_input,
        added_candidates=added_candidates,
        source_contribution=dict(source_mix),
    )


def _to_merged_candidate(candidate: FallbackCandidate, config: Pool500FallbackCompletionConfig, user_segment: str) -> MergedCandidate:
    if candidate.canonical_source not in CANONICAL_FALLBACK_SOURCES:
        raise ValueError(f"non-canonical fallback source label: {candidate.canonical_source}")
    metadata = {
        "fallback_subtype": candidate.fallback_source,
        "fallback_stage": config.stage,
        "fallback_reason": config.fallback_reason,
        "user_segment": user_segment,
        "fallback_evidence": candidate.evidence,
    }
    return MergedCandidate(
        item_id=candidate.item_id,
        sources=[candidate.canonical_source],
        source_scores={candidate.canonical_source: candidate.score},
        category=candidate.category,
        metadata=metadata,
    )


def _sequence_items(sequence: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for field in ("recent_item_sequence", "recent_positive_item_sequence", "positive_item_sequence", "item_sequence"):
        items.extend(str(item).strip() for item in sequence.get(field, []) or [] if str(item).strip())
    return items


def _seed_items(sequence: dict[str, Any]) -> list[str]:
    for field in ("recent_positive_item_sequence", "positive_item_sequence", "recent_item_sequence", "item_sequence"):
        items = [str(item).strip() for item in sequence.get(field, []) or [] if str(item).strip()]
        if items:
            return items
    return []
