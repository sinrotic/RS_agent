from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from scripts.run_full_lightweight_recall_e2e import run_representative_e2e


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    clean_dir = tmp_path / "clean_full"
    views_dir = tmp_path / "views_full_lightweight"
    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {
                "user_id": "u1",
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
            },
            {
                "user_id": "u2",
                "recent_item_sequence": ["seed_office"],
                "recent_positive_item_sequence": ["seed_office"],
            },
        ],
    )
    write_json(
        views_dir / "manifest.json",
        {
            "mode": "lightweight_full_safe",
            "source_signature": {"combined_signature": "fixture"},
            "skipped_outputs": ["itemcf_recall_weak", "itemcf_recall_strong", "item_graph_recall"],
        },
    )
    write_json(views_dir / "stats.json", {"safety": {"final_output_size_bytes": 123}})
    write_jsonl(
        views_dir / "popular_recall.jsonl",
        [
            {"parent_asin": "popular_audio", "category": "Electronics", "pop_score": 10},
            {"parent_asin": "popular_office", "category": "Office", "pop_score": 8},
        ],
    )
    write_jsonl(
        views_dir / "category_recall_items.jsonl",
        [
            {
                "parent_asin": "seed_audio",
                "category": "Electronics",
                "main_category": "Electronics",
                "source_categories": ["Electronics"],
                "categories_flat": ["Electronics"],
                "title_clean": "wireless audio seed",
            },
            {
                "parent_asin": "seed_office",
                "category": "Office_Products",
                "main_category": "Office Products",
                "source_categories": ["Office_Products"],
                "categories_flat": ["Office Products"],
                "title_clean": "office paper seed",
            },
        ],
    )
    write_jsonl(
        views_dir / "category_top_items.jsonl",
        [
            {
                "bucket": "main::Electronics",
                "top_items": [{"parent_asin": "category_audio", "score": 7}],
            },
            {
                "bucket": "main::Office Products",
                "top_items": [{"parent_asin": "category_office", "score": 6}],
            },
        ],
    )
    write_jsonl(
        views_dir / "semantic_recall_inputs.jsonl",
        [
            {
                "parent_asin": "seed_audio",
                "category": "Electronics",
                "main_category": "Electronics",
                "categories_flat": ["Electronics"],
                "title_clean": "wireless audio seed",
                "description_text": "bluetooth speaker",
                "features_text": "audio wireless",
                "item_text": "wireless audio seed bluetooth speaker",
            },
            {
                "parent_asin": "seed_office",
                "category": "Office_Products",
                "main_category": "Office Products",
                "categories_flat": ["Office Products"],
                "title_clean": "office paper seed",
                "description_text": "clipboard paper",
                "features_text": "office paper",
                "item_text": "office paper seed clipboard",
            },
        ],
    )
    write_jsonl(
        views_dir / "semantic_inverted_index.jsonl",
        [
            {"token": "wireless", "parent_asins": ["semantic_audio", "seed_audio"]},
            {"token": "audio", "parent_asins": ["semantic_audio"]},
            {"token": "office", "parent_asins": ["semantic_office", "seed_office"]},
            {"token": "paper", "parent_asins": ["semantic_office"]},
        ],
    )
    return clean_dir, views_dir


def test_representative_runner_writes_manifest_and_source_audit_without_itemcf(tmp_path):
    clean_dir, views_dir = make_fixture(tmp_path)
    output_dir = tmp_path / "out"

    manifest = run_representative_e2e(
        clean_dir=clean_dir,
        views_dir=views_dir,
        output_dir=output_dir,
        limit_users=2,
        min_free_bytes=0,
        enforce_venv=False,
        candidate_pool_size=10,
        popular_per_user=2,
        category_per_user=2,
        semantic_per_user=2,
    )

    assert manifest["enabled_sources"] == ["popular", "category", "semantic"]
    assert "itemcf_weak" in manifest["disabled_sources"]
    assert manifest["mode"] == "baseline"
    assert manifest["train_only"] is True
    assert manifest["summary"]["user_count"] == 2
    assert manifest["summary"]["empty_candidate_users"] == 0
    assert set(manifest["summary"]["source_candidate_rows"]) == {"category", "popular", "semantic"}
    assert not (views_dir / "itemcf_recall_weak.jsonl").exists()
    assert (output_dir / "manifest.json").exists()
    assert (output_dir / "source_audit.json").exists()
    candidates = read_jsonl(output_dir / "candidates.jsonl")
    assert {row["user_id"] for row in candidates} == {"u1", "u2"}
    assert any("semantic" in row["sources"] for row in candidates)
    persisted = read_json(output_dir / "manifest.json")
    assert persisted["source_artifact_signatures"]["semantic_inverted_index"]["row_count"] == 4


def test_representative_runner_rejects_10k_views_path(tmp_path):
    clean_dir, views_dir = make_fixture(tmp_path)
    bad_views = tmp_path / "amazon_2023_recall_views_10000"
    bad_views.mkdir()
    for child in views_dir.iterdir():
        bad_views.joinpath(child.name).write_bytes(child.read_bytes())

    with pytest.raises(ValueError, match="10k recall views"):
        run_representative_e2e(
            clean_dir=clean_dir,
            views_dir=bad_views,
            output_dir=tmp_path / "out",
            limit_users=1,
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_representative_runner_rejects_pool_curve_mode(tmp_path):
    clean_dir, views_dir = make_fixture(tmp_path)

    with pytest.raises(ValueError, match="Only --mode baseline"):
        run_representative_e2e(
            clean_dir=clean_dir,
            views_dir=views_dir,
            output_dir=tmp_path / "out",
            limit_users=1,
            mode="pool-curve",
            min_free_bytes=0,
            enforce_venv=False,
        )
