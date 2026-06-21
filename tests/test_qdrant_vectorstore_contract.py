from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from qdrant_fakes import install_fake_qdrant

from rs_core.recsys.vectorstores import (
    QDRANT_RAG_CHUNK_SCHEMA_VERSION,
    OptionalQdrantDependencyMissing,
    QdrantCollectionSpec,
    rag_chunk_payload,
    stable_qdrant_point_id,
    two_tower_item_payload,
)
from rs_core.recsys.vectorstores.qdrant_client import QdrantVectorStore, build_qdrant_client
from rs_core.recsys.vectorstores.qdrant_filters import item_id_match_any_filter, no_holdout_condition, schema_version_condition


def test_qdrant_vectorstore_upsert_query_and_candidate_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    spec = QdrantCollectionSpec(
        collection_name="test_rag_chunks",
        vector_size=3,
        schema_version=QDRANT_RAG_CHUNK_SCHEMA_VERSION,
    )
    store.ensure_collection(spec)
    store.upsert_points(
        collection_name=spec.collection_name,
        points=[
            (
                stable_qdrant_point_id("rag", "i1", "title", 0),
                [1.0, 0.0, 0.0],
                rag_chunk_payload(item_id="i1", field="title", text="red sofa", chunk_index=0),
            ),
            (
                stable_qdrant_point_id("rag", "i2", "title", 0),
                [0.0, 1.0, 0.0],
                rag_chunk_payload(item_id="i2", field="title", text="desk lamp", chunk_index=0),
            ),
        ],
    )

    hits = store.query_points(
        collection_name=spec.collection_name,
        query_vector=[1.0, 0.0, 0.0],
        limit=5,
        query_filter=item_id_match_any_filter(
            ["i2"],
            extra_must=[schema_version_condition(QDRANT_RAG_CHUNK_SCHEMA_VERSION), no_holdout_condition()],
        ),
    )

    assert [hit.item_id for hit in hits] == ["i2"]
    assert hits[0].payload["schema_version"] == QDRANT_RAG_CHUNK_SCHEMA_VERSION
    assert hits[0].payload["candidate_generation_allowed"] is False
    assert hits[0].payload["ranking_input_replacement_allowed"] is False
    assert hits[0].payload["promotion_allowed"] is False
    assert hits[0].payload["no_holdout"] is True


def test_qdrant_ensure_collection_rejects_existing_vector_size_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    store.ensure_collection(QdrantCollectionSpec(collection_name="test_existing_size", vector_size=3))

    with pytest.raises(ValueError, match="vector size mismatch"):
        store.ensure_collection(QdrantCollectionSpec(collection_name="test_existing_size", vector_size=2))


def test_qdrant_ensure_collection_rejects_existing_distance_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    store.ensure_collection(QdrantCollectionSpec(collection_name="test_existing_distance", vector_size=3, distance="COSINE"))

    with pytest.raises(ValueError, match="distance mismatch"):
        store.ensure_collection(QdrantCollectionSpec(collection_name="test_existing_distance", vector_size=3, distance="DOT"))


def test_qdrant_ensure_collection_propagates_non_missing_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)

    class BrokenClient:
        create_collection_called = False

        def get_collection(self, *, collection_name: str) -> dict[str, object]:
            raise RuntimeError("temporary qdrant outage")

        def create_collection(self, **kwargs: object) -> None:
            self.create_collection_called = True

    client = BrokenClient()
    store = QdrantVectorStore(client)

    with pytest.raises(RuntimeError, match="temporary qdrant outage"):
        store.ensure_collection(QdrantCollectionSpec(collection_name="test_error", vector_size=3))
    assert client.create_collection_called is False


def test_qdrant_ensure_collection_treats_not_found_value_error_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_qdrant(monkeypatch)

    class MissingCollectionClient:
        create_collection_called = False

        def get_collection(self, *, collection_name: str) -> dict[str, object]:
            raise ValueError(f"Collection {collection_name} not found")

        def create_collection(self, **kwargs: object) -> None:
            self.create_collection_called = True

    client = MissingCollectionClient()
    store = QdrantVectorStore(client)
    store.ensure_collection(QdrantCollectionSpec(collection_name="test_missing", vector_size=3))

    assert client.create_collection_called is True


def test_qdrant_payload_helpers_keep_governance_boundaries() -> None:
    rag_payload = rag_chunk_payload(item_id="i1", field="description", text="safe text", metadata={"chunk_index": 99})
    two_tower_payload = two_tower_item_payload(item_id="i2", metadata={"embedding": [1.0, 0.0], "category": "Audio"})

    assert rag_payload["schema_version"] == QDRANT_RAG_CHUNK_SCHEMA_VERSION
    assert rag_payload["artifact_scope"] == "candidate_internal"
    assert rag_payload["candidate_generation_allowed"] is False
    assert rag_payload["ranking_input_replacement_allowed"] is False
    assert rag_payload["promotion_allowed"] is False
    assert two_tower_payload["source_name"] == "two_tower"
    assert two_tower_payload["candidate_generation_allowed"] is True
    assert two_tower_payload["ranking_input_replacement_allowed"] is False
    assert "embedding" not in two_tower_payload


def test_qdrant_optional_dependency_error_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    original_import = builtins.__import__

    def blocked_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "qdrant_client":
            raise ImportError("blocked qdrant")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(OptionalQdrantDependencyMissing, match="qdrant-client is required"):
        build_qdrant_client(location=":memory:")
