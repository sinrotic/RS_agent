from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_core.online.recall.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _load_source_artifacts
from scripts.recall.build_two_tower_source_index import build_two_tower_source_index

pytestmark = pytest.mark.unit


def test_direct_artifact_manifest_load_blocked(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    with pytest.raises(ValueError, match="source_index_manifest.json|schema_version"):
        _load_source_artifacts({"two_tower": paths["artifact_manifest"]})


def test_source_field_mismatch_blocked(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    manifest = read_json(paths["source_index_manifest"])
    manifest["source"] = "oracle"
    write_json(paths["source_index_manifest"], manifest)

    with pytest.raises(ValueError, match="source"):
        validate_two_tower_source_index_manifest(paths["source_index_manifest"])


def test_row_count_mismatch_blocked(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    manifest = read_json(paths["source_index_manifest"])
    manifest["embedding_row_count"] = manifest["row_count"] + 1
    write_json(paths["source_index_manifest"], manifest)

    with pytest.raises(ValueError, match="row_count"):
        validate_two_tower_source_index_manifest(paths["source_index_manifest"])


def test_valid_source_manifest_accepted(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = validate_two_tower_source_index_manifest(paths["source_index_manifest"])
    artifacts = _load_source_artifacts({"two_tower": paths["source_index_manifest"]})

    assert manifest["source"] == "two_tower"
    assert artifacts["two_tower"]["manifest"]["row_count"] == 3


def test_build_two_tower_source_index_cli_payload(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path, build_source=False)
    manifest = build_two_tower_source_index(
        training_run_dir=paths["training_run_dir"],
        item_vocab_manifest=paths["item_vocab_manifest"],
        output_dir=tmp_path / "source_index",
        output_source_manifest=tmp_path / "source_index" / "source_index_manifest.json",
    )

    assert manifest["schema_version"] == "two_tower_source_index_v1"
    assert manifest["row_count"] == 3
    assert validate_two_tower_source_index_manifest(tmp_path / "source_index" / "source_index_manifest.json")["index_scope"] == "FULL_DERIVED_INDEX"


def _write_fixture(tmp_path: Path, build_source: bool = True) -> dict[str, Path]:
    run_dir = tmp_path / "train" / "run"
    vocab_dir = tmp_path / "vocab"
    source_dir = tmp_path / "source"
    run_dir.mkdir(parents=True)
    vocab_dir.mkdir()
    source_dir.mkdir()

    model = run_dir / "two_tower_model.json"
    item_embeddings = run_dir / "item_embeddings.jsonl"
    user_embeddings = run_dir / "user_embeddings.jsonl"
    train_config = run_dir / "train_config.json"
    train_metrics = run_dir / "train_metrics.json"
    recall_index = run_dir / "two_tower_recall_index.jsonl"
    artifact_manifest = run_dir / "artifact_manifest.json"
    item_vocab = vocab_dir / "two_tower_item_vocab.jsonl"
    item_vocab_manifest = vocab_dir / "two_tower_item_vocab_manifest.json"

    rows: list[dict[str, Any]] = [
        {"item_id": "item_a", "parent_asin": "item_a", "embedding": [1.0, 0.0]},
        {"item_id": "item_b", "parent_asin": "item_b", "embedding": [0.0, 1.0]},
        {"item_id": "item_c", "parent_asin": "item_c", "embedding": [1.0, 1.0]},
    ]
    write_json(model, {"model_type": "youtube_dnn_two_tower_v1", "variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn"})
    write_json(train_config, {"variant": "youtube_dnn"})
    write_json(train_metrics, {"variant": "youtube_dnn"})
    write_jsonl(item_embeddings, rows)
    write_jsonl(recall_index, rows)
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0]}])
    write_jsonl(item_vocab, [{"parent_asin": row["parent_asin"]} for row in rows])
    write_json(item_vocab_manifest, {"schema_version": "two_tower_item_vocab_v1", "item_vocab_path": str(item_vocab), "item_count": 3})
    write_json(
        artifact_manifest,
        {
            "artifact_type": "two_tower_training_artifacts_v1",
            "variant": "youtube_dnn",
            "source_name": "two_tower_youtube_dnn",
            "contract": {
                "model": str(model),
                "item_embeddings": str(item_embeddings),
                "user_embeddings": str(user_embeddings),
                "train_config": str(train_config),
                "train_metrics": str(train_metrics),
                "recall_index": str(recall_index),
            },
        },
    )
    source_index_manifest = source_dir / "source_index_manifest.json"
    if build_source:
        build_two_tower_source_index(
            training_run_dir=run_dir,
            item_vocab_manifest=item_vocab_manifest,
            output_dir=source_dir,
            output_source_manifest=source_index_manifest,
        )
    return {
        "training_run_dir": run_dir,
        "artifact_manifest": artifact_manifest,
        "item_vocab_manifest": item_vocab_manifest,
        "source_index_manifest": source_index_manifest,
    }
