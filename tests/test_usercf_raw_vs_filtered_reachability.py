from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.experiments.recall.pool500.diagnose_usercf_raw_vs_filtered_reachability import (
    diagnose_usercf_raw_vs_filtered_reachability,
)

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_usercf_raw_vs_filtered_reachability_uses_eval_labels_only(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    train_sequences_path = data_dir / "user_sequences.train.jsonl"
    valid_path = data_dir / "canonical_interactions.valid.jsonl"
    clean_manifest_path = data_dir / "manifest.json"
    method_dir = tmp_path / "method_dataset"
    method_rows_path = method_dir / "method_dataset_rows.jsonl"
    method_manifest_path = method_dir / "method_dataset_manifest.json"
    source_dir = tmp_path / "source"
    candidates_path = source_dir / "candidates.jsonl"
    source_manifest_path = source_dir / "source_index_manifest.json"
    output_dir = tmp_path / "diagnostic"

    _write_jsonl(
        train_sequences_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["a", "b", "raw_hit"]},
        ],
    )
    _write_jsonl(
        method_rows_path,
        [
            {
                "schema_version": "pool500_method_dataset_v1",
                "source_method": "usercf_method_dataset",
                "train_only": True,
                "user_id": "u1",
                "eligible_item_sequence": ["a"],
            },
            {
                "schema_version": "pool500_method_dataset_v1",
                "source_method": "usercf_method_dataset",
                "train_only": True,
                "user_id": "u2",
                "eligible_item_sequence": ["a", "b"],
            },
        ],
    )
    _write_json(
        method_manifest_path,
        {
            "schema_version": "pool500_method_dataset_v1",
            "status": "PASS",
            "source_method": "usercf_method_dataset",
            "train_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
            "outputs": {
                "dataset_schema": "eligible_user_sequence_v1",
                "dataset_rows_path": str(method_rows_path),
            },
        },
    )
    _write_jsonl(
        candidates_path,
        [
            {"user_id": "u1", "item_id": "b", "rank": 1, "source": "usercf_recall"},
        ],
    )
    _write_json(source_manifest_path, {"status": "PASS", "source": "usercf_recall", "outputs": {"candidates": str(candidates_path)}})
    _write_jsonl(
        valid_path,
        [
            {"user_id": "u1", "parent_asin": "raw_hit", "label_binary": 1, "split": "valid"},
            {"user_id": "u1", "parent_asin": "b", "label_binary": 1, "split": "valid"},
            {"user_id": "u2", "parent_asin": "not_positive", "label_binary": 0, "split": "valid"},
        ],
    )
    _write_json(clean_manifest_path, {"train_user_sequences_path": str(train_sequences_path), "split_paths": {"valid": str(valid_path)}})

    report = diagnose_usercf_raw_vs_filtered_reachability(
        clean_manifest_path=clean_manifest_path,
        method_dataset_manifest_path=method_manifest_path,
        source_index_manifest_path=source_manifest_path,
        output_dir=output_dir,
        target_user_limit=2,
        label_splits=("valid",),
        overwrite=True,
        enforce_venv=False,
    )

    metrics = report["metrics"]
    governance = report["governance_evidence"]
    assert report["readiness"] == "DIAGNOSTIC_ONLY"
    assert report["promotion_decision"] == "NO_PROMOTION_DIAGNOSTIC_ONLY"
    assert governance["eval_scope"] == "evaluation_only"
    assert governance["label_inputs_role"] == "evaluation_only_not_candidate_generation_inputs"
    assert governance["labels_used_for_neighbor_building"] is False
    assert governance["labels_used_for_candidate_generation"] is False
    assert governance["candidate_generation_allowed"] is False
    assert metrics["label_total_count"] == 2
    assert metrics["raw_neighbor_reachable_label_count"] == 2
    assert metrics["filtered_neighbor_reachable_label_count"] == 1
    assert metrics["final_candidate_hit_count"] == 1
    assert metrics["raw_reachability_rate"] == pytest.approx(1.0)
    assert metrics["filtered_reachability_rate"] == pytest.approx(0.5)
    assert metrics["final_recall_at_k"] == pytest.approx(0.5)
    assert metrics["raw_to_filtered_loss_rate"] == pytest.approx(0.5)
    assert metrics["filtered_to_final_loss_rate"] == pytest.approx(0.0)
    assert Path(report["report_path"]).is_file()
    assert Path(report["per_user_sample_path"]).is_file()
