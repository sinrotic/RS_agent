from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.experiment, pytest.mark.gpu]

from rs_core.common.io import read_json, read_jsonl, write_json, write_jsonl
from rs_core.recsys.candidate_merge import load_two_tower_index, two_tower_candidates_for_user
from rs_core.recsys.vector_index import VectorIndex
from rs_core.recsys import two_tower
from rs_core.recsys.two_tower import save_two_tower_artifacts, train_two_tower_model
from rs_core.workflow.two_tower_training import build_two_tower_item_vocab, build_two_tower_seed_sidecar, build_two_tower_seed_sidecar_from_config, train_two_tower_recall
from scripts.training.train_two_tower import main as train_two_tower_cli_main


def _write_training_workflow_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir()

    write_jsonl(
        clean_dir / "user_sequences.train.jsonl",
        [
            {"user_id": "u1", "recent_positive_item_sequence": ["audio_seed", "audio_next"], "recent_item_sequence": ["audio_seed", "audio_next"]},
            {"user_id": "u2", "recent_positive_item_sequence": ["camera_seed", "camera_next"], "recent_item_sequence": ["camera_seed", "camera_next"]},
        ],
    )
    write_jsonl(
        clean_dir / "canonical_interactions.train.jsonl",
        [
            {"user_id": "u1", "parent_asin": "audio_seed"},
            {"user_id": "u1", "parent_asin": "audio_next"},
            {"user_id": "u2", "parent_asin": "camera_seed"},
            {"user_id": "u2", "parent_asin": "camera_next"},
        ],
    )
    write_jsonl(clean_dir / "canonical_items.jsonl", _items())
    vocab_manifest_path = tmp_path / "item_vocab" / "two_tower_item_vocab_manifest.json"
    build_two_tower_item_vocab(
        clean_dir / "canonical_interactions.train.jsonl",
        tmp_path / "item_vocab" / "two_tower_item_vocab.jsonl",
        vocab_manifest_path,
        clean_dir / "canonical_items.jsonl",
    )

    config_path = tmp_path / "config.json"
    write_json(
        config_path,
        {
            "clean_dir": str(clean_dir),
            "evaluation_mode": "train_only",
            "two_tower_training": {"variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn", "item_vocab_manifest": str(vocab_manifest_path)},
        },
    )
    user_quality_path = tmp_path / "eligible_user_quality_manifest.json"
    write_json(
        user_quality_path,
        {
            "policy_role": "eligibility_policy_not_recall_source",
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
            "profiles": [
                {"user_id": "u1", "quality_bucket": "heavy"},
                {"user_id": "u2", "quality_bucket": "medium"},
            ],
        },
    )
    return {"config": config_path, "user_quality": user_quality_path}


def _sequences() -> list[dict]:
    return [
        {"user_id": "u1", "recent_positive_item_sequence": ["audio_seed", "audio_next"], "recent_item_sequence": ["audio_seed", "audio_next"]},
        {"user_id": "u2", "recent_positive_item_sequence": ["camera_seed", "camera_next"], "recent_item_sequence": ["camera_seed", "camera_next"]},
    ]


def _items() -> list[dict]:
    return [
        {"parent_asin": "audio_seed", "title_clean": "wireless earbuds", "main_category": "Audio"},
        {"parent_asin": "audio_next", "title_clean": "bluetooth headphones", "main_category": "Audio"},
        {"parent_asin": "camera_seed", "title_clean": "mirrorless camera", "main_category": "Camera"},
        {"parent_asin": "camera_next", "title_clean": "camera tripod", "main_category": "Camera"},
    ]


def test_two_tower_item_vocab_is_canonical_train_only_and_metadata_does_not_expand(tmp_path: Path):
    train_path = tmp_path / "canonical_interactions.train.jsonl"
    metadata_path = tmp_path / "canonical_items.jsonl"
    vocab_path = tmp_path / "two_tower_item_vocab.jsonl"
    manifest_path = tmp_path / "two_tower_item_vocab_manifest.json"
    write_jsonl(train_path, [{"parent_asin": "train_a"}, {"item_id": "train_b"}, {"parent_asin": "train_a"}])
    write_jsonl(
        metadata_path,
        [
            {"parent_asin": "train_a", "title_clean": "kept metadata"},
            {"parent_asin": "metadata_only", "title_clean": "must not expand"},
        ],
    )

    manifest = build_two_tower_item_vocab(train_path, vocab_path, manifest_path, metadata_path)
    rows = read_jsonl(vocab_path)

    assert {row["parent_asin"] for row in rows} == {"train_a", "train_b"}
    assert {row["item_id"] for row in rows} == {"train_a", "train_b"}
    assert "metadata_only" not in {row["parent_asin"] for row in rows}
    assert manifest["item_count"] == len(rows) == 2
    assert manifest["metadata_join_added_items"] is False
    assert manifest["content_hash"].startswith("sha256:")
    assert read_json(manifest_path) == manifest


