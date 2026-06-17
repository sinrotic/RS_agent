from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.common.io import write_json, write_jsonl
from rs_core.recsys.two_tower_DSSM.source_manifest import validate_two_tower_dssm_source_index_manifest

pytestmark = pytest.mark.unit


def test_two_tower_dssm_source_manifest_success(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")

    manifest = validate_two_tower_dssm_source_index_manifest(manifest_path)

    assert manifest["schema_version"] == "two_tower_dssm_source_index_v1"
    assert manifest["source"] == "two_tower_dssm"
    assert manifest["canonical_source"] == "two_tower_dssm"
    assert manifest["source_name"] == "two_tower_dssm"
    assert manifest["variant"] == "dssm"
    assert manifest["model_type"] == "dssm_two_tower_v1"
    assert manifest["source_status"] == "FULL_DERIVED_INDEX_DIAGNOSTIC"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False


def test_two_tower_dssm_source_manifest_rejects_wrong_variant(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["variant"] = "youtube_dnn"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="variant"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_forbidden_path(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    forbidden_dir = tmp_path / "oracle" / "source"
    forbidden_dir.mkdir(parents=True)
    forbidden_index = forbidden_dir / "recall_index.jsonl"
    write_jsonl(forbidden_index, [{"parent_asin": "A", "embedding": [1.0, 0.0]}])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["index_path"] = str(forbidden_index)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_row_count_mismatch(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["index_row_count"] = 3
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="row_count"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_item_vocab_test_reference(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    item_vocab_manifest_path = tmp_path / "source" / "two_tower_dssm_item_vocab_manifest.json"
    item_vocab_manifest = json.loads(item_vocab_manifest_path.read_text(encoding="utf-8"))
    item_vocab_manifest["source_paths"]["canonical_interactions_train"] = str(tmp_path / "source" / "canonical_interactions.test.jsonl")
    item_vocab_manifest_path.write_text(json.dumps(item_vocab_manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden|canonical_interactions_train"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_item_vocab_eval_label_reference(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    item_vocab_manifest_path = tmp_path / "source" / "two_tower_dssm_item_vocab_manifest.json"
    item_vocab_manifest = json.loads(item_vocab_manifest_path.read_text(encoding="utf-8"))
    item_vocab_manifest["source_paths"]["eval_labels"] = str(tmp_path / "source" / "eval_label.jsonl")
    item_vocab_manifest_path.write_text(json.dumps(item_vocab_manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_missing_item_id(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source", rows=[{"embedding": [1.0, 0.0]}])

    with pytest.raises(ValueError, match="missing item id"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_missing_embedding(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source", rows=[{"parent_asin": "A", "item_id": "A"}])

    with pytest.raises(ValueError, match="missing embedding"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_embedding_dimension_mismatch(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(
        tmp_path / "source",
        rows=[
            {"parent_asin": "A", "item_id": "A", "embedding": [1.0, 0.0]},
            {"parent_asin": "B", "item_id": "B", "embedding": [0.0, 1.0, 0.0]},
        ],
    )

    with pytest.raises(ValueError, match="dimension mismatch"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_validates_user_embedding_dimensions(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    user_embeddings = tmp_path / "source" / "user_embeddings.jsonl"
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0, 0.0]}])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_embedding_path"] = str(user_embeddings)
    manifest["user_embedding_row_count"] = 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="user_embedding_path.*dimension mismatch"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_validates_user_embedding_row_count(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    user_embeddings = tmp_path / "source" / "user_embeddings.jsonl"
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0]}])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_embedding_path"] = str(user_embeddings)
    manifest["user_embedding_row_count"] = 2
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="user_embedding_path row count"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_non_finite_user_embedding(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    user_embeddings = tmp_path / "source" / "user_embeddings.jsonl"
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, float("nan")]}])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_embedding_path"] = str(user_embeddings)
    manifest["user_embedding_row_count"] = 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="non-finite embedding"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_requires_user_embedding_row_count(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    user_embeddings = tmp_path / "source" / "user_embeddings.jsonl"
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0]}])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_embedding_path"] = str(user_embeddings)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="user_embedding_row_count"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_user_embedding_missing_user_id(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    user_embeddings = tmp_path / "source" / "user_embeddings.jsonl"
    write_jsonl(user_embeddings, [{"embedding": [1.0, 0.0]}])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_embedding_path"] = str(user_embeddings)
    manifest["user_embedding_row_count"] = 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="missing user_id"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def test_two_tower_dssm_source_manifest_rejects_forbidden_user_embedding_path(tmp_path: Path) -> None:
    manifest_path = _write_source_manifest(tmp_path / "source")
    forbidden_dir = tmp_path / "oracle" / "source"
    forbidden_dir.mkdir(parents=True)
    user_embeddings = forbidden_dir / "user_embeddings.jsonl"
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0]}])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["user_embedding_path"] = str(user_embeddings)
    manifest["user_embedding_row_count"] = 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden"):
        validate_two_tower_dssm_source_index_manifest(manifest_path)


def _write_source_manifest(root: Path, *, rows: list[dict] | None = None) -> Path:
    root.mkdir(parents=True)
    index = root / "recall_index.jsonl"
    item_vocab = root / "training_item_universe.jsonl"
    item_vocab_manifest = root / "two_tower_dssm_item_vocab_manifest.json"
    if rows is None:
        rows = [
            {"parent_asin": "A", "item_id": "A", "embedding": [1.0, 0.0]},
            {"parent_asin": "B", "item_id": "B", "embedding": [0.0, 1.0]},
        ]
    write_jsonl(index, rows)
    write_jsonl(
        item_vocab,
        [
            {"parent_asin": str(row.get("parent_asin") or row.get("item_id") or f"item_{index}"), "item_id": str(row.get("item_id") or row.get("parent_asin") or f"item_{index}")}
            for index, row in enumerate(rows)
        ],
    )
    write_json(
        item_vocab_manifest,
        {
            "schema_version": "two_tower_item_vocab_v1",
            "item_vocab_path": str(item_vocab),
            "source_paths": {"canonical_interactions_train": str(root / "canonical_interactions.train.jsonl")},
            "item_count": len(rows),
            "metadata_join_added_items": False,
        },
    )
    manifest = root / "source_index_manifest.json"
    write_json(
        manifest,
        {
            "schema_version": "two_tower_dssm_source_index_v1",
            "source": "two_tower_dssm",
            "canonical_source": "two_tower_dssm",
            "source_name": "two_tower_dssm",
            "variant": "dssm",
            "model_type": "dssm_two_tower_v1",
            "index_scope": "RECENT_2Y_DERIVED_INDEX",
            "source_status": "FULL_DERIVED_INDEX_DIAGNOSTIC",
            "train_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "ranking_replacement_allowed": False,
            "pool1000_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
            "embedding_path": str(index),
            "index_path": str(index),
            "item_vocab_manifest": str(item_vocab_manifest),
            "row_count": len(rows),
            "embedding_row_count": len(rows),
            "index_row_count": len(rows),
            "model_parameters": {},
        },
    )
    return manifest
