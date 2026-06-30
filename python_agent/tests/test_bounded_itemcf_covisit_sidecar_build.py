from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_lab.experiments.recall.run_bounded_itemcf_covisit_sidecar_build import run_sidecar_build


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
    write_jsonl(clean_dir / "holdout.jsonl", [{"must_not_be_read": True}])
    return clean_dir


def build_for_test(clean_dir: Path, output_dir: Path, **kwargs) -> dict:
    return run_sidecar_build(
        clean_dir=clean_dir,
        output_dir=output_dir,
        limit_users=kwargs.pop("limit_users", 3),
        max_history_items=kwargs.pop("max_history_items", 3),
        max_pairs_per_user=kwargs.pop("max_pairs_per_user", 10),
        top_neighbors_per_item=kwargs.pop("top_neighbors_per_item", 2),
        max_item_degree=kwargs.pop("max_item_degree", 10),
        shard_count=kwargs.pop("shard_count", 4),
        min_free_bytes=kwargs.pop("min_free_bytes", 0),
        enforce_venv=kwargs.pop("enforce_venv", False),
        **kwargs,
    )


def test_sidecar_build_writes_only_manifest_audit_and_neighbor_shards(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "bounded_itemcf_covisit_sidecar"

    manifest = build_for_test(clean_dir, output_dir)

    persisted_manifest = read_json(output_dir / "manifest.json")
    source_audit = read_json(output_dir / "source_audit.json")
    assert persisted_manifest == manifest
    assert manifest["train_only"] is True
    assert source_audit["train_only"] is True
    assert manifest["holdout_contract"] == {
        "uses_holdout": False,
        "source_file": "user_sequences.train.jsonl",
        "allowed_inputs": ["clean_dir/user_sequences.train.jsonl"],
        "forbidden_inputs": [
            "canonical_interactions.valid.jsonl",
            "canonical_interactions.test.jsonl",
            "holdout files",
        ],
    }
    assert source_audit["holdout_contract"] == manifest["holdout_contract"]
    assert source_audit["read_files"] == [str((clean_dir / "user_sequences.train.jsonl").resolve())]
    read_names = [Path(path).name for path in source_audit["read_files"]]
    assert read_names == ["user_sequences.train.jsonl"]
    assert all("valid" not in name and "test" not in name and "holdout" not in name for name in read_names)
    assert manifest["disabled_outputs"]["valid_reads"] is True
    assert manifest["disabled_outputs"]["test_reads"] is True
    assert manifest["disabled_outputs"]["holdout_reads"] is True
    assert manifest["safety_flags"]["train_only"] is True
    assert manifest["safety_flags"]["project_venv_enforced"] is False

    expected_files = {"manifest.json", "source_audit.json"} | {f"neighbors_shard_{index:05d}.jsonl" for index in range(4)}
    assert {path.name for path in output_dir.iterdir()} == expected_files
    assert sorted(manifest["outputs"]) == ["manifest", "neighbor_shards", "source_audit"]
    assert len(manifest["outputs"]["neighbor_shards"]) == 4
    assert len(manifest["shards"]) == 4
    shard_rows = []
    for shard_path in manifest["outputs"]["neighbor_shards"]:
        shard_rows.extend(read_jsonl(Path(shard_path)))
    assert {row["src_item"] for row in shard_rows} == {"a", "b", "c", "d"}


def test_sidecar_build_rejects_10k_clean_and_views_paths(tmp_path: Path) -> None:
    clean_dir = tmp_path / "amazon_2023_recall_clean_10000"
    write_jsonl(clean_dir / "user_sequences.train.jsonl", [{"user_id": "u1", "recent_item_sequence": ["a"]}])

    with pytest.raises(ValueError, match="Forbidden 10k path"):
        build_for_test(clean_dir, tmp_path / "out")

    clean_dir = make_clean_dir(tmp_path)
    with pytest.raises(ValueError, match="Forbidden 10k path"):
        build_for_test(clean_dir, tmp_path / "amazon_2023_recall_views_10000" / "out")


def test_sidecar_build_rejects_existing_output_dir(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(FileExistsError, match="Output directory already exists"):
        build_for_test(clean_dir, output_dir)


def test_sidecar_build_rejects_output_inside_clean_dir(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)

    with pytest.raises(ValueError, match="must not be inside clean dir"):
        build_for_test(clean_dir, clean_dir / "sidecar")


def test_sidecar_build_enforces_limit_users_cap(tmp_path: Path) -> None:
    clean_dir = make_clean_dir(tmp_path)

    with pytest.raises(ValueError, match="--limit-users must be between"):
        build_for_test(clean_dir, tmp_path / "out", limit_users=1001)


def test_sidecar_build_counts_pairs_dropped_by_user_cap(tmp_path: Path) -> None:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b", "c", "d", "e"]}],
    )

    manifest = build_for_test(
        clean_dir,
        tmp_path / "out",
        limit_users=1,
        max_history_items=5,
        max_pairs_per_user=2,
        top_neighbors_per_item=10,
    )

    assert manifest["processed_users"] == 1
    assert manifest["pair_updates"] == 2
    assert manifest["pairs_dropped_by_cap"] == 8


def test_sidecar_build_respects_top_neighbors_per_item_cap(tmp_path: Path) -> None:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["anchor", "b", "c", "d"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["anchor", "b", "c", "e"]},
        ],
    )

    manifest = build_for_test(
        clean_dir,
        tmp_path / "out",
        limit_users=2,
        max_history_items=4,
        max_pairs_per_user=10,
        top_neighbors_per_item=1,
    )

    shard_rows = []
    for shard_path in manifest["outputs"]["neighbor_shards"]:
        shard_rows.extend(read_jsonl(Path(shard_path)))
    assert shard_rows
    assert all(len(row["neighbors"]) <= 1 for row in shard_rows)
    anchor_row = next(row for row in shard_rows if row["src_item"] == "anchor")
    assert anchor_row["neighbors"] == [{"item_id": "b", "score": 1.0, "cooc_cnt": 2}]