def test_two_tower_item_vocab_min_frequency_prunes_train_items_only(tmp_path: Path):
    train_path = tmp_path / "canonical_interactions.train.jsonl"
    metadata_path = tmp_path / "canonical_items.jsonl"
    vocab_path = tmp_path / "two_tower_item_vocab.jsonl"
    manifest_path = tmp_path / "two_tower_item_vocab_manifest.json"
    write_jsonl(train_path, [{"parent_asin": "keep_a"}, {"parent_asin": "keep_a"}, {"parent_asin": "drop_b"}])
    write_jsonl(metadata_path, [{"parent_asin": "keep_a"}, {"parent_asin": "drop_b"}, {"parent_asin": "metadata_only"}])

    manifest = build_two_tower_item_vocab(train_path, vocab_path, manifest_path, metadata_path, min_frequency=2)
    rows = read_jsonl(vocab_path)

    assert [row["parent_asin"] for row in rows] == ["keep_a"]
    assert manifest["item_count"] == 1
    assert manifest["original_item_count"] == 2
    assert manifest["filtered_item_count"] == 1
    assert manifest["min_frequency"] == 2
    assert manifest["metadata_join_added_items"] is False


def test_train_two_tower_recall_rejects_eval_scoped_item_vocab_manifest(tmp_path: Path):
    paths = _write_training_workflow_fixture(tmp_path)
    config = read_json(paths["config"])
    manifest_path = Path(config["two_tower_training"]["item_vocab_manifest"])
    manifest = read_json(manifest_path)
    manifest["source_paths"]["canonical_interactions_train"] = str(tmp_path / "canonical_interactions.valid.jsonl")
    write_json(manifest_path, manifest)

    with pytest.raises(ValueError, match="eval/valid/test/holdout"):
        train_two_tower_recall(
            paths["config"],
            output_dir=tmp_path / "artifacts",
            variant="youtube_dnn",
            config_overrides={"two_tower_training": {"embedding_dim": 8, "epochs": 1, "negative_samples": 1}},
        )


def test_train_two_tower_cli_blocks_default_and_explicit_all(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.json"
    write_json(config_path, {"clean_dir": str(tmp_path)})

    monkeypatch.setattr(sys, "argv", ["train_two_tower.py", "--config", str(config_path)])
    with pytest.raises(SystemExit, match="variant youtube_dnn"):
        train_two_tower_cli_main()

    monkeypatch.setattr(sys, "argv", ["train_two_tower.py", "--config", str(config_path), "--variant", "all"])
    with pytest.raises(SystemExit, match="variant youtube_dnn"):
        train_two_tower_cli_main()


def test_two_tower_artifacts_write_complete_default_off_contract(tmp_path: Path):
    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "dssm", "source_name": "two_tower_dssm", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )

    contract = save_two_tower_artifacts(result, tmp_path)
    manifest = json.loads(Path(contract["artifact_manifest"]).read_text(encoding="utf-8"))

    assert set(contract) == {
        "train_config",
        "model",
        "item_embeddings",
        "user_embeddings",
        "item_id_map",
        "user_id_map",
        "train_metrics",
        "recall_index",
        "artifact_manifest",
    }
    assert manifest["artifact_type"] == "two_tower_training_artifacts_v1"
    assert manifest["variant"] == "dssm"
    assert manifest["source_name"] == "two_tower_dssm"
    assert manifest["default_enabled"] is False
    assert manifest["contract"] == contract
    assert all(Path(path).exists() for path in contract.values())

    model = json.loads(Path(contract["model"]).read_text(encoding="utf-8"))
    metrics = json.loads(Path(contract["train_metrics"]).read_text(encoding="utf-8"))
    recall_rows = read_jsonl(contract["recall_index"])

    assert model["model_type"] == "dssm_two_tower_v1"
    assert model["default_enabled"] is False
    assert model["training_backend"] == metrics["training_backend"]
    assert "model_parameters" in model
    assert metrics["variant"] == "dssm"
    if two_tower._import_torch() is not None:
        assert metrics["training_backend"]["name"] == "pytorch"
        assert metrics["training_backend"]["torch_available"] is True
        assert metrics["training_backend"]["batch_training"] is True
        assert metrics["batch_size"] == 512
        assert metrics["training_seconds"] > 0
        assert "peak_cuda_memory_mb" in metrics
        assert metrics["loss_history"]
    else:
        assert metrics["training_backend"] == {"name": "python_fallback_vector_updates", "torch_available": False}
        assert metrics["loss_history"] == []
    assert metrics["users_with_training_rows"] == 2
    assert len(recall_rows) == 4
    assert {row["parent_asin"] for row in recall_rows} == {"audio_seed", "audio_next", "camera_seed", "camera_next"}


