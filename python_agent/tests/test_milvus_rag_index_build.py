from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.unit

from milvus_fakes import install_fake_milvus

from rs_core.common.io import write_json, write_jsonl
from rs_core.agent.rag.milvus_index import build_milvus_rag_chunk_index
from rs_core.data.vectorstores.milvus_client import MilvusVectorStore, build_milvus_client


class FakeEmbeddingBackend:
    def encode(self, texts: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        matrix = np.asarray([self._vector(text) for text in texts], dtype=np.float32)
        if normalize:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix = matrix / np.where(norms == 0.0, 1.0, norms)
        return matrix

    def encode_passages(self, passages: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        return self.encode(passages, normalize=normalize, batch_size=batch_size)

    def _vector(self, text: str) -> list[float]:
        value = text.lower()
        return [float("sofa" in value), float("lamp" in value), float("camp" in value)]


def test_build_milvus_rag_chunk_index_upserts_candidate_scoped_evidence(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    monkeypatch.setattr("rs_core.agent.rag.milvus_index.build_store", lambda _config: store)
    items_path = tmp_path / "canonical_items.jsonl"
    manifest_path = tmp_path / "milvus_rag_manifest.json"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_json(source_manifest_path, {"schema_version": "rag_catalog_manifest_v1", "train_only": True, "no_holdout": True})
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa"}, {"parent_asin": "i2", "title": "bright desk lamp"}])

    manifest = build_milvus_rag_chunk_index(
        items_path=items_path,
        collection_name="test_rag_build",
        milvus_config={"uri": "unit.db"},
        source_manifest_path=source_manifest_path,
        manifest_path=manifest_path,
        fields=["title"],
        embedding_backend=FakeEmbeddingBackend(),
        limit_items=2,
    )

    assert manifest["schema_version"] == "milvus_rag_chunk_index_manifest_v1"
    assert manifest["milvus_collection_schema_version"] == "milvus_rag_chunk_v1"
    assert manifest["chunk_count"] == 2
    assert manifest["upserted_chunk_count"] == 2
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["no_holdout"] is True
    assert manifest_path.is_file()
    rows = store.client.collections["test_rag_build"]["rows"]
    assert {row["item_id"] for row in rows} == {"i1", "i2"}
    assert {row["schema_version"] for row in rows} == {"milvus_rag_chunk_v1"}


def test_build_milvus_rag_chunk_index_dry_run_does_not_touch_milvus(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_milvus(monkeypatch)
    items_path = tmp_path / "canonical_items.jsonl"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa"}])
    write_json(source_manifest_path, {"schema_version": "unit_dataset_manifest_v1", "train_only": True, "no_holdout": True})

    def fail_build_store(_config):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run should not create a Milvus store")

    monkeypatch.setattr("rs_core.agent.rag.milvus_index.build_store", fail_build_store)
    manifest = build_milvus_rag_chunk_index(items_path=items_path, collection_name="test_rag_dry_run", source_manifest_path=source_manifest_path, fields=["title"], dry_run=True)

    assert manifest["dry_run"] is True
    assert manifest["chunk_count"] == 1
    assert manifest["upserted_chunk_count"] == 0
    assert manifest["vector_size"] is None


def test_build_milvus_rag_chunk_index_requires_explicit_live_target(tmp_path) -> None:
    items_path = tmp_path / "canonical_items.jsonl"
    source_manifest_path = tmp_path / "dataset_manifest.json"
    write_jsonl(items_path, [{"parent_asin": "i1", "title": "soft red sofa"}])
    write_json(source_manifest_path, {"schema_version": "unit_dataset_manifest_v1", "train_only": True, "no_holdout": True})

    with pytest.raises(ValueError, match="explicit target"):
        build_milvus_rag_chunk_index(items_path=items_path, collection_name="test_missing_target", source_manifest_path=source_manifest_path, fields=["title"], embedding_backend=FakeEmbeddingBackend())
