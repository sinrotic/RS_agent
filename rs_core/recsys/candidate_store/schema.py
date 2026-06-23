from __future__ import annotations

from typing import Any

from rs_core.recsys.types import RecallCandidate


def row_to_recall_candidate(row: dict[str, Any], *, default_source: str) -> RecallCandidate | None:
    item_id = str(row.get("parent_asin") or row.get("item_id") or row.get("dst_item_id") or "").strip()
    if not item_id:
        return None
    source = str(row.get("source") or default_source)
    try:
        score = float(row.get("score", 0.0) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    rank = row.get("rank")
    if rank not in (None, ""):
        metadata = dict(metadata) | {f"{source}_rank": rank}
    if row.get("src_item_id"):
        metadata = dict(metadata) | {"seed_item_id": str(row.get("src_item_id"))}
    if row.get("artifact_id"):
        metadata = dict(metadata) | {"candidate_store_artifact_id": str(row.get("artifact_id"))}
    metadata.setdefault("online_candidate_store", True)
    return RecallCandidate(
        item_id=item_id,
        source=source,
        score=score,
        category=str(row.get("category") or metadata.get("category") or ""),
        metadata=metadata,
    )