def test_two_tower_variants_keep_model_type_and_source_isolated(tmp_path: Path):
    variants = {
        "dssm": "two_tower_dssm",
        "youtube_dnn": "two_tower_youtube_dnn",
    }

    manifests = {}
    for variant, source_name in variants.items():
        result = train_two_tower_model(
            _sequences(),
            _items(),
            {"variant": variant, "source_name": source_name, "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
        )
        contract = save_two_tower_artifacts(result, tmp_path / variant)
        manifests[variant] = json.loads(Path(contract["artifact_manifest"]).read_text(encoding="utf-8"))

    assert manifests["dssm"]["source_name"] == "two_tower_dssm"
    assert manifests["youtube_dnn"]["source_name"] == "two_tower_youtube_dnn"
    assert manifests["dssm"]["contract"]["artifact_manifest"] != manifests["youtube_dnn"]["contract"]["artifact_manifest"]

    dssm_model = json.loads(Path(manifests["dssm"]["contract"]["model"]).read_text(encoding="utf-8"))
    youtube_model = json.loads(Path(manifests["youtube_dnn"]["contract"]["model"]).read_text(encoding="utf-8"))
    assert dssm_model["model_type"] == "dssm_two_tower_v1"
    assert youtube_model["model_type"] == "youtube_dnn_two_tower_v1"
    if two_tower._import_torch() is not None:
        assert dssm_model["training_backend"]["name"] == "pytorch"
        assert youtube_model["training_backend"]["name"] == "pytorch"
        assert dssm_model["training_backend"]["model_class"] != youtube_model["training_backend"]["model_class"]
    else:
        assert dssm_model["training_backend"]["name"] == "python_fallback_vector_updates"
        assert youtube_model["training_backend"]["name"] == "python_fallback_vector_updates"
    assert dssm_model["source_name"] != youtube_model["source_name"]


def test_backend_config_cannot_bypass_torch_when_torch_is_available():
    torch_module = two_tower._import_torch()
    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "dssm", "source_name": "two_tower_dssm", "backend": "python_fallback", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )

    backend = result["train_metrics"]["training_backend"]
    if torch_module is not None:
        assert backend["name"] == "pytorch"
        assert backend["torch_available"] is True
    else:
        assert backend == {"name": "python_fallback_vector_updates", "torch_available": False}
    assert result["model"]["training_backend"] == backend


def test_python_backend_is_labeled_as_no_torch_fallback(monkeypatch):
    monkeypatch.setattr(two_tower, "_import_torch", lambda: None)

    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "dssm", "source_name": "two_tower_dssm", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )

    backend = result["train_metrics"]["training_backend"]
    assert backend == {"name": "python_fallback_vector_updates", "torch_available": False}
    assert result["model"]["training_backend"] == backend



def test_saved_two_tower_manifest_loads_as_vector_index_with_model_metadata(tmp_path: Path):
    result = train_two_tower_model(
        _sequences(),
        _items(),
        {"variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn", "embedding_dim": 8, "epochs": 1, "negative_samples": 1},
    )
    contract = save_two_tower_artifacts(result, tmp_path)

    index = load_two_tower_index(contract["artifact_manifest"])
    assert isinstance(index, VectorIndex)
    assert index.source_name == "two_tower_youtube_dnn"
    assert index.model_metadata["variant"] == "youtube_dnn"
    assert index.model_metadata["model_type"] == "youtube_dnn_two_tower_v1"

    sequence = {"user_id": "u1", "recent_item_sequence": ["audio_seed"], "recent_positive_item_sequence": ["audio_seed"]}
    candidates = two_tower_candidates_for_user(sequence, index, {"two_tower_enabled": True, "two_tower_per_user": 3})

    assert candidates
    assert "audio_seed" not in {candidate.item_id for candidate in candidates}
    assert {candidate.metadata["two_tower_source_name"] for candidate in candidates} == {"two_tower_youtube_dnn"}
    assert {candidate.metadata["two_tower_model_type"] for candidate in candidates} == {"youtube_dnn_two_tower_v1"}


