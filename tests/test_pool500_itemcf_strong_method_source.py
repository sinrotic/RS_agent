from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_core.common.io import read_json
from rs_lab.experiments.recall.pool500.methods.itemcf_strong import build_itemcf_strong_method_source

pytestmark = pytest.mark.unit


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _make_clean_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    train_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(
        train_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["a"], "recent_strong_positive_item_sequence": ["a"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["b"], "recent_strong_positive_item_sequence": ["b"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["a", "c"], "recent_strong_positive_item_sequence": ["a", "c"]},
            {"user_id": "u4", "recent_positive_item_sequence": ["b", "d"], "recent_strong_positive_item_sequence": ["b", "d"]},
            {"user_id": "u5", "recent_positive_item_sequence": ["x"], "recent_strong_positive_item_sequence": []},
        ],
    )
    _write_json(clean_dir / "manifest.json", {"train_user_sequences_path": str(train_path)})
    _write_jsonl(clean_dir / "canonical_interactions.valid.jsonl", [{"must_not_be_read": True}])
    _write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [{"must_not_be_read": True}])
    _write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])
    return clean_dir / "manifest.json"


def test_build_itemcf_strong_method_source_outputs_required_contract(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)

    manifest = build_itemcf_strong_method_source(
        clean_manifest_path=clean_manifest,
        output_root=tmp_path / "method_sources",
        run_id="unit",
        target_user_limit=2,
        batch_size=1,
        max_items_per_user=3,
        max_item_user_freq=10,
        top_k_per_seed=3,
        candidate_limit_per_user=2,
        min_free_bytes=1,
        enforce_venv=False,
    )

    output_dir = tmp_path / "method_sources" / "itemcf_strong" / "unit"
    required = {
        "method_dataset_manifest.json",
        "source_index_manifest.json",
        "candidates.jsonl",
        "coverage_audit.json",
        "undercoverage_audit.json",
        "resource_audit.json",
        "no_holdout_audit.json",
    }
    assert required.issubset({path.name for path in output_dir.iterdir()})
    assert manifest["source"] == "itemcf_strong"
    assert manifest["canonical_source"] == "itemcf_strong"
    assert manifest["source_status"] == "DIAGNOSTIC_ONLY"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["final_pool500_ready_claimed"] is False
    assert manifest["candidate_row_count"] == 2
    assert manifest["user_coverage_count"] == 2
    assert manifest["per_user_candidate_count"] == {"min": 1, "p50": 1, "p90": 1, "max": 1}

    rows = [json.loads(line) for line in (output_dir / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(row["user_id"], row["item_id"], row["source"]) for row in rows} == {("u1", "c", "itemcf_strong"), ("u2", "d", "itemcf_strong")}
    coverage = read_json(output_dir / "coverage_audit.json")
    undercoverage = read_json(output_dir / "undercoverage_audit.json")
    no_holdout = read_json(output_dir / "no_holdout_audit.json")
    assert coverage["seed_hit_count"] == 2
    assert coverage["strong_edge_hit_count"] == 2
    assert undercoverage["undercovered_user_count"] == 0
    assert no_holdout["read_files"] == [str(clean_manifest.resolve()), str((clean_manifest.parent / "user_sequences.train.jsonl").resolve())]
    assert no_holdout["uses_holdout"] is False


def test_build_itemcf_strong_method_source_accepts_runner_style_config(tmp_path: Path) -> None:
    clean_manifest = _make_clean_manifest(tmp_path)
    output_dir = tmp_path / "explicit" / "itemcf_strong" / "runner"

    manifest = build_itemcf_strong_method_source(
        config={
            "clean_manifest": str(clean_manifest),
            "target_user_limit": 2,
            "batch_size": 2,
            "max_items_per_user": 3,
            "top_k_per_seed": 2,
            "candidate_limit_per_user": 2,
            "min_free_bytes": 1,
        },
        output_dir=output_dir,
        run_id="runner",
        overwrite=False,
        enforce_venv=False,
    )

    assert manifest["outputs"]["source_index_manifest"] == str(output_dir / "source_index_manifest.json")
    assert Path(manifest["outputs"]["candidates"]).is_file()
