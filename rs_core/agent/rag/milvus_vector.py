from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np

from rs_core.agent.rag.schema import RagEvidence
from rs_core.agent.rag.vector_index import (
    DEFAULT_DENSE_MODEL_NAME,
    RAG_RETRIEVAL_SCOPE,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    SentenceTransformerEmbeddingBackend,
    TextEmbeddingBackend,
)
from rs_core.recsys.vectorstores.milvus_client import MilvusVectorStore
from rs_core.recsys.vectorstores.milvus_contracts import (
    DEFAULT_MILVUS_RAG_CHUNK_COLLECTION,
    MILVUS_RAG_CHUNK_SCHEMA_VERSION,
)
from rs_core.recsys.vectorstores.milvus_filters import item_id_match_any_expr, no_holdout_expr, schema_version_expr


@dataclass
class MilvusCandidateRagVectorRetriever:
    store: MilvusVectorStore
    collection_name: str = DEFAULT_MILVUS_RAG_CHUNK_COLLECTION
    embedding_backend: TextEmbeddingBackend | None = None
    embedding_model_name: str = DEFAULT_DENSE_MODEL_NAME
    embedding_method: str = SENTENCE_TRANSFORMER_VECTOR_METHOD
    query_prefix: str = ""
    embedding_batch_size: int = 32
    normalize_embeddings: bool = True
    top_k_multiplier: int = 4
    schema_version: str = MILVUS_RAG_CHUNK_SCHEMA_VERSION
    exclude_holdout: bool = True

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        candidate_ids = [str(item_id) for item_id in candidate_item_ids if str(item_id)]
        if not query or not candidate_ids:
            return []
        query_vector = _query_vector(
            query,
            embedding_backend=self.embedding_backend,
            embedding_model_name=self.embedding_model_name,
            query_prefix=self.query_prefix,
            normalize=self.normalize_embeddings,
            batch_size=self.embedding_batch_size,
        )
        limit = max(len(candidate_ids) * max(max_evidence_per_item, 1) * max(self.top_k_multiplier, 1), 20)
        extra_must = [schema_version_expr(self.schema_version)]
        if self.exclude_holdout:
            extra_must.append(no_holdout_expr())
        query_filter = item_id_match_any_expr(candidate_ids, extra_must=extra_must)
        hits = self.store.query_points(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            query_filter=query_filter,
        )
        evidence: list[RagEvidence] = []
        for hit in hits:
            payload = dict(hit.payload)
            item_id = str(payload.get("item_id") or hit.item_id)
            field = str(payload.get("field") or "")
            text = str(payload.get("text") or "")
            if not item_id or not field or not text:
                continue
            metadata = _public_rag_metadata(payload)
            metadata.update(
                {
                    "retriever": "milvus_vector",
                    "vector_method": self.embedding_method,
                    "vector_score": hit.score,
                    "embedding_model_name": payload.get("embedding_model_name") or self.embedding_model_name,
                    "retrieval_scope": RAG_RETRIEVAL_SCOPE,
                    "candidate_scoped": True,
                    "candidate_generation_allowed": False,
                    "ranking_input_replacement_allowed": False,
                    "promotion_allowed": False,
                    "artifact_scope": "candidate_internal",
                }
            )
            evidence.append(
                RagEvidence(
                    item_id=item_id,
                    field=field,
                    text=text,
                    source=str(payload.get("source_name") or payload.get("source") or "catalog_rag_chunk"),
                    score=hit.score,
                    metadata=metadata,
                )
            )
        return evidence


def _query_vector(
    query: str,
    *,
    embedding_backend: TextEmbeddingBackend | None,
    embedding_model_name: str,
    query_prefix: str,
    normalize: bool,
    batch_size: int,
) -> list[float]:
    backend = embedding_backend or SentenceTransformerEmbeddingBackend(
        model_name=embedding_model_name,
        query_prefix=query_prefix,
    )
    if hasattr(backend, "encode_query"):
        vector = backend.encode_query(query, normalize=normalize, batch_size=batch_size)  # type: ignore[attr-defined]
    else:
        vector = backend.encode([f"{query_prefix}{query}"], normalize=normalize, batch_size=batch_size)[0]
    return [float(value) for value in np.asarray(vector, dtype=np.float32).tolist()]


def _public_rag_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    blocked = {"text", "embedding", "vector"}
    return {str(key): value for key, value in payload.items() if key not in blocked}
