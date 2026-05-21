from __future__ import annotations

import json
from pathlib import Path

from rs_lab.experiments.recall.pool500.methods.semantic_title_category_expansion import (
    build_semantic_title_category_expansion_source,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_builds_semantic_title_category_pool500_method_source(tmp_path: Path) -> None:
    data_dir = tmp_path / "data" / "processed" / "amazon_2023_recall_clean_full"
    views_dir = tmp_path / "data" / "processed" / "amazon_2023_recall_views_full_lightweight"
    output_root = tmp_path / "outputs" / "recall" / "pool500_method_sources"
    train_sequences = data_dir / "user_sequences.train.jsonl"
    canonical_items = data_dir / "canonical_items.jsonl"
    semantic_inputs = views_dir / "semantic_recall_inputs.jsonl"
    semantic_index = views_dir / "semantic_inverted_index.jsonl"
    clean_manifest = data_dir / "manifest.json"
    views_manifest = views_dir / "manifest.json"
    eligible_users = tmp_path / "eligible_user_manifest.json"

    _write_jsonl(train_sequences, [{
        "user_id": "u1",
        "recent_item_sequence": ["seed1"],
        "recent_positive_item_sequence": ["seed1"],
    }])
    _write_jsonl(canonical_items, [{"parent_asin": "seed1"}, {"parent_asin": "cand1"}])
    _write_jsonl(semantic_inputs, [
        {
            "parent_asin": "seed1",
            "title_clean": "wireless office mouse",
            "main_category": "Office Products",
            "category": "Office_Products",
            "categories_flat": ["Office Products", "Mice"],
        },
        {
            "parent_asin": "cand1",
            "title_clean": "wireless office keyboard",
            "main_category": "Office Products",
            "category": "Office_Products",
            "categories_flat": ["Office Products", "Keyboards"],
        },
    ])
    _write_jsonl(semantic_index, [
        {"token": "wireless", "parent_asins": ["seed1", "cand1"]},
        {"token": "office", "parent_asins": ["seed1", "cand1"]},
        {"token": "mouse", "parent_asins": ["seed1"]},
    ])
    _write_json(clean_manifest, {
        "train_user_sequences_path": str(train_sequences),
        "canonical_items_path": str(canonical_items),
    })
    _write_json(views_manifest, {
        "outputs": {
            "semantic_recall_inputs": str(semantic_inputs),
            "semantic_inverted_index": str(semantic_index),
        }
    })
    _write_json(eligible_users, {"eligible_user_ids": ["u1"]})

    manifest = build_semantic_title_category_expansion_source(
        clean_manifest_path=clean_manifest,
        lightweight_views_manifest_path=views_manifest,
        eligible_user_manifest_path=eligible_users,
        output_root=output_root,
        run_id="unit",
        limit_users=1,
        per_user=5,
        per_seed=5,
        per_token_item_limit=10,
        max_candidate_items=10,
        enforce_venv=False,
    )

    output_dir = output_root / "semantic_title_category_expansion" / "unit"
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
    assert manifest["source"] == "semantic_title_category_expansion"
    assert manifest["canonical_source"] == "semantic_title_category_expansion"
    assert manifest["source_status"] == "TARGET_SLICE_DIAGNOSTIC"
    assert manifest["candidate_generation_allowed"] is False
    assert manifest["ranking_input_replacement_allowed"] is False
    assert manifest["pool1000_allowed"] is False
    assert manifest["promotion_allowed"] is False
    assert manifest["full_pool500_ready_declared"] is False
    assert manifest["candidate_row_count"] == 1
    assert manifest["user_coverage_count"] == 1

    coverage = json.loads((output_dir / "coverage_audit.json").read_text(encoding="utf-8"))
    no_holdout = json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))
    candidate = json.loads((output_dir / "candidates.jsonl").read_text(encoding="utf-8").strip())
    assert coverage["title_coverage"] == 1.0
    assert coverage["category_coverage"] == 1.0
    assert coverage["clean_title_token_coverage"] == 1.0
    assert coverage["seed_item_metadata_coverage"] == 1.0
    assert no_holdout["status"] == "PASS"
    assert candidate["source"] == "semantic_title_category_expansion"
    assert candidate["canonical_source"] == "semantic_title_category_expansion"


def test_semantic_title_category_no_holdout_audit_blocks_forbidden_split(tmp_path: Path) -> None:
    valid_path = tmp_path / "canonical_interactions.valid.jsonl"
    valid_path.write_text("{}\n", encoding="utf-8")

    from rs_lab.experiments.recall.pool500.methods.semantic_title_category_expansion.builder import _no_holdout_audit

    audit = _no_holdout_audit([valid_path])

    assert audit["status"] == "BLOCKED"
    assert audit["candidate_generation_uses_holdout"] is True
    assert audit["candidate_generation_allowed"] is False
    assert audit["ranking_input_replacement_allowed"] is False
    assert audit["pool1000_allowed"] is False
