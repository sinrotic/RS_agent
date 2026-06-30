from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json, write_json, write_jsonl
from scripts.recall.two_tower_DSSM.build_two_tower_dssm_source_index import build_two_tower_dssm_source_index

pytestmark = pytest.mark.unit


def test_build_two_tower_dssm_source_index_success(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_path = tmp_path / "final" / "source_index_manifest.json"

    manifest = build_two_tower_dssm_source_index(
        training_run_dir=paths["training_run_dir"],
        item_vocab_manifest=paths["item_vocab_manifest"],
        output_dir=output_path.parent,
        output_source_manifest=output_path,
    )

    saved = read_json(output_path)
    assert saved == manifest
    assert saved["schema_version"] == "two_tower_dssm_source_index_v1"
    assert saved["source"] == "two_tower_dssm"
    assert saved["canonical_source"] == "two_tower_dssm"
    assert saved["source_name"] == "two_tower_dssm"
    assert saved["variant"] == "dssm"
    assert saved["model_type"] == "dssm_two_tower_v1"
    assert saved["index_scope"] == "RECENT_2Y_DERIVED_INDEX"
    assert saved["source_status"] == "FULL_DERIVED_INDEX_DIAGNOSTIC"
    assert saved["train_only"] is True
    assert saved["candidate_generation_allowed"] is False
    assert saved["ranking_input_replacement_allowed"] is False
    assert saved["ranking_replacement_allowed"] is False
    assert saved["pool1000_allowed"] is False
    assert saved["promotion_allowed"] is False
    assert saved["final_pool500_ready_claimed"] is False
    assert saved["embedding_path"] == str(paths["item_embeddings"].resolve())
    assert saved["index_path"] == str(paths["recall_index"].resolve())
    assert saved["item_vocab_manifest"] == str(paths["item_vocab_manifest"].resolve())
    assert saved["row_count"] == 3
    assert saved["embedding_row_count"] == 3
    assert saved["index_row_count"] == 3
    assert saved["content_hash"].startswith("sha256:")


def test_build_two_tower_dssm_source_index_rejects_youtube_dnn_artifact(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    artifact = read_json(paths["artifact_manifest"])
    artifact["variant"] = "youtube_dnn"
    write_json(paths["artifact_manifest"], artifact)

    with pytest.raises(ValueError, match="variant"):
        build_two_tower_dssm_source_index(
            training_run_dir=paths["training_run_dir"],
            item_vocab_manifest=paths["item_vocab_manifest"],
            output_dir=tmp_path / "final",
            output_source_manifest=tmp_path / "final" / "source_index_manifest.json",
        )


def test_build_two_tower_dssm_source_index_preserves_existing_final_on_failure(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_path = tmp_path / "final" / "source_index_manifest.json"
    output_path.parent.mkdir()
    output_path.write_text('{"existing": true}', encoding="utf-8")
    paths["recall_index"].write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="row counts|must match"):
        build_two_tower_dssm_source_index(
            training_run_dir=paths["training_run_dir"],
            item_vocab_manifest=paths["item_vocab_manifest"],
            output_dir=output_path.parent,
            output_source_manifest=output_path,
            overwrite=True,
        )

    assert read_json(output_path) == {"existing": True}
    assert not (output_path.parent / "source_index_manifest.json.tmp").exists()


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    run_dir = tmp_path / "dssm" / "run_001"
    clean_dir.mkdir()
    run_dir.mkdir(parents=True)

    canonical_interactions = clean_dir / "canonical_interactions.train.jsonl"
    item_vocab = clean_dir / "training_item_universe.jsonl"
    item_vocab_manifest = clean_dir / "two_tower_dssm_item_vocab_manifest.json"
    rows: list[dict[str, Any]] = [
        {"item_id": "item_a", "parent_asin": "item_a", "embedding": [1.0, 0.0]},
        {"item_id": "item_b", "parent_asin": "item_b", "embedding": [0.0, 1.0]},
        {"item_id": "item_c", "parent_asin": "item_c", "embedding": [1.0, 1.0]},
    ]
    write_jsonl(canonical_interactions, [{"parent_asin": row["parent_asin"]} for row in rows])
    write_jsonl(item_vocab, [{"parent_asin": row["parent_asin"], "item_id": row["item_id"]} for row in rows])
    write_json(
        item_vocab_manifest,
        {
            "schema_version": "two_tower_item_vocab_v1",
            "item_vocab_path": str(item_vocab),
            "source_paths": {"canonical_interactions_train": str(canonical_interactions)},
            "item_count": len(rows),
            "metadata_join_added_items": False,
            "forbidden_sources": ["valid", "test", "holdout", "eval_label", "oracle"],
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

    write_json(train_config, {"variant": "dssm", "source_name": "two_tower_dssm"})
    write_json(model, {"model_type": "dssm_two_tower_v1", "variant": "dssm", "source_name": "two_tower_dssm"})
    write_jsonl(item_embeddings, rows)
    write_jsonl(recall_index, rows)
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0]}])
    write_json(train_metrics, {"variant": "dssm", "training_backend": {"name": "fixture"}, "users_with_training_rows": 1})
    write_json(
        artifact_manifest,
        {
            "artifact_type": "two_tower_training_artifacts_v1",
            "variant": "dssm",
            "source_name": "two_tower_dssm",
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
        "item_embeddings": item_embeddings,
        "recall_index": recall_index,
        "item_vocab_manifest": item_vocab_manifest,
    }
