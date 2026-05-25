from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.pool500.common.source_layout import REQUIRED_SOURCE_OUTPUTS
from rs_lab.experiments.recall.pool500.methods.co_visit_fallback_repair.builder import build_co_visit_fallback_repair_source

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_build_co_visit_fallback_repair_source_writes_governed_artifacts(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    train_sequences = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(
        train_sequences,
        [
            {"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]},
            {"user_id": "u2", "recent_item_sequence": ["missing"], "recent_positive_item_sequence": ["missing"]},
        ],
    )
    train_interactions = clean_dir / "canonical_interactions.train.jsonl"
    _write_jsonl(
        train_interactions,
        [
            {"user_id": "u3", "parent_asin": "seed", "rating": 5.0, "label_binary": 1},
            {"user_id": "u3", "parent_asin": "transition_candidate", "rating": 5.0, "label_binary": 1},
        ],
    )
    clean_manifest = clean_dir / "manifest.json"
    _write_json(clean_manifest, {"train_user_sequences_path": str(train_sequences), "split_paths": {"train": str(train_interactions)}})

    views_dir = tmp_path / "views"
    semantic = views_dir / "semantic_recall_inputs.jsonl"
    _write_jsonl(
        semantic,
        [
            {"parent_asin": "seed", "title_clean": "wireless mouse", "main_category": "Electronics"},
            {"parent_asin": "candidate", "title_clean": "wireless keyboard", "main_category": "Electronics"},
            {"parent_asin": "transition_candidate", "title_clean": "wireless receiver", "main_category": "Electronics"},
        ],
    )
    views_manifest = views_dir / "manifest.json"
    _write_json(views_manifest, {"outputs": {"semantic_recall_inputs": str(semantic)}})

    users = tmp_path / "eligible_user_manifest.json"
    _write_json(users, {"eligible_user_ids": ["u1", "u2"]})

    manifest = build_co_visit_fallback_repair_source(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        eligible_user_manifest_path=users,
        output_root=tmp_path / "outputs",
        run_id="unit",
        max_metadata_rows=10,
        candidate_per_user=5,
        candidate_per_seed=5,
        seed_window=5,
        checkpoint_every_users=1,
        overwrite=True,
    )

    output_dir = tmp_path / "outputs" / "co_visit_fallback_repair" / "unit"
    for name in REQUIRED_SOURCE_OUTPUTS:
        assert (output_dir / name).is_file()

    assert manifest["source"] == "co_visit_fallback_repair"
    assert manifest["canonical_source"] == "co_visit_fallback_repair"
    assert manifest["status"] == "TARGET_SLICE_DIAGNOSTIC"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False

    coverage = json.loads((output_dir / "coverage_audit.json").read_text(encoding="utf-8"))
    assert coverage["co_visit_seed_coverage"]["count"] == 1
    assert coverage["metadata_neighbor_coverage"]["count"] == 1
    assert coverage["sequence_transition_coverage"]["count"] == 1
    assert coverage["repair_candidate_count"] == 2

    rows = [json.loads(line) for line in (output_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[0]["source"] == "co_visit_fallback_repair"
    assert rows[0]["sources"] == ["co_visit_fallback_repair"]
    assert rows[0]["metadata"]["source_status"] == "TARGET_SLICE_DIAGNOSTIC"

    no_holdout = json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))
    assert no_holdout["status"] == "PASS"
    assert no_holdout["candidate_generation_uses_holdout"] is False
