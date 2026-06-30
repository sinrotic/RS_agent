from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.pool500.methods.swing_recall import enhanced_source

pytestmark = pytest.mark.unit


def test_pool500_swing_recall_enhanced_source_writes_required_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "target", "recent_positive_item_sequence": ["seed"]},
            {"user_id": "neighbor_a", "recent_positive_item_sequence": ["seed", "item_a"]},
            {"user_id": "neighbor_b", "recent_positive_item_sequence": ["seed", "item_b"]},
        ],
    )
    baseline_dir = _write_baseline_fixture(tmp_path)
    monkeypatch.setattr(enhanced_source, "ROOT", tmp_path)

    manifest = enhanced_source.build_pool500_swing_recall_enhanced_source(
        clean_manifest_path=clean_manifest,
        baseline_dir=baseline_dir,
        output_root=tmp_path / "method_sources" / "swing_recall",
        run_id="fixture",
        max_graph_users=10,
        max_items_per_user=10,
        max_item_user_freq=10,
        min_user_items=2,
        min_pair_support=1,
        per_seed_top_k=10,
        seed_window=5,
        per_user=10,
        min_free_bytes=0,
        enforce_venv=False,
    )

    output_dir = tmp_path / "method_sources" / "swing_recall" / "fixture"
    required = {
        "method_dataset_manifest.json",
        "source_index_manifest.json",
        "candidates.jsonl",
        "coverage_audit.json",
        "undercoverage_audit.json",
        "resource_audit.json",
        "no_holdout_audit.json",
    }
    assert required <= {path.name for path in output_dir.iterdir()}
    assert manifest["source_status"] == "TARGET_SLICE_DIAGNOSTIC"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False

    candidates = _read_jsonl(output_dir / "candidates.jsonl")
    assert {row["item_id"] for row in candidates} == {"item_a", "item_b"}
    assert all(row["sources"] == ["swing_recall"] for row in candidates)

    coverage = json.loads((output_dir / "coverage_audit.json").read_text(encoding="utf-8"))
    no_holdout = json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))
    assert coverage["candidate_row_count"] == 2
    assert coverage["user_coverage_count"] == 1
    assert coverage["candidate_count_distribution"] == {"min": 2, "p50": 2, "p90": 2, "max": 2, "avg": 2.0}
    assert coverage["swing_pair_coverage"]["target_seed_hit_user_count"] == 1
    assert no_holdout["valid_test_holdout_usage"] == "not_read"
    assert no_holdout["read_files"] == [
        str(clean_manifest.resolve()),
        str((tmp_path / "clean" / "user_sequences.train.jsonl").resolve()),
        str((baseline_dir / "eligible_user_manifest.json").resolve()),
        str((baseline_dir / "sources" / "swing_recall" / "candidates.jsonl").resolve()),
    ]


def _write_clean_fixture(root: Path, rows: list[dict[str, object]]) -> Path:
    clean_dir = root / "clean"
    clean_dir.mkdir()
    train_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(train_path, rows)
    manifest_path = clean_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"status": "PASS", "train_user_sequences_path": str(train_path)}), encoding="utf-8")
    return manifest_path


def _write_baseline_fixture(root: Path) -> Path:
    baseline_dir = root / "baseline"
    swing_dir = baseline_dir / "sources" / "swing_recall"
    swing_dir.mkdir(parents=True)
    (baseline_dir / "eligible_user_manifest.json").write_text(
        json.dumps({"eligible_user_ids": ["target"]}),
        encoding="utf-8",
    )
    (swing_dir / "candidates.jsonl").write_text("", encoding="utf-8")
    return baseline_dir


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
