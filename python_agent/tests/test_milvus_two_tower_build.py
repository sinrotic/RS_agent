from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from milvus_fakes import install_fake_milvus

from rs_core.common.io import write_json, write_jsonl
from rs_core.data.vectorstores.milvus_client import MilvusVectorStore, build_milvus_client
from rs_core.online.recall.vectorstores.milvus_two_tower_build import build_milvus_two_tower_item_index


def test_build_milvus_two_tower_item_index_validates_manifest_and_upserts(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    monkeypatch.setattr("rs_core.online.recall.vectorstores.milvus_two_tower_build.build_store", lambda _config: store)
    manifest_path = _write_youtube_source_manifest(tmp_path)

    manifest = build_milvus_two_tower_item_index(
        source_index_manifest_path=manifest_path,
        collection_name="test_two_tower_build",
        milvus_config={"uri": "unit.db"},
        manifest_path=tmp_path / "milvus_two_tower_manifest.json",
        limit_items=2,
    )

    assert manifest["schema_version"] == "milvus_two_tower_item_index_manifest_v1"
    assert manifest["milvus_collection_schema_version"] == "milvus_two_tower_item_v1"
    assert manifest["source_manifest_validated"] is True
    assert manifest["item_count"] == 3
    assert manifest["selected_item_count"] == 2
    assert manifest["upserted_item_count"] == 2
    assert manifest["stale_points_deleted_for_source"] is True
    assert manifest["candidate_generation_allowed"] is True
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["train_only"] is True
    assert manifest["no_holdout"] is True
    rows = store.client.collections["test_two_tower_build"]["rows"]
    assert {row["item_id"] for row in rows} == {"seed", "match"}
    assert {row["schema_version"] for row in rows} == {"milvus_two_tower_item_v1"}


def test_build_milvus_two_tower_item_index_dry_run_does_not_touch_milvus(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_milvus(monkeypatch)
    manifest_path = _write_youtube_source_manifest(tmp_path)

    def fail_build_store(_config):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run should not create a Milvus store")

    monkeypatch.setattr("rs_core.online.recall.vectorstores.milvus_two_tower_build.build_store", fail_build_store)
    manifest = build_milvus_two_tower_item_index(source_index_manifest_path=manifest_path, collection_name="test_two_tower_dry_run", limit_items=1, dry_run=True)

    assert manifest["dry_run"] is True
    assert manifest["selected_item_count"] == 1
    assert manifest["upserted_item_count"] == 0
    assert manifest["vector_size"] == 2


def test_build_milvus_two_tower_item_index_zero_row_rebuild_preserves_existing_items(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    install_fake_milvus(monkeypatch)
    store = MilvusVectorStore(build_milvus_client(uri="unit.db"))
    monkeypatch.setattr("rs_core.online.recall.vectorstores.milvus_two_tower_build.build_store", lambda _config: store)
    uuids = iter([type("FakeUuid", (), {"hex": "build-1"})(), type("FakeUuid", (), {"hex": "build-2"})()])
    monkeypatch.setattr("rs_core.online.recall.vectorstores.milvus_two_tower_build.uuid4", lambda: next(uuids))
    manifest_path = _write_youtube_source_manifest(tmp_path)

    build_milvus_two_tower_item_index(source_index_manifest_path=manifest_path, collection_name="test_zero", milvus_config={"uri": "unit.db"})
    manifest = build_milvus_two_tower_item_index(source_index_manifest_path=manifest_path, collection_name="test_zero", milvus_config={"uri": "unit.db"}, limit_items=0)

    assert manifest["selected_item_count"] == 0
    assert manifest["stale_points_deleted_for_source"] is False
    assert {row["item_id"] for row in store.client.collections["test_zero"]["rows"]} == {"seed", "match", "other"}


def test_build_milvus_two_tower_item_index_rejects_limited_durable_live_build(tmp_path) -> None:
    manifest_path = _write_youtube_source_manifest(tmp_path)

    with pytest.raises(ValueError, match="limit-items"):
        build_milvus_two_tower_item_index(source_index_manifest_path=manifest_path, collection_name="test_limited", milvus_config={"uri": "http://localhost:19530"}, limit_items=1)


def _write_youtube_source_manifest(tmp_path) -> object:
    index_path = tmp_path / "two_tower_recall_index.jsonl"
    embedding_path = tmp_path / "item_embeddings.jsonl"
    rows = [
        {"parent_asin": "seed", "embedding": [1.0, 0.0], "category": "Audio"},
        {"parent_asin": "match", "embedding": [0.99, 0.01], "category": "Audio"},
        {"parent_asin": "other", "embedding": [0.0, 1.0], "category": "Lighting"},
    ]
    write_jsonl(index_path, rows)
    write_jsonl(embedding_path, rows)
    manifest_path = tmp_path / "source_index_manifest.json"
    write_json(manifest_path, _base_manifest(tmp_path))
    return manifest_path


def _base_manifest(tmp_path) -> dict[str, object]:
    return {
        "schema_version": "two_tower_source_index_v1",
        "source": "two_tower",
        "canonical_source": "two_tower",
        "source_name": "two_tower_youtube_dnn",
        "variant": "youtube_dnn",
        "model_type": "youtube_dnn_two_tower_v1",
        "index_scope": "FULL_DERIVED_INDEX",
        "source_status": "FULL_DERIVED_INDEX_DIAGNOSTIC",
        "train_only": True,
        "no_holdout": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "ranking_replacement_allowed": False,
        "pool1000_allowed": False,
        "promotion_allowed": False,
        "final_pool500_ready_claimed": False,
        "row_count": 3,
        "embedding_row_count": 3,
        "index_row_count": 3,
        "embedding_path": str(tmp_path / "item_embeddings.jsonl"),
        "index_path": str(tmp_path / "two_tower_recall_index.jsonl"),
    }
