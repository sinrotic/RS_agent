from __future__ import annotations

import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall import build_full_train_swing_sidecar as swing_sidecar

pytestmark = pytest.mark.unit


def test_full_train_swing_sidecar_writes_edges_and_manifests(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b", "item_c"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_b"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["seed", "item_c"]},
        ],
    )
    output_dir = tmp_path / "out"

    manifest = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=10,
        max_user_items=10,
        min_pair_support=2,
        per_seed_top_k=1,
        min_score=0.0,
        min_free_bytes=0,
        enforce_venv=False,
    )

    edges = _read_jsonl(output_dir / "swing_recall_edges.jsonl")
    seed_edges = [edge for edge in edges if edge["src_item"] == "seed"]
    assert len(seed_edges) == 1
    assert seed_edges[0] == {
        "src_item": "seed",
        "dst_item": "item_b",
        "score": 1.090909,
        "rank": 1,
        "source": "swing_recall",
    }
    assert all(set(edge) == {"src_item", "dst_item", "score", "rank", "source"} for edge in edges)

    source_manifest = json.loads((output_dir / "source_index_manifest.json").read_text(encoding="utf-8"))
    selection_manifest = json.loads((output_dir / "custom_index_selection_manifest.json").read_text(encoding="utf-8"))
    no_holdout_audit = json.loads((output_dir / "no_holdout_audit.json").read_text(encoding="utf-8"))
    resource_audit = json.loads((output_dir / "resource_audit.json").read_text(encoding="utf-8"))

    assert manifest == source_manifest
    for payload in [source_manifest, selection_manifest, no_holdout_audit]:
        assert payload["index_scope"] == "FULL_DERIVED_INDEX"
        assert payload["train_only"] is True
        assert payload["candidate_generation_allowed"] is False
        assert payload["ranking_input_replacement_allowed"] is False
        assert payload["pool1000_allowed"] is False
    assert selection_manifest["ranking_input_replacement"] is False
    assert selection_manifest["declared_inputs"] == [str((tmp_path / "clean" / "user_sequences.train.jsonl").resolve())]
    assert no_holdout_audit["read_files"] == [str((tmp_path / "clean" / "user_sequences.train.jsonl").resolve())]
    assert no_holdout_audit["valid_test_holdout_usage"] == "not_read"
    assert resource_audit["edge_count"] == len(edges)
    assert resource_audit["shard_audit"]["strategy"] == "src_item_prefix_2_audit_only"


def test_full_train_swing_sidecar_drops_hot_items(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["hot", "item_a"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["hot", "item_a"]},
            {"user_id": "u3", "recent_positive_item_sequence": ["hot", "item_b"]},
        ],
    )
    output_dir = tmp_path / "out"

    swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=output_dir,
        max_item_user_freq=2,
        max_user_items=10,
        min_pair_support=1,
        per_seed_top_k=10,
        min_score=0.0,
        min_free_bytes=0,
        enforce_venv=False,
    )

    edges = _read_jsonl(output_dir / "swing_recall_edges.jsonl")
    dropped = json.loads((output_dir / "dropped_hot_items.json").read_text(encoding="utf-8"))
    assert dropped["items"] == [{"item_id": "hot", "train_user_freq": 3}]
    assert all(edge["src_item"] != "hot" and edge["dst_item"] != "hot" for edge in edges)


def test_full_train_swing_sidecar_resolves_clean_manifest_path_from_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = tmp_path / "repo"
    data_dir = repo_root / "data" / "processed" / "amazon_2023_recall_clean_full"
    data_dir.mkdir(parents=True)
    train_path = data_dir / "user_sequences.train.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    manifest_dir = data_dir / "manifests"
    manifest_dir.mkdir()
    clean_manifest = manifest_dir / "manifest.json"
    clean_manifest.write_text(
        json.dumps({"train_user_sequences_path": "data/processed/amazon_2023_recall_clean_full/user_sequences.train.jsonl"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(swing_sidecar, "ROOT", repo_root)

    manifest = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out",
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert manifest["train_user_sequences_path"] == str(train_path.resolve())


def test_full_train_swing_sidecar_stable_manifest_content_across_output_dirs(tmp_path: Path) -> None:
    clean_manifest = _write_clean_fixture(
        tmp_path,
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["seed", "item_b", "item_c"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["seed", "item_b"]},
        ],
    )

    first = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out_first",
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )
    second = swing_sidecar.build_full_train_swing_sidecar(
        clean_manifest_path=clean_manifest,
        output_dir=tmp_path / "out_second",
        min_pair_support=1,
        min_free_bytes=0,
        enforce_venv=False,
    )

    assert first == second
    first_resource = json.loads((tmp_path / "out_first" / "resource_audit.json").read_text(encoding="utf-8"))
    second_resource = json.loads((tmp_path / "out_second" / "resource_audit.json").read_text(encoding="utf-8"))
    assert first_resource == second_resource
    assert first["generated_at"] == "excluded_from_canonical_sha"
    assert first["output_dir"] == "excluded_from_canonical_sha"
    assert first["runtime_seconds"] == "excluded_from_canonical_sha"
    assert first_resource["disk_free_bytes_start"] == "excluded_from_canonical_sha"
    assert first_resource["disk_free_bytes_end"] == "excluded_from_canonical_sha"


def test_full_train_swing_sidecar_manifest_requires_train_sequence_path(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

    with pytest.raises(ValueError, match="train_user_sequences_path"):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            min_free_bytes=0,
            enforce_venv=False,
        )


def test_full_train_swing_sidecar_rejects_holdout_path(tmp_path: Path) -> None:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()
    train_path = clean_dir / "user_sequences.valid.jsonl"
    _write_jsonl(train_path, [{"user_id": "u1", "recent_positive_item_sequence": ["a", "b"]}])
    clean_manifest = clean_dir / "manifest.json"
    clean_manifest.write_text(json.dumps({"train_user_sequences_path": str(train_path)}), encoding="utf-8")

    with pytest.raises(ValueError, match="user_sequences.train.jsonl|Forbidden"):
        swing_sidecar.build_full_train_swing_sidecar(
            clean_manifest_path=clean_manifest,
            output_dir=tmp_path / "out",
            min_free_bytes=0,
            enforce_venv=False,
        )


def _write_clean_fixture(root: Path, rows: list[dict[str, object]]) -> Path:
    clean_dir = root / "clean"
    clean_dir.mkdir()
    sequence_path = clean_dir / "user_sequences.train.jsonl"
    _write_jsonl(sequence_path, rows)
    manifest_path = clean_dir / "manifest.json"
    manifest_path.write_text(json.dumps({"status": "PASS", "train_user_sequences_path": str(sequence_path)}), encoding="utf-8")
    return manifest_path


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
