from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.unit

from qdrant_fakes import install_fake_qdrant

from rs_core.recsys.rag import RagPolicy, build_rag_context_for_ranked_candidates
from rs_core.recsys.rag.qdrant_vector import QdrantCandidateRagVectorRetriever
from rs_core.recsys.vectorstores import QDRANT_RAG_CHUNK_SCHEMA_VERSION, QdrantCollectionSpec, rag_chunk_payload, stable_qdrant_point_id
from rs_core.recsys.vectorstores.qdrant_client import QdrantVectorStore, build_qdrant_client


class FakeEmbeddingBackend:
    def encode(self, texts: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        matrix = np.asarray([self._vector(text) for text in texts], dtype=np.float32)
        if normalize:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix = matrix / np.where(norms == 0.0, 1.0, norms)
        return matrix

    def encode_query(self, query: str, *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        return self.encode([query], normalize=normalize, batch_size=batch_size)[0]

    def _vector(self, text: str) -> list[float]:
        value = text.lower()
        return [
            float(any(token in value for token in ("sofa", "couch", "seat"))),
            float(any(token in value for token in ("lamp", "light"))),
            float(any(token in value for token in ("camp", "kettle"))),
        ]


def test_qdrant_rag_retriever_preserves_candidate_scope_and_policy_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    collection_name = "test_qdrant_rag"
    store.ensure_collection(
        QdrantCollectionSpec(
            collection_name=collection_name,
            vector_size=3,
            schema_version=QDRANT_RAG_CHUNK_SCHEMA_VERSION,
        )
    )
    store.upsert_points(
        collection_name=collection_name,
        points=[
            (
                stable_qdrant_point_id("rag", "i1", "title", 0),
                [1.0, 0.0, 0.0],
                rag_chunk_payload(item_id="i1", field="title", text="soft sofa seat", chunk_index=0),
            ),
            (
                stable_qdrant_point_id("rag", "outside", "title", 0),
                [1.0, 0.0, 0.0],
                rag_chunk_payload(item_id="outside", field="title", text="outside sofa", chunk_index=0),
            ),
            (
                stable_qdrant_point_id("rag", "i1", "description", 1),
                [1.0, 0.0, 0.0],
                rag_chunk_payload(
                    item_id="i1",
                    field="description",
                    text="leaky label text",
                    source="offline_eval_label",
                    chunk_index=1,
                    metadata={"source_path": "holdout/target.json"},
                ),
            ),
        ],
    )
    retriever = QdrantCandidateRagVectorRetriever(
        store=store,
        collection_name=collection_name,
        embedding_backend=FakeEmbeddingBackend(),
    )

    context = build_rag_context_for_ranked_candidates(
        query="sofa seating",
        candidate_item_ids=["i1"],
        retriever=retriever,
        policy=RagPolicy(mode="explain", max_evidence_per_item=3, max_evidence_total=3),
    )

    assert [(row.item_id, row.field, row.text) for row in context.evidence] == [("i1", "title", "soft sofa seat")]
    diagnostics = context.metadata["rag_diagnostics"]
    assert diagnostics["dropped_non_candidate_evidence_count"] == 0
    assert diagnostics["dropped_policy_violation_count"] == 1
    assert diagnostics["policy_violations"][0]["tokens"] == ["eval", "holdout", "label", "target"]
    metadata = context.evidence[0].metadata
    assert metadata["retriever"] == "qdrant_vector"
    assert metadata["candidate_scoped"] is True
    assert metadata["candidate_generation_allowed"] is False
    assert metadata["ranking_input_replacement_allowed"] is False
    assert metadata["promotion_allowed"] is False
    assert "text" not in metadata
