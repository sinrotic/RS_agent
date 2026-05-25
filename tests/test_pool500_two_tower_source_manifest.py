from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_core.recsys.candidate_merge import load_two_tower_index
from rs_core.recsys.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_core.recsys.vector_index import VectorIndex
from scripts.recall.build_two_tower_source_index import build_two_tower_source_index

pytestmark = pytest.mark.unit


def test_build_pool500_two_tower_source_manifest_success(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_path = tmp_path / "final" / "source_index_manifest.json"

    manifest = build_two_tower_source_index(
        training_run_dir=paths["training_run_dir"],
        item_vocab_manifest=paths["item_vocab_manifest"],
        output_dir=output_path.parent,
        output_source_manifest=output_path,
    )

    saved = read_json(output_path)
    index = load_two_tower_index(output_path)
    assert saved == manifest
    assert isinstance(index, VectorIndex)
    assert saved["schema_version"] == "two_tower_source_index_v1"
    assert saved["source"] == "two_tower"
    assert saved["canonical_source"] == "two_tower"
    assert saved["source_name"] == "two_tower_youtube_dnn"
    assert saved["variant"] == "youtube_dnn"
    assert saved["model_type"] == "youtube_dnn_two_tower_v1"
    assert saved["index_scope"] == "FULL_DERIVED_INDEX"
    assert saved["embedding_path"] == str(paths["item_embeddings"].resolve())
    assert saved["index_path"] == str(paths["recall_index"].resolve())
    assert saved["item_vocab_manifest"] == str(paths["item_vocab_manifest"].resolve())
    assert saved["row_count"] == 3
    assert saved["embedding_row_count"] == 3
    assert saved["index_row_count"] == 3
    assert len(index.items) == 3
    assert len(index.user_embeddings) == 2
    assert saved["content_hash"].startswith("sha256:")


def test_build_pool500_two_tower_source_manifest_uses_train_only_item_vocab(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    manifest = build_two_tower_source_index(
        training_run_dir=paths["training_run_dir"],
        item_vocab_manifest=paths["item_vocab_manifest"],
        output_dir=tmp_path / "final",
        output_source_manifest=tmp_path / "final" / "source_index_manifest.json",
    )

    item_vocab_manifest = read_json(manifest["item_vocab_manifest"])
    assert item_vocab_manifest["source_paths"]["canonical_interactions_train"] == str(paths["canonical_interactions"].resolve())
    assert item_vocab_manifest["metadata_join_added_items"] is False
    assert "popular_recall.jsonl" in item_vocab_manifest["forbidden_sources"]
    assert "category_recall_items.jsonl" in item_vocab_manifest["forbidden_sources"]


def test_build_pool500_two_tower_source_manifest_rejects_forbidden_contract_path(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    forbidden_dir = tmp_path / "valid" / "run"
    forbidden_dir.mkdir(parents=True)
    forbidden_index = forbidden_dir / "two_tower_recall_index.jsonl"
    write_jsonl(forbidden_index, [
        {"item_id": "item_a", "parent_asin": "item_a", "embedding": [1.0, 0.0]},
        {"item_id": "item_b", "parent_asin": "item_b", "embedding": [0.0, 1.0]},
        {"item_id": "item_c", "parent_asin": "item_c", "embedding": [1.0, 1.0]},
    ])
    artifact = read_json(paths["artifact_manifest"])
    artifact["contract"]["recall_index"] = str(forbidden_index)
    write_json(paths["artifact_manifest"], artifact)
    output_path = tmp_path / "final" / "source_index_manifest.json"

    with pytest.raises(ValueError, match="forbidden"):
        build_two_tower_source_index(
            training_run_dir=paths["training_run_dir"],
            item_vocab_manifest=paths["item_vocab_manifest"],
            output_dir=output_path.parent,
            output_source_manifest=output_path,
        )

    assert not output_path.exists()


def test_build_pool500_two_tower_source_manifest_rejects_source_field_mismatch(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    model = read_json(paths["model"])
    model["model_type"] = "dssm_two_tower_v1"
    write_json(paths["model"], model)
    output_path = tmp_path / "final" / "source_index_manifest.json"

    with pytest.raises(ValueError, match="model_type"):
        build_two_tower_source_index(
            training_run_dir=paths["training_run_dir"],
            item_vocab_manifest=paths["item_vocab_manifest"],
            output_dir=output_path.parent,
            output_source_manifest=output_path,
        )

    assert not output_path.exists()


def test_build_pool500_two_tower_source_manifest_preserves_existing_final_on_failure(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_path = tmp_path / "final" / "source_index_manifest.json"
    output_path.parent.mkdir()
    output_path.write_text('{"existing": true}', encoding="utf-8")
    paths["recall_index"].write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="row counts|must match"):
        build_two_tower_source_index(
            training_run_dir=paths["training_run_dir"],
            item_vocab_manifest=paths["item_vocab_manifest"],
            output_dir=output_path.parent,
            output_source_manifest=output_path,
            overwrite=True,
        )

    assert read_json(output_path) == {"existing": True}
    assert not (output_path.parent / "source_index_manifest.json.tmp").exists()


def test_build_pool500_two_tower_source_manifest_validates_saved_manifest(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_path = tmp_path / "final" / "source_index_manifest.json"
    build_two_tower_source_index(
        training_run_dir=paths["training_run_dir"],
        item_vocab_manifest=paths["item_vocab_manifest"],
        output_dir=output_path.parent,
        output_source_manifest=output_path,
    )

    manifest = read_json(output_path)
    manifest["index_row_count"] = manifest["row_count"] + 1
    write_json(output_path, manifest)

    with pytest.raises(ValueError, match="row_count"):
        validate_two_tower_source_index_manifest(output_path)


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    run_dir = tmp_path / "official" / "run_001"
    clean_dir.mkdir()
    run_dir.mkdir(parents=True)

    canonical_interactions = clean_dir / "canonical_interactions.train.jsonl"
    canonical_items = clean_dir / "canonical_items.jsonl"
    item_vocab = clean_dir / "two_tower_item_vocab.jsonl"
    item_vocab_manifest = clean_dir / "two_tower_item_vocab_manifest.json"
    rows: list[dict[str, Any]] = [
        {"item_id": "item_a", "parent_asin": "item_a", "embedding": [1.0, 0.0]},
        {"item_id": "item_b", "parent_asin": "item_b", "embedding": [0.0, 1.0]},
        {"item_id": "item_c", "parent_asin": "item_c", "embedding": [1.0, 1.0]},
    ]
    write_jsonl(canonical_interactions, [{"parent_asin": row["parent_asin"]} for row in rows])
    write_jsonl(canonical_items, [{"parent_asin": row["parent_asin"]} for row in rows])
    write_jsonl(item_vocab, [{"parent_asin": row["parent_asin"], "item_id": row["item_id"]} for row in rows])
    write_json(
        item_vocab_manifest,
        {
            "schema_version": "two_tower_item_vocab_v1",
            "item_vocab_path": str(item_vocab),
            "source_paths": {"canonical_interactions_train": str(canonical_interactions), "canonical_items_metadata": str(canonical_items)},
            "item_count": len(rows),
            "metadata_join_added_items": False,
            "forbidden_sources": ["popular_recall.jsonl", "category_recall_items.jsonl", "valid", "test", "holdout", "eval_label"],
            "content_hash": "sha256:fixture",
        },
    )

    train_config = run_dir / "train_config.json"
    model = run_dir / "two_tower_model.json"
    item_embeddings = run_dir / "item_embeddings.jsonl"
    user_embeddings = run_dir / "user_embeddings.jsonl"
    train_metrics = run_dir / "train_metrics.json"
    recall_index = run_dir / "two_tower_recall_index.jsonl"
    artifact_manifest = run_dir / "artifact_manifest.json"

    write_json(train_config, {"variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn"})
    write_json(model, {"model_type": "youtube_dnn_two_tower_v1", "variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn"})
    write_jsonl(item_embeddings, rows)
    write_jsonl(recall_index, rows)
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0]}, {"user_id": "u2", "embedding": [0.0, 1.0]}])
    write_json(train_metrics, {"variant": "youtube_dnn", "training_backend": {"name": "fixture"}, "users_with_training_rows": 2})
    write_json(
        artifact_manifest,
        {
            "artifact_type": "two_tower_training_artifacts_v1",
            "variant": "youtube_dnn",
            "source_name": "two_tower_youtube_dnn",
            "default_enabled": False,
            "contract": {
                "train_config": str(train_config),
                "model": str(model),
                "item_embeddings": str(item_embeddings),
                "user_embeddings": str(user_embeddings),
                "train_metrics": str(train_metrics),
                "recall_index": str(recall_index),
                "artifact_manifest": str(artifact_manifest),
            },
        },
    )
    return {
        "training_run_dir": run_dir,
        "artifact_manifest": artifact_manifest,
        "model": model,
        "item_embeddings": item_embeddings,
        "user_embeddings": user_embeddings,
        "recall_index": recall_index,
        "canonical_interactions": canonical_interactions,
        "item_vocab_manifest": item_vocab_manifest,
    }
