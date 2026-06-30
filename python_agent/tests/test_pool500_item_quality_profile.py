from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_train_only_data_governance import build_train_only_data_governance

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _make_manifest(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "clean_full"
    interactions = [
        _interaction("u1", "dup", 1),
        _interaction("u1", "dup", 2),
        _interaction("u1", "dup", 3),
        _interaction("u2", "hot", 4),
        _interaction("u3", "hot", 5),
        _interaction("u4", "hot", 6),
    ]
    _write_jsonl(clean_dir / "canonical_interactions.train.jsonl", interactions)
    _write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            _sequence("u1", ["dup", "dup", "dup"]),
            _sequence("u2", ["hot"]),
            _sequence("u3", ["hot"]),
            _sequence("u4", ["hot"]),
        ],
    )
    _write_jsonl(
        clean_dir / "canonical_items.jsonl",
        [
            {"parent_asin": "dup", "title": "Duplicate item", "category": "Office", "main_category": "Office"},
            {"parent_asin": "hot", "title": "Hot item", "category": "Electronics", "main_category": "Electronics"},
            {"parent_asin": "cold_catalog", "title": "Catalog only", "category": "Office", "main_category": "Office"},
        ],
    )
    manifest = clean_dir / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "train_user_sequences_path": "user_sequences.train.jsonl",
                "canonical_items_path": "canonical_items.jsonl",
                "split_paths": {"train": "canonical_interactions.train.jsonl"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


def _interaction(user_id: str, parent_asin: str, timestamp: int) -> dict[str, object]:
    return {
        "user_id": user_id,
        "parent_asin": parent_asin,
        "category": "Electronics" if parent_asin == "hot" else "Office",
        "main_category": "Electronics" if parent_asin == "hot" else "Office",
        "timestamp": timestamp,
        "label_binary": 1,
        "split": "train",
    }


def _sequence(user_id: str, items: list[str]) -> dict[str, object]:
    return {
        "user_id": user_id,
        "sequence_len": len(items),
        "positive_sequence_len": len(items),
        "recent_item_sequence": items,
        "recent_positive_item_sequence": items,
    }


def test_item_quality_profile_has_required_p1_fields_and_v2_bucket(tmp_path: Path) -> None:
    output_dir = tmp_path / "governance"

    build_train_only_data_governance(
        clean_manifest_path=_make_manifest(tmp_path),
        output_dir=output_dir,
        overwrite=True,
        enforce_venv=False,
    )

    profiles = {row["parent_asin"]: row for row in _read_jsonl(output_dir / "item_quality_profile.jsonl")}
    required_fields = {
        "parent_asin",
        "positive_event_count",
        "unique_positive_user_count",
        "train_interaction_count",
        "train_positive_count",
        "train_strong_positive_count",
        "global_pop_rank",
        "category",
        "main_category",
        "category_pop_rank",
        "title_ready",
        "category_ready",
        "text_ready",
        "semantic_ready",
        "cf_ready",
        "two_tower_ready",
        "fallback_ready",
        "hotness_bucket",
        "quality_bucket",
        "bucket_reason",
        "dropped_reasons",
        "train_only",
        "source_layer",
    }
    dup = profiles["dup"]
    assert required_fields <= set(dup)
    assert "quality_bucket_v2" in dup or "behavior_bucket_v2" in dup
    assert dup["positive_event_count"] == 3
    assert dup["unique_positive_user_count"] == 1
    assert dup["train_only"] is True
    assert dup["source_layer"] == "governance_train_only_v1"

    hot = profiles["hot"]
    bucket_v2 = hot.get("quality_bucket_v2", hot.get("behavior_bucket_v2"))
    assert bucket_v2 == "two_tower_train_eligible"

    catalog_only = profiles["cold_catalog"]
    assert catalog_only["positive_event_count"] == 0
    assert catalog_only["unique_positive_user_count"] == 0
    assert catalog_only.get("quality_bucket_v2", catalog_only.get("behavior_bucket_v2")) == "no_positive"
    assert catalog_only["train_only"] is True
    assert catalog_only["source_layer"] == "governance_train_only_v1"
