from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from scripts.run_bounded_itemcf_covisit_dry_run import run_dry_run


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_clean_dir(tmp_path: Path) -> Path:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {
                "user_id": "u1",
                "recent_positive_item_sequence": ["a", "b", "c", "a"],
                "recent_item_sequence": ["a", "b", "c", "a"],
            },
            {
                "user_id": "u2",
                "recent_strong_positive_item_sequence": ["b", "c", "d"],
                "recent_positive_item_sequence": ["b", "c", "d"],
                "recent_item_sequence": ["b", "c", "d"],
            },
            {
                "user_id": "u3",
                "recent_positive_item_sequence": ["x"],
                "recent_item_sequence": ["x"],
            },
        ],
    )
    write_jsonl(clean_dir / "canonical_interactions.valid.jsonl", [{"must_not_be_read": True}])
    write_jsonl(clean_dir / "canonical_interactions.test.jsonl", [{"must_not_be_read": True}])
    return clean_dir


def test_dry_run_writes_manifest_only_and_uses_train_sequences(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "bounded_itemcf_covisit_dry_run_estimate"

    manifest = run_dry_run(
        clean_dir=clean_dir,
        output_dir=output_dir,
        limit_users=3,
        sample_users=2,
        max_history_items=3,
        max_pairs_per_user=2,
        top_neighbors_per_item=2,
        max_item_degree=10,
        shard_count=4,
        min_free_bytes=0,
        enforce_venv=False,
    )

    persisted = read_json(output_dir / "manifest.json")
    assert persisted == manifest
    assert manifest["train_only"] is True
    assert manifest["holdout_contract"]["uses_holdout"] is False
    assert manifest["holdout_contract"]["source_file"] == "user_sequences.train.jsonl"
    assert manifest["config_caps"]["limit_users"] == 3
    assert manifest["config_caps"]["sample_users"] == 2
    assert manifest["sampled_users"] == 2
    assert manifest["users_scanned"] == 2
    assert manifest["estimated_pair_rows"] > 0
    assert len(manifest["estimated_shard_bytes"]) == 4
    assert manifest["disk_free_bytes"] >= 0
    assert manifest["safety_flags"]["bounded_pair_counter_only"] is True
    assert manifest["disabled_outputs"] == {
        "neighbor_sidecar_build": True,
        "neighbor_files": True,
        "shard_files": True,
        "recall_views": True,
    }
    assert sorted(path.name for path in output_dir.iterdir()) == ["manifest.json"]


def test_dry_run_counts_pairs_dropped_by_user_cap(tmp_path: Path) -> None:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b", "c", "d", "e"]}],
    )

    manifest = run_dry_run(
        clean_dir=clean_dir,
        output_dir=tmp_path / "out",
        limit_users=1,
        sample_users=1,
        max_history_items=5,
        max_pairs_per_user=2,
        top_neighbors_per_item=10,
        max_item_degree=10,
        shard_count=4,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert manifest["bounded_pair_updates"] == 2
    assert manifest["pairs_dropped_by_cap"] == 8



def test_dry_run_rejects_10k_clean_path(tmp_path: Path) -> None:
    clean_dir = tmp_path / "amazon_2023_recall_clean_10000"
    write_jsonl(clean_dir / "user_sequences.train.jsonl", [{"user_id": "u1", "recent_item_sequence": ["a"]}])

    with pytest.raises(ValueError, match="Forbidden 10k path"):
        run_dry_run(
            clean_dir=clean_dir,
            output_dir=tmp_path / "out",
            limit_users=1,
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_dry_run_rejects_existing_output_dir(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(FileExistsError, match="Output directory already exists"):
        run_dry_run(
            clean_dir=clean_dir,
            output_dir=output_dir,
            limit_users=1,
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_dry_run_rejects_output_inside_clean_dir(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)

    with pytest.raises(ValueError, match="must not be inside clean dir"):
        run_dry_run(
            clean_dir=clean_dir,
            output_dir=clean_dir / "estimate",
            limit_users=1,
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_dry_run_enforces_limit_users_cap(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)

    with pytest.raises(ValueError, match="--limit-users must be between"):
        run_dry_run(
            clean_dir=clean_dir,
            output_dir=tmp_path / "out",
            limit_users=1001,
            min_free_bytes=0,
            enforce_venv=False,
        )
