from __future__ import annotations

from typing import Any

from rs_core.agent.rag.schema import RagContext


def build_empty_rag_context(
    query: str,
    candidate_item_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> RagContext:
    return RagContext(
        query=query,
        candidate_item_ids=list(candidate_item_ids or []),
        evidence=[],
        metadata=dict(metadata or {}),
    )
