from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from milvus_fakes import install_fake_milvus

from rs_core.data.vectorstores.milvus_client import SEARCH_OUTPUT_FIELDS, MilvusVectorStore, build_milvus_client
from rs_core.data.vectorstores.milvus_contracts import MILVUS_RAG_CHUNK_SCHEMA_VERSION, MilvusCollectionSpec, OptionalMilvusDependencyMissing, milvus_payload_for_schema
from rs_core.data.vectorstores.milvus_filters import item_id_match_any_expr, no_holdout_expr, schema_version_expr
from rs_core.data.vectorstores.payloads import rag_chunk_payload, stable_vector_point_id


def test_milvus_vectorstore_upsert_query_and_candidate_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    spec = MilvusCollectionSpec(collection_name="test_rag_chunks", vector_size=3, schema_version=MILVUS_RAG_CHUNK_SCHEMA_VERSION)
    store.ensure_collection(spec)
    store.upsert_points(
        collection_name=spec.collection_name,
        points=[
            (
                stable_vector_point_id("milvus_rag", "i1", "title", 0),
                [1.0, 0.0, 0.0],
                milvus_payload_for_schema(rag_chunk_payload(item_id="i1", field="title", text="red sofa", chunk_index=0), MILVUS_RAG_CHUNK_SCHEMA_VERSION),
            ),
            (
                stable_vector_point_id("milvus_rag", "i2", "title", 0),
                [0.0, 1.0, 0.0],
                milvus_payload_for_schema(rag_chunk_payload(item_id="i2", field="title", text="desk lamp", chunk_index=0), MILVUS_RAG_CHUNK_SCHEMA_VERSION),
            ),
        ],
    )

    hits = store.query_points(
        collection_name=spec.collection_name,
        query_vector=[1.0, 0.0, 0.0],
        limit=5,
        query_filter=item_id_match_any_expr(["i2"], extra_must=[schema_version_expr(MILVUS_RAG_CHUNK_SCHEMA_VERSION), no_holdout_expr()]),
    )

    assert [hit.item_id for hit in hits] == ["i2"]
    assert store.client.last_search_output_fields == SEARCH_OUTPUT_FIELDS
    assert hits[0].payload["schema_version"] == MILVUS_RAG_CHUNK_SCHEMA_VERSION
    assert hits[0].payload["candidate_generation_allowed"] is False
    assert hits[0].payload["ranking_input_replacement_allowed"] is False
    assert hits[0].payload["promotion_allowed"] is False
    assert hits[0].payload["no_holdout"] is True


def test_milvus_ensure_collection_rejects_existing_vector_size_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    store.ensure_collection(MilvusCollectionSpec(collection_name="test_existing_size", vector_size=3))

    with pytest.raises(ValueError, match="vector size mismatch"):
        store.ensure_collection(MilvusCollectionSpec(collection_name="test_existing_size", vector_size=2))


def test_milvus_ensure_collection_rejects_existing_metric_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    store.ensure_collection(MilvusCollectionSpec(collection_name="test_existing_metric", vector_size=3, metric_type="COSINE"))

    with pytest.raises(ValueError, match="metric type mismatch"):
        store.ensure_collection(MilvusCollectionSpec(collection_name="test_existing_metric", vector_size=3, metric_type="IP"))


def test_milvus_optional_dependency_error_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "pymilvus":
            raise ImportError("blocked pymilvus")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(OptionalMilvusDependencyMissing, match="pymilvus is required"):
        build_milvus_client(uri="unit.db")