def test_train_two_tower_recall_filters_user_quality_policy(tmp_path: Path):
    paths = _write_training_workflow_fixture(tmp_path)
    output_dir = tmp_path / "artifacts"

    result = train_two_tower_recall(
        paths["config"],
        output_dir=output_dir,
        variant="youtube_dnn",
        config_overrides={"two_tower_training": {"embedding_dim": 8, "epochs": 1, "negative_samples": 1}},
        user_quality_manifest=paths["user_quality"],
        user_quality_bucket="heavy",
    )

    metrics = read_json(result["train_metrics_path"])
    user_embeddings = read_jsonl(result["user_embeddings_path"])
    assert metrics["training_input_users"] == 1
    assert metrics["split_scope"] == "train_only"
    assert metrics["leakage_checks"] == {"train_inputs_only": True, "eval_paths_rejected": True}
    assert metrics["item_vocab_size"] == 4
    assert Path(metrics["item_vocab_manifest_path"]).name == "two_tower_item_vocab_manifest.json"
    assert metrics["user_quality_selected_user_count"] == 1
    assert metrics["user_quality_matched_user_count"] == 1
    assert metrics["user_quality_bucket"] == "heavy"
    assert {row["user_id"] for row in user_embeddings} == {"u1"}


def test_train_two_tower_recall_rejects_user_quality_as_source(tmp_path: Path):
    paths = _write_training_workflow_fixture(tmp_path)
    policy = read_json(paths["user_quality"])
    policy["policy_role"] = "recall_source"
    write_json(paths["user_quality"], policy)

    with pytest.raises(ValueError, match="eligibility policy"):
        train_two_tower_recall(
            paths["config"],
            output_dir=tmp_path / "artifacts",
            variant="youtube_dnn",
            config_overrides={"two_tower_training": {"embedding_dim": 8, "epochs": 1, "negative_samples": 1}},
            user_quality_manifest=paths["user_quality"],
        )


def test_two_tower_seed_sidecar_schema_manifest_and_deterministic_sort(tmp_path: Path):
    embeddings_path = tmp_path / "item_embeddings.jsonl"
    sidecar_path = tmp_path / "two_tower_seed_neighbors.jsonl"
    manifest_path = tmp_path / "two_tower_seed_manifest.json"
    rows = [
        {"item_id": "b", "embedding": [1.0, 0.0], "embedding_norm": 1.0, "main_category": "", "category": "", "title_clean": ""},
        {"item_id": "a", "embedding": [1.0, 0.0], "embedding_norm": 1.0, "main_category": "", "category": "", "title_clean": ""},
        {"item_id": "c", "embedding": [0.0, 1.0], "embedding_norm": 1.0, "main_category": "", "category": "", "title_clean": ""},
    ]
    embeddings_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    manifest = build_two_tower_seed_sidecar(embeddings_path, sidecar_path, manifest_path, neighbor_k=2)
    sidecar_rows = read_jsonl(sidecar_path)
    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert sidecar_rows == [
        {"item_id": "a", "neighbors": [{"item_id": "b", "score": 1.0, "rank": 1}, {"item_id": "c", "score": 0.0, "rank": 2}]},
        {"item_id": "b", "neighbors": [{"item_id": "a", "score": 1.0, "rank": 1}, {"item_id": "c", "score": 0.0, "rank": 2}]},
        {"item_id": "c", "neighbors": [{"item_id": "a", "score": 0.0, "rank": 1}, {"item_id": "b", "score": 0.0, "rank": 2}]},
    ]
    assert set(manifest) == {
        "phase",
        "source",
        "created_at",
        "embedding_input_path",
        "sidecar_path",
        "item_count",
        "neighbor_k",
        "similarity",
        "deterministic_sort",
        "embedding_sha256",
        "sidecar_sha256",
        "config_sha256",
        "schema_version",
    }
    assert saved_manifest == manifest
    assert manifest["phase"] == "1.18"
    assert manifest["source"] == "two_tower_seed"
    assert manifest["item_count"] == 3
    assert manifest["neighbor_k"] == 2
    assert manifest["similarity"] == "cosine"
    assert manifest["deterministic_sort"] == "score_desc_item_id_asc"
    assert manifest["schema_version"] == "two_tower_seed_neighbors_v1"
    assert manifest["embedding_sha256"]
    assert manifest["sidecar_sha256"]


