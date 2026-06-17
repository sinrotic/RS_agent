from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.dataproc.recent_window_materializer import materialize_recent_window_dataset

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _interaction(user_id: str, item_id: str, timestamp: int, label: int = 1, strong: int = 0) -> dict[str, object]:
    return {
        "user_id": user_id,
        "parent_asin": item_id,
        "category": "Electronics",
        "rating": 5.0 if label else 2.0,
        "timestamp": timestamp,
        "verified_purchase": bool(strong),
        "helpful_vote": 0,
        "user_interaction_count": 999,
        "item_interaction_count": 999,
        "row_num": 999,
        "label_binary": label,
        "label_strong": strong,
        "label_strength": 1.0 if label else 0.0,
        "dedup_strategy": "exact_then_user_item_keep_last",
        "split": "source",
    }


def test_materialize_recent_window_dataset_writes_fixed_splits_and_train_only_catalog(tmp_path: Path) -> None:
    source_dir = tmp_path / "clean_full"
    output_dir = tmp_path / "recent"
    source_manifest = source_dir / "manifest.json"
    source_manifest.parent.mkdir()
    interactions = [
        _interaction("u_before", "old", 1623715199999),
        _interaction("u1", "train_a", 1623715200000, strong=1),
        _interaction("u1", "valid_a", 1684108800000),
        _interaction("u2", "test_a", 1686787200000),
        _interaction("u_after", "after", 1694649600000),
    ]
    items = [
        {"parent_asin": item_id, "title_clean": item_id, "category": "Electronics"}
        for item_id in ["old", "train_a", "valid_a", "test_a", "after"]
    ]
    _write_jsonl(source_dir / "canonical_interactions.jsonl", interactions)
    _write_jsonl(source_dir / "canonical_items.jsonl", items)
    source_manifest.write_text(
        json.dumps(
            {
                "dataset": "unit",
                "canonical_interactions_path": str(source_dir / "canonical_interactions.jsonl"),
                "canonical_items_path": str(source_dir / "canonical_items.jsonl"),
                "sqlite_path": str(source_dir / "recall_clean.sqlite"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = materialize_recent_window_dataset(
        source_manifest_path=source_manifest,
        output_dir=output_dir,
        sequence_max_len=2,
        shard_count=2,
    )

    manifest = result["manifest"]
    assert manifest["sqlite_path"] is None
    assert manifest["all_interactions_path"] == manifest["canonical_interactions_path"]
    assert set(manifest["split_paths"]) == {"all", "train", "valid", "test"}
    assert Path(manifest["canonical_items_path"]).name == "canonical_items.jsonl"
    assert Path(manifest["all_canonical_items_path"]).name == "canonical_items.all.jsonl"
    assert manifest["counts"]["interactions"]["train"]["interaction_count"] == 1
    assert manifest["counts"]["interactions"]["valid"]["interaction_count"] == 1
    assert manifest["counts"]["interactions"]["test"]["interaction_count"] == 1

    all_rows = _read_jsonl(output_dir / "canonical_interactions.jsonl")
    assert [row["split"] for row in all_rows] == ["train", "valid", "test"]
    assert [row["row_num"] for row in all_rows] == [1, 2, 3]
    assert all_rows[0]["user_interaction_count"] == 2
    assert all_rows[0]["item_interaction_count"] == 1
    assert _read_jsonl(output_dir / "canonical_interactions.train.jsonl")[0]["parent_asin"] == "train_a"
    assert _read_jsonl(output_dir / "canonical_interactions.valid.jsonl")[0]["parent_asin"] == "valid_a"
    assert _read_jsonl(output_dir / "canonical_interactions.test.jsonl")[0]["parent_asin"] == "test_a"

    assert [row["parent_asin"] for row in _read_jsonl(output_dir / "canonical_items.jsonl")] == ["train_a"]
    assert [row["parent_asin"] for row in _read_jsonl(output_dir / "canonical_items.all.jsonl")] == ["train_a", "valid_a", "test_a"]

    sequences = {row["user_id"]: row for row in _read_jsonl(output_dir / "user_sequences.jsonl")}
    train_sequences = {row["user_id"]: row for row in _read_jsonl(output_dir / "user_sequences.train.jsonl")}
    assert sequences["u1"]["recent_item_sequence"] == ["train_a", "valid_a"]
    assert train_sequences["u1"]["recent_item_sequence"] == ["train_a"]
    assert "u2" not in train_sequences
    assert not (output_dir / "_sequence_shards").exists()


def test_materialize_recent_window_dataset_refuses_non_empty_output(tmp_path: Path) -> None:
    source_dir = tmp_path / "clean_full"
    output_dir = tmp_path / "recent"
    source_dir.mkdir()
    output_dir.mkdir()
    (output_dir / "existing.txt").write_text("keep", encoding="utf-8")
    source_manifest = source_dir / "manifest.json"
    source_manifest.write_text(
        json.dumps({"canonical_interactions_path": "missing.jsonl", "canonical_items_path": "missing_items.jsonl"}),
        encoding="utf-8",
    )

    with pytest.raises(FileExistsError):
        materialize_recent_window_dataset(source_manifest_path=source_manifest, output_dir=output_dir)
