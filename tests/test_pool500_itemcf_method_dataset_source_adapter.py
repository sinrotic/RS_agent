from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.recsys.candidate_merge import load_itemcf_by_source, load_itemcf_source_manifest
from rs_lab.experiments.recall.pool500.method_dataset_to_itemcf_source import build_itemcf_source_from_method_dataset

pytestmark = pytest.mark.unit


def test_build_itemcf_source_from_method_dataset_outputs_loader_edges(tmp_path: Path) -> None:
    input_dir = tmp_path / "formal_method_dataset"
    input_dir.mkdir()
    rows_path = input_dir / "method_dataset_rows.jsonl"
    rows_path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False)
            for row in [
                {"src_item_id": "seed-a", "dst_item_id": "cand-b", "itemcf_score": 0.7, "edge_rank": 2, "reason": "unit"},
                {"src_item_id": "seed-a", "dst_item_id": "cand-c", "itemcf_score": 0.9, "edge_rank": 1},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = input_dir / "method_dataset_manifest.json"
    manifest_path.write_text(json.dumps({"source": "itemcf_weak", "train_only": True}, ensure_ascii=False), encoding="utf-8")

    manifest = build_itemcf_source_from_method_dataset(
        source="itemcf_weak",
        method_dataset_manifest_path=manifest_path,
        output_root=tmp_path / "sources",
        run_id="unit",
        enforce_venv=False,
    )

    edges_path = Path(manifest["edges_path"])
    assert manifest["source"] == "itemcf_weak"
    assert manifest["source_status"] == "DIAGNOSTIC_ONLY"
    assert manifest["diagnostic_boundary"]["label_usage"] == "none_in_candidate_generation"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["row_count"] == 2

    loaded = load_itemcf_by_source(edges_path, "itemcf_weak")
    assert [candidate.item_id for candidate in loaded["seed-a"]] == ["cand-c", "cand-b"]
    assert loaded["seed-a"][0].score == 0.9


def test_build_itemcf_source_from_method_dataset_supports_limit_rows(tmp_path: Path) -> None:
    input_dir = tmp_path / "formal_method_dataset"
    input_dir.mkdir()
    rows_path = input_dir / "method_dataset_rows.jsonl"
    rows_path.write_text(
        "".join(
            json.dumps({"src_item_id": f"seed-{index}", "dst_item_id": f"cand-{index}", "itemcf_score": index}) + "\n"
            for index in range(3)
        ),
        encoding="utf-8",
    )
    manifest_path = input_dir / "method_dataset_manifest.json"
    manifest_path.write_text(json.dumps({"source": "itemcf_strong", "train_only": True}, ensure_ascii=False), encoding="utf-8")

    manifest = build_itemcf_source_from_method_dataset(
        source="itemcf_strong",
        method_dataset_manifest_path=manifest_path,
        output_root=tmp_path / "sources",
        run_id="unit",
        limit_rows=1,
        enforce_venv=False,
    )

    assert manifest["row_count"] == 1
    assert manifest["sharded"] is False
    assert manifest["shard_count"] == 1
    assert Path(manifest["edges_path"]).read_text(encoding="utf-8").count("\n") == 1


def test_build_itemcf_weak_source_from_method_dataset_writes_src_item_shards(tmp_path: Path) -> None:
    input_dir = tmp_path / "formal_method_dataset"
    input_dir.mkdir()
    rows_path = input_dir / "method_dataset_rows.jsonl"
    rows_path.write_text(
        "".join(
            json.dumps({"src_item_id": seed, "dst_item_id": f"cand-{index}", "itemcf_score": 1.0 - index / 10, "edge_rank": index + 1}) + "\n"
            for index, seed in enumerate(["seed-a", "seed-b", "seed-a", "seed-z"])
        ),
        encoding="utf-8",
    )
    manifest_path = input_dir / "method_dataset_manifest.json"
    manifest_path.write_text(json.dumps({"source": "itemcf_weak", "train_only": True}, ensure_ascii=False), encoding="utf-8")

    manifest = build_itemcf_source_from_method_dataset(
        source="itemcf_weak",
        method_dataset_manifest_path=manifest_path,
        output_root=tmp_path / "sources",
        run_id="unit_shards",
        shard_count=4,
        enforce_venv=False,
    )

    assert manifest["row_count"] == 4
    assert manifest["sharded"] is True
    assert manifest["shard_count"] == 4
    assert manifest["shard_key"] == "src_item_sha256_mod"
    assert manifest["edges_path"] is None
    assert len(manifest["outputs"]["edges_shards"]) == 4
    assert sum(shard["row_count"] for shard in manifest["edge_shard_stats"]) == 4

    loaded = load_itemcf_source_manifest(manifest["outputs"]["source_index_manifest"], "itemcf_weak", {"seed-a"})
    assert sorted(loaded) == ["seed-a"]
    assert [candidate.item_id for candidate in loaded["seed-a"]] == ["cand-0", "cand-2"]


def test_itemcf_strong_defaults_to_single_edges_path(tmp_path: Path) -> None:
    input_dir = tmp_path / "formal_method_dataset"
    input_dir.mkdir()
    rows_path = input_dir / "method_dataset_rows.jsonl"
    rows_path.write_text(
        json.dumps({"src_item_id": "strong-seed", "dst_item_id": "strong-cand", "itemcf_score": 0.8}) + "\n",
        encoding="utf-8",
    )
    manifest_path = input_dir / "method_dataset_manifest.json"
    manifest_path.write_text(json.dumps({"source": "itemcf_strong", "train_only": True}, ensure_ascii=False), encoding="utf-8")

    manifest = build_itemcf_source_from_method_dataset(
        source="itemcf_strong",
        method_dataset_manifest_path=manifest_path,
        output_root=tmp_path / "sources",
        run_id="strong_unit",
        enforce_venv=False,
    )

    assert manifest["sharded"] is False
    assert manifest["edges_path"]
    assert "edges_shards" not in manifest["outputs"]
    loaded = load_itemcf_by_source(manifest["edges_path"], "itemcf_strong")
    assert loaded["strong-seed"][0].item_id == "strong-cand"
