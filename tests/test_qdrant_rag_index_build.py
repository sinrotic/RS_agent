from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.unit

from qdrant_fakes import install_fake_qdrant

from rs_core.common.io import write_json, write_jsonl
from rs_core.recsys.rag.qdrant_index import build_qdrant_rag_chunk_index
from rs_core.recsys.rag.qdrant_vector import QdrantCandidateRagVectorRetriever
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

    def encode_passages(self, passages: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        return self.encode(passages, normalize=normalize, batch_size=batch_size)

    def _vector(self, text: str) -> list[float]:
        value = text.lower()
        return [
            float(any(token in value for token in ("sofa", "seat"))),
            float(any(token in value for token in ("lamp", "light"))),
            float(any(token in value for token in ("camp", "kettle"))),
        ]


def test_build_qdrant_rag_chunk_index_upserts_candidate_scoped_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_qdrant(monkeypatch)
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    monkeypatch.setattr("rs_core.recsys.rag.qdrant_index.build_store", lambda _config: store)
    items_path = tmp_path / "canonical_items.jsonl"
    manifest_path = tmp_path / "qdrant_rag_manifest.json"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_json(source_manifest_path, {"schema_version": "rag_catalog_manifest_v1", "train_only": True, "no_holdout": True})
    write_jsonl(
        items_path,
        [
            {"parent_asin": "i1", "title": "soft red sofa seat", "main_category": "Home"},
            {"parent_asin": "i2", "title": "bright desk lamp", "main_category": "Lighting"},
        ],
    )

    manifest = build_qdrant_rag_chunk_index(
        items_path=items_path,
        collection_name="test_rag_build",
        qdrant_config={"location": ":memory:"},
        source_manifest_path=source_manifest_path,
        manifest_path=manifest_path,
        fields=["title"],
        embedding_backend=FakeEmbeddingBackend(),
        limit_items=2,
    )

    assert manifest["schema_version"] == "qdrant_rag_chunk_index_manifest_v1"
    assert manifest["qdrant_collection_schema_version"] == "qdrant_rag_chunk_v1"
    assert manifest["chunk_count"] == 2
    assert manifest["upserted_chunk_count"] == 2
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["no_holdout"] is True
    assert manifest_path.is_file()

    retriever = QdrantCandidateRagVectorRetriever(
        store=store,
        collection_name="test_rag_build",
        embedding_backend=FakeEmbeddingBackend(),
    )
    evidence = retriever.retrieve("sofa seating", ["i1"], max_evidence_per_item=1)

    assert [(row.item_id, row.field, row.text) for row in evidence] == [("i1", "title", "soft red sofa seat")]
    assert evidence[0].metadata["candidate_scoped"] is True
    assert evidence[0].metadata["candidate_generation_allowed"] is False


def test_build_qdrant_rag_chunk_index_dry_run_does_not_touch_qdrant(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_qdrant(monkeypatch)
    items_path = tmp_path / "canonical_items.jsonl"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    output_manifest_path = tmp_path / "dry_run_manifest.json"
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa seat"}])
    write_json(source_manifest_path, {"schema_version": "unit_dataset_manifest_v1", "train_only": True, "no_holdout": True})

    def fail_build_store(_config):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run should not create a Qdrant store")

    monkeypatch.setattr("rs_core.recsys.rag.qdrant_index.build_store", fail_build_store)
    manifest = build_qdrant_rag_chunk_index(
        items_path=items_path,
        collection_name="test_rag_dry_run",
        source_manifest_path=source_manifest_path,
        manifest_path=output_manifest_path,
        fields=["title"],
        dry_run=True,
    )

    assert manifest["dry_run"] is True
    assert manifest["chunk_count"] == 1
    assert manifest["upserted_chunk_count"] == 0
    assert manifest["vector_size"] is None
    assert manifest["source_manifest_path"] == str(source_manifest_path.resolve())
    assert output_manifest_path.is_file()


def test_build_qdrant_rag_chunk_index_rejects_bad_batch_before_qdrant(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_qdrant(monkeypatch)
    items_path = tmp_path / "canonical_items.jsonl"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa seat"}])
    write_json(source_manifest_path, {"schema_version": "unit_dataset_manifest_v1", "train_only": True, "no_holdout": True})

    def fail_build_store(_config):  # type: ignore[no-untyped-def]
        raise AssertionError("invalid batch size should fail before Qdrant store creation")

    monkeypatch.setattr("rs_core.recsys.rag.qdrant_index.build_store", fail_build_store)

    with pytest.raises(ValueError, match="batch_size"):
        build_qdrant_rag_chunk_index(
            items_path=items_path,
            collection_name="test_rag_bad_batch",
            qdrant_config={"location": ":memory:"},
            source_manifest_path=source_manifest_path,
            fields=["title"],
            embedding_backend=FakeEmbeddingBackend(),
            batch_size=0,
        )


def test_build_qdrant_rag_chunk_index_requires_explicit_train_no_holdout(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_qdrant(monkeypatch)
    items_path = tmp_path / "canonical_items.jsonl"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa seat"}])
    write_json(source_manifest_path, {"schema_version": "unit_dataset_manifest_v1", "train_only": True})

    with pytest.raises(ValueError, match="train_only=true and no_holdout=true"):
        build_qdrant_rag_chunk_index(
            items_path=items_path,
            collection_name="test_rag_missing_no_holdout",
            qdrant_config={"location": ":memory:"},
            source_manifest_path=source_manifest_path,
            fields=["title"],
            embedding_backend=FakeEmbeddingBackend(),
        )


def test_build_qdrant_rag_chunk_index_rejects_nested_forbidden_manifest_path(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_qdrant(monkeypatch)
    items_path = tmp_path / "canonical_items.jsonl"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa seat"}])
    write_json(
        source_manifest_path,
        {
            "schema_version": "unit_dataset_manifest_v1",
            "train_only": True,
            "no_holdout": True,
            "inputs": {"items_path": "data/holdout/catalog.jsonl"},
        },
    )

    with pytest.raises(ValueError, match="forbidden"):
        build_qdrant_rag_chunk_index(
            items_path=items_path,
            collection_name="test_rag_nested_forbidden",
            qdrant_config={"location": ":memory:"},
            source_manifest_path=source_manifest_path,
            fields=["title"],
            embedding_backend=FakeEmbeddingBackend(),
        )


def test_build_qdrant_rag_chunk_index_deletes_stale_chunks_after_rebuild(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_qdrant(monkeypatch)
    store = QdrantVectorStore(build_qdrant_client(location=":memory:"))
    monkeypatch.setattr("rs_core.recsys.rag.qdrant_index.build_store", lambda _config: store)
    items_path = tmp_path / "canonical_items.jsonl"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_json(source_manifest_path, {"schema_version": "unit_dataset_manifest_v1", "train_only": True, "no_holdout": True})
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa seat", "description": "extra stale sofa detail"}])

    build_qdrant_rag_chunk_index(
        items_path=items_path,
        collection_name="test_rag_stale_rebuild",
        qdrant_config={"location": ":memory:"},
        source_manifest_path=source_manifest_path,
        fields=["title", "description"],
        embedding_backend=FakeEmbeddingBackend(),
    )
    build_qdrant_rag_chunk_index(
        items_path=items_path,
        collection_name="test_rag_stale_rebuild",
        qdrant_config={"location": ":memory:"},
        source_manifest_path=source_manifest_path,
        fields=["title"],
        embedding_backend=FakeEmbeddingBackend(),
    )

    points = store.client.collections["test_rag_stale_rebuild"]["points"]
    assert [(point.payload["item_id"], point.payload["field"]) for point in points] == [("i1", "title")]
