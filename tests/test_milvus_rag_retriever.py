from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.unit

from milvus_fakes import install_fake_milvus

from rs_core.agent.rag import RagPolicy, build_rag_context_for_ranked_candidates
from rs_core.agent.rag.milvus_vector import MilvusCandidateRagVectorRetriever
from rs_core.recsys.vectorstores.milvus_client import MilvusVectorStore, build_milvus_client
from rs_core.recsys.vectorstores.milvus_contracts import MILVUS_RAG_CHUNK_SCHEMA_VERSION, MilvusCollectionSpec, milvus_payload_for_schema
from rs_core.recsys.vectorstores.payloads import rag_chunk_payload, stable_vector_point_id


def _milvus_payload(payload: dict, *, no_holdout: bool = True) -> dict:
    row = milvus_payload_for_schema(payload, MILVUS_RAG_CHUNK_SCHEMA_VERSION)
    row["no_holdout"] = no_holdout
    return row


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


def test_milvus_rag_retriever_preserves_candidate_scope_and_policy_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    collection_name = "test_milvus_rag"
    store.ensure_collection(MilvusCollectionSpec(collection_name=collection_name, vector_size=3, schema_version=MILVUS_RAG_CHUNK_SCHEMA_VERSION))
    store.upsert_points(
        collection_name=collection_name,
        points=[
            (
                stable_vector_point_id("milvus_rag", "i1", "title", 0),
                [1.0, 0.0, 0.0],
                _milvus_payload(rag_chunk_payload(item_id="i1", field="title", text="soft sofa seat", chunk_index=0)),
            ),
            (
                stable_vector_point_id("milvus_rag", "outside", "title", 0),
                [1.0, 0.0, 0.0],
                _milvus_payload(rag_chunk_payload(item_id="outside", field="title", text="outside sofa", chunk_index=0)),
            ),
            (
                stable_vector_point_id("milvus_rag", "i1", "description", 1),
                [1.0, 0.0, 0.0],
                _milvus_payload(
                    rag_chunk_payload(
                        item_id="i1",
                        field="description",
                        text="leaky label text",
                        source="offline_eval_label",
                        chunk_index=1,
                        metadata={"source_path": "holdout/target.json"},
                    )
                ),
            ),
            (
                stable_vector_point_id("milvus_rag", "i1", "features", 2),
                [1.0, 0.0, 0.0],
                _milvus_payload(
                    rag_chunk_payload(item_id="i1", field="features", text="holdout sofa", chunk_index=2),
                    no_holdout=False,
                ),
            ),
        ],
    )
    retriever = MilvusCandidateRagVectorRetriever(
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
    metadata = context.evidence[0].metadata
    assert metadata["retriever"] == "milvus_vector"
    assert metadata["candidate_scoped"] is True
    assert metadata["candidate_generation_allowed"] is False
    assert metadata["ranking_input_replacement_allowed"] is False
    assert metadata["promotion_allowed"] is False
    assert metadata["schema_version"] == MILVUS_RAG_CHUNK_SCHEMA_VERSION
    assert "text" not in metadata
    assert "vector" not in metadata


def test_milvus_rag_retriever_empty_query_or_candidates_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    retriever = MilvusCandidateRagVectorRetriever(store=store, embedding_backend=FakeEmbeddingBackend())

    assert retriever.retrieve("", ["i1"]) == []
    assert retriever.retrieve("sofa", []) == []
