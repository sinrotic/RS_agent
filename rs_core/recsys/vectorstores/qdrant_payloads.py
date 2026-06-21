from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, uuid5

from rs_core.recsys.vectorstores.qdrant_contracts import (
    QDRANT_RAG_CHUNK_SCHEMA_VERSION,
    QDRANT_SEMANTIC_VECTOR_ITEM_SCHEMA_VERSION,
    QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION,
)


def stable_qdrant_point_id(*parts: Any) -> str:
    raw = ":".join(str(part).strip() for part in parts if str(part).strip())
    if not raw:
        raise ValueError("at least one non-empty point id part is required")
    return str(uuid5(NAMESPACE_URL, f"rs-agent:qdrant:{raw}"))


def rag_chunk_payload(
    *,
    item_id: str,
    field: str,
    text: str,
    source: str = "catalog_rag_chunk",
    chunk_index: int = 0,
    corpus_scope: str = "product_catalog",
    embedding_method: str = "sentence_transformer_dense_v1",
    embedding_model_name: str | None = None,
    index_build_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload.update(
        {
            "schema_version": QDRANT_RAG_CHUNK_SCHEMA_VERSION,
            "item_id": str(item_id),
            "field": str(field),
            "text": str(text),
            "source": str(source or "catalog_rag_chunk"),
            "corpus_scope": str(corpus_scope),
            "chunk_index": int(chunk_index),
            "embedding_method": str(embedding_method),
            "embedding_model_name": embedding_model_name,
            "index_build_id": str(index_build_id or ""),
            "artifact_scope": "candidate_internal",
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "no_holdout": True,
        }
    )
    return payload


def two_tower_item_payload(
    *,
    item_id: str,
    source_name: str = "two_tower",
    index_build_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {key: value for key, value in dict(metadata or {}).items() if key != "embedding"}
    payload.update(
        {
            "schema_version": QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION,
            "item_id": str(item_id),
            "source_name": str(source_name or "two_tower"),
            "artifact_type": payload.get("artifact_type", "two_tower_recall_index"),
            "index_build_id": str(index_build_id or ""),
            "candidate_generation_allowed": True,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "train_only": True,
            "no_holdout": True,
        }
    )
    return payload


def semantic_vector_item_payload(
    *,
    item_id: str,
    embedding_method: str,
    embedding_model_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {key: value for key, value in dict(metadata or {}).items() if key != "embedding"}
    payload.update(
        {
            "schema_version": QDRANT_SEMANTIC_VECTOR_ITEM_SCHEMA_VERSION,
            "item_id": str(item_id),
            "source_name": "semantic_vector",
            "embedding_method": str(embedding_method),
            "embedding_model_name": embedding_model_name,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "experimental": True,
            "no_holdout": True,
        }
    )
    return payload
