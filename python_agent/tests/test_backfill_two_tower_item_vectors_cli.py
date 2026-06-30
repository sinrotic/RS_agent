from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.common.io import read_json, read_jsonl, write_json, write_jsonl
from scripts.recall.backfill_two_tower_item_vectors import main

pytestmark = pytest.mark.unit


def test_backfill_two_tower_item_vectors_cli_writes_backfilled_manifest(tmp_path: Path) -> None:
    source_index = tmp_path / "source" / "two_tower_recall_index.jsonl"
    source_index.parent.mkdir(parents=True)
    write_jsonl(source_index, [{"parent_asin": "a", "embedding": [1.0, 0.0], "main_category": "Audio"}])
    source_manifest = tmp_path / "source" / "source_index_manifest.json"
    write_json(
        source_manifest,
        {
            "schema_version": "two_tower_source_index_v1",
            "source_name": "two_tower_youtube_dnn",
            "variant": "youtube_dnn",
            "model_type": "youtube_dnn_two_tower_v1",
            "index_path": "two_tower_recall_index.jsonl",
            "embedding_path": "two_tower_recall_index.jsonl",
            "candidate_generation_allowed": False,
            "train_only": True,
            "no_holdout": True,
        },
    )
    canonical_items = tmp_path / "canonical_items.jsonl"
    write_jsonl(
        canonical_items,
        [
            {"parent_asin": "a", "main_category": "Audio"},
            {"parent_asin": "b", "main_category": "Audio"},
        ],
    )

    output_dir = tmp_path / "backfilled"
    manifest = main(
        [
            "--source-index-manifest",
            str(source_manifest),
            "--canonical-items",
            str(canonical_items),
            "--output-dir",
            str(output_dir),
        ]
    )

    rows = read_jsonl(output_dir / "item_embeddings.backfilled.jsonl")
    written_manifest = read_json(output_dir / "source_index_manifest.backfilled.json")
    assert [row["item_id"] for row in rows] == ["a", "b"]
    assert rows[1]["vector_origin"] == "category_centroid"
    assert manifest["backfill"]["backfilled_item_count"] == 1
    assert written_manifest["row_count"] == 2
