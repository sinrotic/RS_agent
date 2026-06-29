from __future__ import annotations

from typing import Any
from uuid import uuid4

from rs_core.data.clients import CandidatePoolClient
from rs_core.online.contracts import RecallRequest, RecallResult, RecallTrace
from rs_core.online.recall.canonical import (
    CANONICAL_SOURCES,
    FINAL_SOURCE_WHITELIST,
    FORBIDDEN_SOURCE_LABELS,
    GROUP_SOURCE_EXPANSIONS,
    SOURCE_ALIASES,
    canonicalize_source_label,
    canonicalize_source_set,
    forbidden_source_labels,
    unknown_source_labels,
)
from rs_core.online.recall.merge import MergeResult, duplicate_count, merge_candidates_with_fallback


def recall_from_sequence_contract(
    request: RecallRequest | dict[str, Any],
    *,
    candidate_pool_client: CandidatePoolClient | None = None,
) -> RecallResult:
    """Build a public-safe recall result through the online recall boundary."""

    recall_request = request if isinstance(request, RecallRequest) else RecallRequest(**dict(request))
    payload = recall_request.model_dump()
    sequence = payload.get("user_sequence") or {}
    raw_item_ids = sequence.get("recent_item_sequence") or sequence.get("recent_item_ids") or []
    item_ids = [str(item) for item in raw_item_ids if item]
    size = int(payload.get("candidate_pool_size") or len(item_ids) or 0)
    candidate_pool = (candidate_pool_client or CandidatePoolClient()).from_item_ids(
        pool_id=str(payload.get("user_id") or uuid4()),
        item_ids=item_ids[:size],
        source="online_recall_sequence_contract",
    )
    return RecallResult(
        request_id=str(uuid4()),
        candidate_item_ids=candidate_pool.item_ids,
        candidate_count=len(candidate_pool.item_ids),
        retrieval_summary=RecallTrace(target_pool_size=size, path_count=1).to_dict(),
    )


__all__ = [
    "CANONICAL_SOURCES",
    "FINAL_SOURCE_WHITELIST",
    "FORBIDDEN_SOURCE_LABELS",
    "GROUP_SOURCE_EXPANSIONS",
    "SOURCE_ALIASES",
    "MergeResult",
    "canonicalize_source_label",
    "canonicalize_source_set",
    "duplicate_count",
    "forbidden_source_labels",
    "merge_candidates_with_fallback",
    "recall_from_sequence_contract",
    "unknown_source_labels",
]
