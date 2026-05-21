from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rs_lab.experiments.recall.build_pool500_two_tower_source_manifest import build_pool500_two_tower_source_manifest
from rs_core.common.io import read_json, write_json, write_jsonl
from rs_core.recsys.candidate_merge import load_two_tower_index
from rs_core.recsys.vector_index import VectorIndex
from rs_core.workflow.two_tower_training import _load_item_records


def test_build_pool500_two_tower_source_manifest_success(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    output_path = tmp_path / "final" / "source_index_manifest.json"

    manifest = build_pool500_two_tower_source_manifest(
        artifact_manifest=paths["artifact_manifest"],
        config=paths["config"],
        clean_manifest=paths["clean_manifest"],
        lightweight_views_manifest=paths["views_manifest"],
        output_path=output_path,
    )

    saved = read_json(output_path)
    index = load_two_tower_index(saved["recall_index_path"])
    assert saved == manifest
    assert isinstance(index, VectorIndex)
    assert saved["schema_version"] == "pool500_two_tower_source_index_manifest_v1"
    assert saved["source"] == "two_tower"
    assert saved["canonical_source"] == "two_tower"
    assert saved["source_name"] == "two_tower_youtube_dnn"
    assert saved["variant"] == "youtube_dnn"
    assert saved["model_type"] == "youtube_dnn_two_tower_v1"
    assert saved["index_scope"] == "FULL_DERIVED_INDEX"
    assert saved["readiness_status"] == "MAIN_ROUTE_ARTIFACT_ONLY"
    assert saved["recall_index_path"] == str(paths["artifact_manifest"].resolve())
    assert saved["artifact_manifest_path"] == str(paths["artifact_manifest"].resolve())
    assert saved["item_embedding_row_count"] == 3
    assert saved["recall_index_row_count"] == 3
    assert saved["user_embedding_row_count"] == 2
    assert saved["vector_index_item_count"] == 3
    assert len(index.items) == 3
    assert len(index.user_embeddings) == 2
    assert saved["clean_manifest_sha256"] == _sha256(paths["clean_manifest"])
    assert saved["train_sequence_sha256"] == _sha256(paths["train_sequences"])
    assert saved["model_config_sha256"] == _sha256(paths["config"])
    assert saved["item_universe_sha256"] == _expected_item_universe_sha256(paths["category_recall_items"], paths["popular_recall"])
    assert saved["forbidden_inputs_scan"]["status"] == "PASS"
    assert saved["forbidden_inputs_scan"]["forbidden_matches"] == []
    assert "source_index_manifest_sha256" not in saved
    for field in [
        "candidate_generation_allowed",
        "ranking_input_replacement_allowed",
        "pool1000_allowed",
        "auto_promotion_allowed",
        "promotion_allowed",
        "final_pool500_ready_claimed",
    ]:
        assert saved[field] is False


def test_build_pool500_two_tower_source_manifest_ignores_unused_clean_split_metadata(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    clean_manifest = read_json(paths["clean_manifest"])
    clean_manifest["split_paths"] = {
        "train": str(paths["train_sequences"]),
        "valid": str(tmp_path / "unused" / "valid.jsonl"),
        "test": str(tmp_path / "unused" / "test.jsonl"),
    }
    write_json(paths["clean_manifest"], clean_manifest)

    manifest = build_pool500_two_tower_source_manifest(
        artifact_manifest=paths["artifact_manifest"],
        config=paths["config"],
        clean_manifest=paths["clean_manifest"],
        lightweight_views_manifest=paths["views_manifest"],
        output_path=tmp_path / "final" / "source_index_manifest.json",
    )

    assert manifest["train_sequence_path"] == str(paths["train_sequences"].resolve())
    assert manifest["forbidden_inputs_scan"]["status"] == "PASS"


def test_build_pool500_two_tower_source_manifest_rejects_forbidden_contract_path(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    artifact = read_json(paths["artifact_manifest"])
    artifact["contract"]["model"] = "outputs/training/two_tower/two_tower_training/youtube_dnn/artifact_manifest.json"
    write_json(paths["artifact_manifest"], artifact)
    output_path = tmp_path / "final" / "source_index_manifest.json"

    with pytest.raises(ValueError, match="missing artifact contract path|forbidden"):
        build_pool500_two_tower_source_manifest(
            artifact_manifest=paths["artifact_manifest"],
            config=paths["config"],
            clean_manifest=paths["clean_manifest"],
            lightweight_views_manifest=paths["views_manifest"],
            output_path=output_path,
        )

    assert not output_path.exists()


def test_build_pool500_two_tower_source_manifest_rejects_empty_user_embeddings(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    paths["user_embeddings"].write_text("", encoding="utf-8")
    output_path = tmp_path / "final" / "source_index_manifest.json"

    with pytest.raises(ValueError, match="user_embedding_row_count"):
        build_pool500_two_tower_source_manifest(
            artifact_manifest=paths["artifact_manifest"],
            config=paths["config"],
            clean_manifest=paths["clean_manifest"],
            lightweight_views_manifest=paths["views_manifest"],
            output_path=output_path,
        )

    assert not output_path.exists()
    assert not (output_path.parent / "source_index_manifest.json.tmp").exists()


def test_build_pool500_two_tower_source_manifest_preserves_existing_final_on_failure(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    output_path = tmp_path / "final" / "source_index_manifest.json"
    output_path.parent.mkdir()
    output_path.write_text('{"existing": true}', encoding="utf-8")
    paths["recall_index"].write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="row counts|must equal"):
        build_pool500_two_tower_source_manifest(
            artifact_manifest=paths["artifact_manifest"],
            config=paths["config"],
            clean_manifest=paths["clean_manifest"],
            lightweight_views_manifest=paths["views_manifest"],
            output_path=output_path,
            overwrite=True,
        )

    assert read_json(output_path) == {"existing": True}
    assert not (output_path.parent / "source_index_manifest.json.tmp").exists()


def test_build_pool500_two_tower_source_manifest_records_user_quality_as_policy(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    user_quality = tmp_path / "quality" / "eligible_user_quality_manifest.json"
    write_json(user_quality, {"policy_role": "eligibility_policy_not_recall_source", "eligible_user_count": 2})
    output_path = tmp_path / "final" / "source_index_manifest.json"

    manifest = build_pool500_two_tower_source_manifest(
        artifact_manifest=paths["artifact_manifest"],
        config=paths["config"],
        clean_manifest=paths["clean_manifest"],
        lightweight_views_manifest=paths["views_manifest"],
        output_path=output_path,
        user_quality_manifest=user_quality,
    )

    assert manifest["user_quality_manifest_path"] == str(user_quality.resolve())
    assert manifest["user_quality_policy_role"] == "eligibility_policy_not_recall_source"
    assert manifest["user_quality_included_in_sources"] is False
    assert manifest["user_quality_ready_evidence"] is False


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    views_dir = tmp_path / "views"
    run_dir = tmp_path / "official" / "run_001"
    clean_dir.mkdir()
    views_dir.mkdir()
    run_dir.mkdir(parents=True)

    train_sequences = clean_dir / "user_sequences.train.jsonl"
    write_jsonl(
        train_sequences,
        [
            {"user_id": "u1", "recent_item_sequence": ["item_a"], "recent_positive_item_sequence": ["item_a"]},
            {"user_id": "u2", "recent_item_sequence": ["item_b"], "recent_positive_item_sequence": ["item_b"]},
        ],
    )
    canonical_items = clean_dir / "canonical_items.jsonl"
    write_jsonl(canonical_items, [{"parent_asin": "item_a"}, {"parent_asin": "item_b"}])
    clean_manifest = clean_dir / "manifest.json"
    write_json(
        clean_manifest,
        {
            "schema_version": "fixture_clean_v1",
            "train_user_sequences_path": str(train_sequences),
            "canonical_items_path": str(canonical_items),
        },
    )

    category_recall_items = views_dir / "category_recall_items.jsonl"
    popular_recall = views_dir / "popular_recall.jsonl"
    write_jsonl(category_recall_items, [{"parent_asin": "item_a", "main_category": "Audio"}, {"parent_asin": "item_c", "main_category": "Audio"}])
    write_jsonl(popular_recall, [{"parent_asin": "item_b", "main_category": "Popular"}, {"parent_asin": "item_c", "pop_score": 1.0}])
    views_manifest = views_dir / "manifest.json"
    write_json(
        views_manifest,
        {
            "schema_version": "fixture_views_v1",
            "outputs": {
                "category_recall_items": str(category_recall_items),
                "popular_recall": str(popular_recall),
            },
        },
    )

    config = tmp_path / "two_tower_full_clean_safe.yaml"
    write_json(
        config,
        {
            "schema_version": "two_tower_full_clean_safe_config_v1",
            "source_name": "two_tower_youtube_dnn",
            "canonical_source": "two_tower",
            "evaluation_mode": "train_only",
            "index_scope": "FULL_DERIVED_INDEX",
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "pool1000_allowed": False,
        },
    )

    train_config = run_dir / "train_config.json"
    model = run_dir / "two_tower_model.json"
    item_embeddings = run_dir / "item_embeddings.jsonl"
    user_embeddings = run_dir / "user_embeddings.jsonl"
    train_metrics = run_dir / "train_metrics.json"
    recall_index = run_dir / "two_tower_recall_index.jsonl"
    artifact_manifest = run_dir / "artifact_manifest.json"

    write_json(train_config, {"variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn"})
    write_json(model, {"model_type": "youtube_dnn_two_tower_v1", "variant": "youtube_dnn", "source_name": "two_tower_youtube_dnn"})
    rows = [
        {"item_id": "item_a", "parent_asin": "item_a", "embedding": [1.0, 0.0]},
        {"item_id": "item_b", "parent_asin": "item_b", "embedding": [0.0, 1.0]},
        {"item_id": "item_c", "parent_asin": "item_c", "embedding": [1.0, 1.0]},
    ]
    write_jsonl(item_embeddings, rows)
    write_jsonl(recall_index, rows)
    write_jsonl(user_embeddings, [{"user_id": "u1", "embedding": [1.0, 0.0]}, {"user_id": "u2", "embedding": [0.0, 1.0]}])
    write_json(train_metrics, {"variant": "youtube_dnn", "training_backend": {"name": "fixture"}, "users_with_training_rows": 2})
    write_json(
        artifact_manifest,
        {
            "artifact_type": "two_tower_training_artifacts_v1",
            "variant": "youtube_dnn",
            "source_name": "two_tower_youtube_dnn",
            "default_enabled": False,
            "contract": {
                "train_config": str(train_config),
                "model": str(model),
                "item_embeddings": str(item_embeddings),
                "user_embeddings": str(user_embeddings),
                "train_metrics": str(train_metrics),
                "recall_index": str(recall_index),
                "artifact_manifest": str(artifact_manifest),
            },
        },
    )
    return {
        "artifact_manifest": artifact_manifest,
        "config": config,
        "clean_manifest": clean_manifest,
        "views_manifest": views_manifest,
        "train_sequences": train_sequences,
        "category_recall_items": category_recall_items,
        "popular_recall": popular_recall,
        "user_embeddings": user_embeddings,
        "recall_index": recall_index,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _expected_item_universe_sha256(category_recall_items: Path, popular_recall: Path) -> str:
    digest = hashlib.sha256()
    for record in sorted(_load_item_records(category_recall_items, popular_recall), key=lambda row: str(row.get("parent_asin") or "")):
        digest.update(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