def test_two_tower_seed_sidecar_fails_closed_for_empty_duplicate_and_schema(tmp_path: Path):
    sidecar_path = tmp_path / "neighbors.jsonl"
    manifest_path = tmp_path / "manifest.json"
    empty_path = tmp_path / "empty.jsonl"
    empty_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty two_tower_seed embedding input"):
        build_two_tower_seed_sidecar(empty_path, sidecar_path, manifest_path, neighbor_k=1)

    duplicate_path = tmp_path / "duplicate.jsonl"
    duplicate_path.write_text(
        json.dumps({"item_id": "a", "embedding": [1.0]}) + "\n" + json.dumps({"item_id": "a", "embedding": [1.0]}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate two_tower_seed source item_id"):
        build_two_tower_seed_sidecar(duplicate_path, sidecar_path, manifest_path, neighbor_k=1)

    schema_path = tmp_path / "schema.jsonl"
    schema_path.write_text(json.dumps({"item_id": "a", "embedding": [1.0], "unexpected": True}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schema mismatch"):
        build_two_tower_seed_sidecar(schema_path, sidecar_path, manifest_path, neighbor_k=1)

    valid_input_path = tmp_path / "valid_input.jsonl"
    valid_input_path.write_text(json.dumps({"item_id": "a", "embedding": [1.0]}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="paths must be distinct"):
        build_two_tower_seed_sidecar(valid_input_path, valid_input_path, manifest_path, neighbor_k=1)
    with pytest.raises(ValueError, match="paths must be distinct"):
        build_two_tower_seed_sidecar(valid_input_path, sidecar_path, sidecar_path, neighbor_k=1)


def test_two_tower_seed_sidecar_cleanup_is_scoped_to_configured_outputs(tmp_path: Path):
    embeddings_path = tmp_path / "item_embeddings.jsonl"
    sidecar_path = tmp_path / "neighbors.jsonl"
    manifest_path = tmp_path / "manifest.json"
    untouched_path = tmp_path / "frozen_config.yaml"
    embeddings_path.write_text(
        json.dumps({"item_id": "a", "embedding": [1.0, 0.0]}) + "\n" + json.dumps({"item_id": "b", "embedding": [0.0, 1.0]}) + "\n",
        encoding="utf-8",
    )
    sidecar_path.write_text("stale sidecar", encoding="utf-8")
    manifest_path.write_text("stale manifest", encoding="utf-8")
    untouched_path.write_text("must stay", encoding="utf-8")

    build_two_tower_seed_sidecar(embeddings_path, sidecar_path, manifest_path, neighbor_k=1)

    assert read_jsonl(sidecar_path) == [{"item_id": "a", "neighbors": [{"item_id": "b", "score": 0.0, "rank": 1}]}, {"item_id": "b", "neighbors": [{"item_id": "a", "score": 0.0, "rank": 1}]}]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["sidecar_path"] == str(sidecar_path)
    assert untouched_path.read_text(encoding="utf-8") == "must stay"


def test_two_tower_seed_sidecar_builds_from_config(tmp_path: Path):
    embeddings_path = tmp_path / "item_embeddings.jsonl"
    sidecar_path = tmp_path / "neighbors.jsonl"
    manifest_path = tmp_path / "manifest.json"
    config_path = tmp_path / "config.yaml"
    embeddings_path.write_text(
        json.dumps({"item_id": "a", "embedding": [1.0, 0.0]}) + "\n" + json.dumps({"item_id": "b", "embedding": [1.0, 0.0]}) + "\n",
        encoding="utf-8",
    )
    config_path.write_text(
        f'two_tower_seed_sidecar:\n  embedding_input_path: "{embeddings_path}"\n  sidecar_path: "{sidecar_path}"\n  manifest_path: "{manifest_path}"\n  neighbor_k: 1\n',
        encoding="utf-8",
    )

    manifest = build_two_tower_seed_sidecar_from_config(config_path)

    assert manifest["config_sha256"]
    assert read_jsonl(sidecar_path) == [{"item_id": "a", "neighbors": [{"item_id": "b", "score": 1.0, "rank": 1}]}, {"item_id": "b", "neighbors": [{"item_id": "a", "score": 1.0, "rank": 1}]}]
