from __future__ import annotations

from dataclasses import replace
from typing import Any

from rs_core.common.recsys_types import MergedCandidate, RecallCandidate
from rs_core.agent.contracts.schema import FeedbackConstraints


def apply_feedback_rerank(
    candidates: list[MergedCandidate],
    constraints: FeedbackConstraints | None,
    itemcf_weak: dict[str, list[RecallCandidate]],
    itemcf_strong: dict[str, list[RecallCandidate]],
    config: dict[str, Any],
    turn_index: int | None = None,
) -> tuple[list[MergedCandidate], dict[str, Any]]:
    policy = config.get("feedback_rerank", {})
    if not policy.get("enabled"):
        return candidates, _empty_diagnostics()
    constraints = constraints or FeedbackConstraints()
    liked_item_ids = set(constraints.liked_item_ids)
    disliked_item_ids = set(constraints.disliked_item_ids)
    positive_boost = float(policy.get("positive_similarity_boost", 0.0))
    negative_demote = float(policy.get("negative_similarity_demote", 0.0))
    sources = list(policy.get("similarity_sources", ["itemcf_strong", "itemcf_weak"]))

    positive_neighbors = _neighbor_scores(liked_item_ids, sources, itemcf_weak, itemcf_strong)
    negative_neighbors = _neighbor_scores(disliked_item_ids, sources, itemcf_weak, itemcf_strong)
    explicit_filter_events: list[dict[str, Any]] = []

    adjusted: list[MergedCandidate] = []
    candidate_events: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate.item_id in disliked_item_ids and not candidate.metadata.get("constraint_filter_restored"):
            explicit_filter_events.append(_event(
                action="filter",
                target_item_id=candidate.item_id,
                source_item_id=candidate.item_id,
                reason="explicit_dislike",
                similarity_source=None,
                similarity_score=None,
                delta=None,
                turn_index=turn_index,
            ))
            continue
        delta = 0.0
        events: list[dict[str, Any]] = []
        if candidate.item_id in positive_neighbors and positive_boost:
            neighbor = positive_neighbors[candidate.item_id]
            boost_delta = positive_boost * neighbor["score"]
            delta += boost_delta
            events.append(_event(
                action="boost",
                target_item_id=candidate.item_id,
                source_item_id=neighbor["source_item_id"],
                reason="liked_item_anchor",
                similarity_source=neighbor["similarity_source"],
                similarity_score=neighbor["score"],
                delta=boost_delta,
                turn_index=turn_index,
            ))
        if candidate.item_id in negative_neighbors and negative_demote:
            neighbor = negative_neighbors[candidate.item_id]
            demote_delta = -negative_demote * neighbor["score"]
            delta += demote_delta
            events.append(_event(
                action="demote",
                target_item_id=candidate.item_id,
                source_item_id=neighbor["source_item_id"],
                reason="itemcf_similarity_propagation",
                similarity_source=neighbor["similarity_source"],
                similarity_score=neighbor["score"],
                delta=demote_delta,
                turn_index=turn_index,
            ))
        if not events:
            adjusted.append(candidate)
            continue
        metadata = dict(candidate.metadata)
        existing_events = metadata.get("model_rerank_events", [])
        if not isinstance(existing_events, list):
            existing_events = []
        metadata["model_rerank_events"] = [*existing_events, *events]
        source_scores = dict(candidate.source_scores)
        source_scores["feedback_rerank"] = float(source_scores.get("feedback_rerank", 0.0)) + delta
        sources_for_candidate = list(candidate.sources)
        if "feedback_rerank" not in sources_for_candidate:
            sources_for_candidate.append("feedback_rerank")
        candidate_events.extend(events)
        adjusted.append(replace(candidate, sources=sources_for_candidate, source_scores=source_scores, metadata=metadata))

    events = [*explicit_filter_events, *candidate_events]
    diagnostics = {
        "feedback_rerank_events": events,
        "feedback_rerank_summary": {
            "filtered_item_count": len(explicit_filter_events),
            "boosted_item_count": sum(1 for event in candidate_events if event["action"] == "boost"),
            "demoted_item_count": sum(1 for event in candidate_events if event["action"] == "demote"),
            "liked_item_ids": sorted(liked_item_ids),
            "disliked_item_ids": sorted(disliked_item_ids),
        },
    }
    return adjusted, diagnostics


def _empty_diagnostics() -> dict[str, Any]:
    return {"feedback_rerank_events": [], "feedback_rerank_summary": {}}


def _neighbor_scores(
    seed_item_ids: set[str],
    sources: list[str],
    itemcf_weak: dict[str, list[RecallCandidate]],
    itemcf_strong: dict[str, list[RecallCandidate]],
) -> dict[str, dict[str, Any]]:
    by_source = {"itemcf_strong": itemcf_strong, "itemcf_weak": itemcf_weak}
    neighbors: dict[str, dict[str, Any]] = {}
    for source in sources:
        rows_by_seed = by_source.get(source, {})
        for seed_item_id in sorted(seed_item_ids):
            for row in rows_by_seed.get(seed_item_id, []):
                current = neighbors.get(row.item_id)
                score = float(row.score)
                if current is None or score > float(current["score"]):
                    neighbors[row.item_id] = {
                        "source_item_id": seed_item_id,
                        "similarity_source": source,
                        "score": score,
                    }
    return neighbors


def _event(
    action: str,
    target_item_id: str,
    source_item_id: str,
    reason: str,
    similarity_source: str | None,
    similarity_score: float | None,
    delta: float | None,
    turn_index: int | None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "feedback_rerank",
        "action": action,
        "target_item_id": target_item_id,
        "source_item_id": source_item_id,
        "reason": reason,
    }
    if similarity_source is not None:
        event["similarity_source"] = similarity_source
    if similarity_score is not None:
        event["similarity_score"] = round(float(similarity_score), 6)
    if delta is not None:
        event["delta"] = round(float(delta), 6)
    if turn_index is not None:
        event["turn_index"] = turn_index
    return event
