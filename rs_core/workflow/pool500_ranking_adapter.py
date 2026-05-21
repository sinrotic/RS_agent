from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from rs_core.common.io import iter_jsonl
from rs_core.recsys.types import MergedCandidate
from rs_core.workflow.full_data_pool500_route_gate import CANONICAL_SOURCES, FORBIDDEN_SOURCE_LABELS, canonicalize_source_label

SCHEMA_VERSION = "pool500_ranking_adapter_v1"
PASS = "PASS"
STOP = "STOP"
REQUIRED_ROW_FIELDS = {"user_id", "item_id", "source", "score", "rank", "metadata"}
DEFAULT_POOL_LIMIT = 500
POOL500_LINEAGE_KEY = "pool500_source_lineage"


def adapt_pool500_rows_to_candidates(
    rows: Iterable[dict[str, Any]],
    *,
    candidate_pool_limit: int = DEFAULT_POOL_LIMIT,
    extra_allowed_sources: set[str] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    candidates_by_user: dict[str, dict[str, MergedCandidate]] = defaultdict(dict)
    seen_user_item_source: set[tuple[str, str, str]] = set()
    allowed_sources = CANONICAL_SOURCES | (extra_allowed_sources or set())

    for row_index, row in enumerate(rows, start=1):
        row_blockers = _validate_required_fields(row, row_index)
        if row_blockers:
            blockers.extend(row_blockers)
            continue

        user_id = str(row["user_id"])
        item_id = str(row["item_id"])
        raw_source = row["source"]
        source = canonicalize_source_label(raw_source)
        if str(raw_source).strip().lower().replace("-", "_") in FORBIDDEN_SOURCE_LABELS or source in FORBIDDEN_SOURCE_LABELS:
            blockers.append(_blocker("POOL500_FORBIDDEN_SOURCE_LABEL", {"row_index": row_index, "source": raw_source, "canonical_source": source}))
            continue
        if source not in allowed_sources:
            blockers.append(_blocker("POOL500_NON_CANONICAL_SOURCE_LABEL", {"row_index": row_index, "source": raw_source, "canonical_source": source}))
            continue

        score = _coerce_score(row["score"])
        if score is None:
            blockers.append(_blocker("POOL500_NON_FINITE_SCORE", {"row_index": row_index, "user_id": user_id, "item_id": item_id, "source": source, "score": row["score"]}))
            continue
        rank = _coerce_rank(row["rank"])
        if rank is None:
            blockers.append(_blocker("POOL500_INVALID_RANK", {"row_index": row_index, "user_id": user_id, "item_id": item_id, "source": source, "rank": row["rank"]}))
            continue
        if not isinstance(row["metadata"], dict):
            blockers.append(_blocker("POOL500_METADATA_OBJECT_REQUIRED", {"row_index": row_index, "user_id": user_id, "item_id": item_id, "source": source, "metadata_type": type(row["metadata"]).__name__}))
            continue

        duplicate_key = (user_id, item_id, source)
        if duplicate_key in seen_user_item_source:
            blockers.append(_blocker("POOL500_DUPLICATE_USER_ITEM_SOURCE", {"row_index": row_index, "user_id": user_id, "item_id": item_id, "source": source}))
            continue
        seen_user_item_source.add(duplicate_key)

        metadata = dict(row["metadata"])
        category = str(row.get("category") or metadata.get("category") or "")
        if not metadata:
            diagnostics.append(_diagnostic("POOL500_EMPTY_METADATA", {"row_index": row_index, "user_id": user_id, "item_id": item_id, "source": source}))
        if not category:
            diagnostics.append(_diagnostic("POOL500_CATEGORY_MISSING", {"row_index": row_index, "user_id": user_id, "item_id": item_id, "source": source}))

        user_candidates = candidates_by_user[user_id]
        current = user_candidates.get(item_id)
        lineage = {"source": source, "score": score, "rank": rank, "metadata": metadata}
        if current is None:
            candidate_metadata = dict(metadata)
            candidate_metadata[POOL500_LINEAGE_KEY] = [lineage]
            candidate_metadata["pool500_source_metadata"] = {source: dict(metadata)}
            user_candidates[item_id] = MergedCandidate(
                item_id=item_id,
                sources=[source],
                source_scores={source: score},
                category=category,
                metadata=candidate_metadata,
            )
            continue

        current.sources.append(source)
        current.source_scores[source] = score
        if not current.category and category:
            current.category = category
        current.metadata.setdefault(POOL500_LINEAGE_KEY, []).append(lineage)
        _merge_metadata(current.metadata, metadata, source)

    candidates = {user_id: list(user_candidates.values()) for user_id, user_candidates in candidates_by_user.items()}
    for user_id, user_candidates in candidates.items():
        candidate_count = len(user_candidates)
        if candidate_count > candidate_pool_limit:
            blockers.append(_blocker("POOL500_USER_CANDIDATE_LIMIT_EXCEEDED", {"user_id": user_id, "candidate_count": candidate_count, "candidate_pool_limit": candidate_pool_limit}))
        if candidate_count < candidate_pool_limit:
            diagnostics.append(_diagnostic("POOL500_USER_CANDIDATE_POOL_UNDERFILLED", {"user_id": user_id, "candidate_count": candidate_count, "candidate_pool_limit": candidate_pool_limit}))

    return {
        "schema_version": SCHEMA_VERSION,
        "status": PASS if not blockers else STOP,
        "decision": PASS if not blockers else STOP,
        "candidate_pool_limit": candidate_pool_limit,
        "candidates_by_user": candidates,
        "blockers": blockers,
        "diagnostics": diagnostics,
    }


def adapt_pool500_jsonl_to_candidates(
    path: str | Path,
    *,
    candidate_pool_limit: int = DEFAULT_POOL_LIMIT,
    extra_allowed_sources: set[str] | None = None,
) -> dict[str, Any]:
    return adapt_pool500_rows_to_candidates(iter_jsonl(path), candidate_pool_limit=candidate_pool_limit, extra_allowed_sources=extra_allowed_sources)


def _validate_required_fields(row: dict[str, Any], row_index: int) -> list[dict[str, Any]]:
    missing = sorted(REQUIRED_ROW_FIELDS - set(row))
    if not missing:
        return []
    return [_blocker("POOL500_REQUIRED_FIELD_MISSING", {"row_index": row_index, "missing_fields": missing})]


def _coerce_score(value: Any) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(score):
        return None
    return score


def _coerce_rank(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        rank = int(value)
    except (TypeError, ValueError):
        return None
    if rank < 1:
        return None
    return rank


def _merge_metadata(target: dict[str, Any], source_metadata: dict[str, Any], source: str) -> None:
    per_source_metadata = target.setdefault("pool500_source_metadata", {})
    per_source_metadata[source] = dict(source_metadata)
    for key, value in source_metadata.items():
        target.setdefault(key, value)


def _blocker(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocker", "evidence": evidence}


def _diagnostic(code: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "diagnostic", "evidence": evidence}
