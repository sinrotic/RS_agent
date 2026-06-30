from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_lab.experiments.recall.pool500.methods.itemcf_weak.builder import build_itemcf_weak_method_source

pytestmark = pytest.mark.unit


def test_build_itemcf_weak_method_source_writes_required_diagnostic_artifacts(tmp_path: Path) -> None:
    clean_manifest = _write_fixture(tmp_path)

    manifest = build_itemcf_weak_method_source(
        clean_manifest_path=clean_manifest,
        output_root=tmp_path / "official_outputs",
        run_id="run_001",
        target_user_limit=2,
        batch_size=1,
        max_items_per_user=3,
        max_item_user_freq=10,
        top_k_per_seed=2,
        per_user_candidate_limit=5,
        overwrite=True,
        enforce_venv=False,
    )

    output_dir = tmp_path / "official_outputs" / "itemcf_weak" / "run_001"
    required_outputs = {
        "method_dataset_manifest.json",
        "source_index_manifest.json",
        "candidates.jsonl",
        "coverage_audit.json",
        "undercoverage_audit.json",
        "resource_audit.json",
        "no_holdout_audit.json",
    }
    assert required_outputs <= {path.name for path in output_dir.iterdir()}
    assert manifest["source"] == "itemcf_weak"
    assert manifest["canonical_source"] == "itemcf_weak"
    assert manifest["source_status"] == "DIAGNOSTIC_ONLY"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    assert manifest["candidate_total_count"] > 0
    assert manifest["candidate_user_count"] == 2
    assert manifest["candidate_count_stats"]["max"] <= 5

    rows = _read_jsonl(output_dir / "candidates.jsonl")
    assert {row["source"] for row in rows} == {"itemcf_weak"}
    assert {row["canonical_source"] for row in rows} == {"itemcf_weak"}
    assert all(row["sources"] == ["itemcf_weak"] for row in rows)
    assert all("seed_item" in row["metadata"] for row in rows)

    no_holdout = read_json(output_dir / "no_holdout_audit.json")
    assert no_holdout["status"] == "PASS"
    assert no_holdout["read_files"] == [str(clean_manifest.resolve()), str((clean_manifest.parent / "user_sequences.train.jsonl").resolve())]
    assert no_holdout["uses_holdout"] is False
    assert no_holdout["uses_valid"] is False
    assert no_holdout["uses_test"] is False


def test_build_itemcf_weak_method_source_rejects_forbidden_output_path(tmp_path: Path) -> None:
    clean_manifest = _write_fixture(tmp_path)

    with pytest.raises(ValueError, match="Forbidden"):
        build_itemcf_weak_method_source(
            clean_manifest_path=clean_manifest,
            output_root=tmp_path / "pool1000" / "outputs",
            run_id="run_001",
            overwrite=True,
            enforce_venv=False,
        )


def _write_fixture(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    write_jsonl(
        train_sequences,
        [
            {"user_id": "u1", "recent_item_sequence": ["a"], "recent_positive_item_sequence": ["a", "b", "c"]},
            {"user_id": "u2", "recent_item_sequence": ["d"], "recent_positive_item_sequence": ["b", "d", "e"]},
            {"user_id": "u3", "recent_item_sequence": ["f"], "recent_positive_item_sequence": ["a", "e", "f"]},
            {"user_id": "u4", "recent_item_sequence": ["g"], "recent_positive_item_sequence": ["c", "e", "g"]},
        ],
    )
    clean_manifest = clean_dir / "manifest.json"
    write_json(clean_manifest, {"schema_version": "fixture_clean_v1", "train_user_sequences_path": str(train_sequences)})
    return clean_manifest


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
