from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
pytestmark = [pytest.mark.experiment, pytest.mark.slow]

from rs_core.common.io import write_jsonl
from rs_core.online.recall.candidate_merge import load_graph_walk_seed_recall
from rs_core.workflow import graph_walk_training as gwt


def test_graph_walk_training_is_deterministic_nonzero_and_writes_valid_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(gwt, "ROOT", tmp_path)
    monkeypatch.setitem(gwt._resolve_path.__globals__, "ROOT", tmp_path)
    monkeypatch.setattr(gwt.torch.cuda, "is_available", lambda: False)
    clean = tmp_path / "clean"
    views = tmp_path / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [
        {"user_id": "u1", "recent_positive_item_sequence": ["a", "b", "c"], "recent_strong_positive_item_sequence": []},
        {"user_id": "u2", "recent_positive_item_sequence": ["a", "b", "d"], "recent_strong_positive_item_sequence": ["d", "c"]},
    ])
    config_path = tmp_path / "config.yaml"
    training_config = {
        "algorithm": "deepwalk",
        "seed": 7,
        "walk_length": 4,
        "walks_per_node": 2,
        "window_size": 1,
        "embedding_dim": 4,
        "epochs": 1,
        "negative_samples": 2,
        "learning_rate": 0.01,
        "batch_size": 8,
        "neighbor_k": 2,
        "similarity_chunk_size": 2,
        "sidecar_path": "outputs/training/graph_walk/graph_walk_seed_neighbors.jsonl",
        "manifest_path": "outputs/training/graph_walk/graph_walk_seed_manifest.json",
        "embeddings_path": "outputs/training/graph_walk/graph_walk_seed_embeddings.jsonl",
    }
    config_path.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "graph_walk_training": training_config,
    }), encoding="utf-8")

    first = gwt.train_graph_walk_seed(config_path)
    first_embeddings = Path(first["embeddings_path"]).read_text(encoding="utf-8")
    first_sidecar = Path(first["sidecar_path"]).read_text(encoding="utf-8")
    second = gwt.train_graph_walk_seed(config_path)

    assert Path(second["embeddings_path"]).read_text(encoding="utf-8") == first_embeddings
    assert Path(second["sidecar_path"]).read_text(encoding="utf-8") == first_sidecar
    embeddings = [json.loads(line) for line in first_embeddings.splitlines()]
    sidecar_rows = [json.loads(line) for line in first_sidecar.splitlines()]
    assert embeddings
    assert all(any(abs(value) > 0.0 for value in row["embedding"]) for row in embeddings)
    assert all(row["src_item"] != row["dst_item"] for row in sidecar_rows)
    assert all(row["source"] == "graph_walk_seed" and row["algorithm"] == "deepwalk" for row in sidecar_rows)

    manifest = second["manifest"]
    assert manifest["phase"] == "1.19"
    assert manifest["source"] == "graph_walk_seed"
    assert manifest["schema_version"] == "graph_walk_seed_pairs_v1"
    assert manifest["algorithm"] == "deepwalk"
    assert manifest["device"] == "cpu"
    assert manifest["sidecar_hash"] == _sha256_file(Path(second["sidecar_path"]))
    assert manifest["embeddings_hash"] == _sha256_file(Path(second["embeddings_path"]))


def test_graph_walk_sidecar_manifest_validation_fails_closed(tmp_path: Path):
    sidecar_path = tmp_path / "graph_walk_seed_neighbors.jsonl"
    manifest_path = tmp_path / "graph_walk_seed_manifest.json"
    write_jsonl(sidecar_path, [{"src_item": "seed", "dst_item": "rec", "score": 1.0, "source": "graph_walk_seed", "algorithm": "deepwalk"}])
    base_manifest = {
        "phase": "1.19",
        "source": "graph_walk_seed",
        "schema_version": "graph_walk_seed_pairs_v1",
        "algorithm": "deepwalk",
        "sidecar_hash": _sha256_file(sidecar_path),
    }
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    assert [candidate.item_id for candidate in load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)["seed"]] == ["rec"]

    for field, value in (("phase", "1.18"), ("source", "item_graph"), ("algorithm", "node2vec")):
        manifest_path.write_text(json.dumps(base_manifest | {field: value}), encoding="utf-8")
        with pytest.raises(ValueError, match=f"invalid graph_walk_seed manifest {field}"):
            load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)

    manifest_path.write_text(json.dumps(base_manifest | {"sidecar_hash": "bad"}), encoding="utf-8")
    with pytest.raises(ValueError, match="sidecar_hash: mismatch"):
        load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)

    write_jsonl(sidecar_path, [{"src_item": "seed", "dst_item": "rec", "score": 1.0, "source": "graph_walk_seed", "algorithm": "node2vec"}])
    manifest_path.write_text(json.dumps(base_manifest | {"sidecar_hash": _sha256_file(sidecar_path)}), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid graph_walk_seed sidecar algorithm"):
        load_graph_walk_seed_recall(sidecar_path, manifest_path=manifest_path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
