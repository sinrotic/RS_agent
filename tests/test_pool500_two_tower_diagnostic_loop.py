from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_core.recsys.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_lab.experiments.recall import run_pool500_two_tower_diagnostic_loop as diagnostic_module
from rs_lab.experiments.recall.run_pool500_two_tower_diagnostic_loop import run_pool500_two_tower_diagnostic_loop

pytestmark = pytest.mark.unit

FORBIDDEN_ARTIFACT_TOKENS = ("oracle", "label", "valid", "validation", "test", "holdout", "eval")


def test_two_tower_diagnostic_loop_writes_guarded_train_only_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _write_method_dataset_fixture(tmp_path)
    _patch_training(monkeypatch)

    report = run_pool500_two_tower_diagnostic_loop(
        method_dataset_manifest_path=paths["method_manifest"],
        output_dir=tmp_path / "diagnostic_loop",
        limit_users=2,
        top_k=2,
        metric_ks=[1, 2],
        embedding_dim=2,
        hidden_dim=2,
        epochs=1,
        negative_samples=1,
        batch_size=4,
        overwrite=True,
        enforce_venv=False,
    )

    output_dir = tmp_path / "diagnostic_loop"
    persisted_report = read_json(output_dir / "diagnostic_report.json")
    manifest = read_json(output_dir / "diagnostic_manifest.json")
    assert persisted_report == manifest == report
    assert report["schema_version"] == "pool500_two_tower_diagnostic_loop_v1"
    assert report["status"] == "PASS"
    assert report["diagnostic_only"] is True
    assert report["candidate_generation_allowed"] is False
    assert report["ranking_input_replacement_allowed"] is False
    assert report["promotion_allowed"] is False
    assert report["final_pool500_ready_claimed"] is False
    assert report["split_scope"] == "train_only"
    assert report["leakage_checks"] == {"train_inputs_only": True, "eval_paths_rejected": True}
    assert report["no_oracle_label_injection"] is True
    assert report["diagnostic_topk_row_count"] == 4
    assert report["source_index_row_count"] == 3
    assert report["training"] == {
        "variant": "youtube_dnn",
        "limit_users": 2,
        "embedding_dim": 2,
        "hidden_dim": 2,
        "epochs": 1,
        "negative_samples": 1,
        "batch_size": 4,
        "training_input_users": 2,
        "users_with_training_rows": 2,
    }
    assert "READY" not in json.dumps(report, ensure_ascii=False)
    assert "promotion" not in json.dumps({"status": report["status"], "retrieval_metrics": report["retrieval_metrics"]}, ensure_ascii=False).lower()

    train_config = read_json(output_dir / "train_only_compat_inputs" / "two_tower_train_config.json")
    item_vocab_manifest = read_json(output_dir / "train_only_compat_inputs" / "two_tower_item_vocab_manifest.json")
    assert train_config["evaluation_mode"] == "train_only"
    assert item_vocab_manifest["split_scope"] == "train_only"
    assert item_vocab_manifest["diagnostic_only"] is True
    assert item_vocab_manifest["source_paths"] == {
        "canonical_interactions_train": str((output_dir / "train_only_compat_inputs" / "canonical_interactions.train.jsonl").resolve()),
        "p2_training_item_universe": str(paths["training_item_universe"].resolve()),
    }
    _assert_no_forbidden_artifact_paths(train_config)
    _assert_no_forbidden_artifact_paths(item_vocab_manifest["source_paths"])


def test_two_tower_diagnostic_loop_reports_denominators_metrics_topk_and_source_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _write_method_dataset_fixture(tmp_path)
    _patch_training(monkeypatch)

    run_pool500_two_tower_diagnostic_loop(
        method_dataset_manifest_path=paths["method_manifest"],
        output_dir=tmp_path / "diagnostic_loop",
        limit_users=2,
        top_k=2,
        metric_ks="1,2",
        overwrite=True,
        enforce_venv=False,
    )

    output_dir = tmp_path / "diagnostic_loop"
    metrics = read_json(output_dir / "diagnostic_metrics.json")
    assert metrics == {
        "schema_version": "pool500_two_tower_diagnostic_loop_v1.metrics",
        "metric_ks": [1, 2],
        "user_count": 2,
        "all_target_denominator": 2,
        "in_universe_target_denominator": 1,
        "all_target_recall_at_1": 0.5,
        "in_universe_recall_at_1": 1.0,
        "all_target_hit_rate_at_1": 0.5,
        "in_universe_hit_rate_at_1": 0.5,
        "all_target_recall_at_2": 0.5,
        "in_universe_recall_at_2": 1.0,
        "all_target_hit_rate_at_2": 0.5,
        "in_universe_hit_rate_at_2": 0.5,
    }

    topk_rows = _read_jsonl(output_dir / "diagnostic_topk.jsonl")
    assert topk_rows == [
        {"user_id": "u1", "item_id": "item_b", "rank": 1, "score": 1.0, "source": "two_tower_diagnostic", "sources": ["two_tower_diagnostic"]},
        {"user_id": "u1", "item_id": "item_a", "rank": 2, "score": 0.2, "source": "two_tower_diagnostic", "sources": ["two_tower_diagnostic"]},
        {"user_id": "u2", "item_id": "item_c", "rank": 1, "score": 1.0, "source": "two_tower_diagnostic", "sources": ["two_tower_diagnostic"]},
        {"user_id": "u2", "item_id": "item_a", "rank": 2, "score": 0.0, "source": "two_tower_diagnostic", "sources": ["two_tower_diagnostic"]},
    ]

    source_manifest_path = output_dir / "source_index" / "source_index_manifest.json"
    source_manifest = validate_two_tower_source_index_manifest(source_manifest_path)
    assert source_manifest["schema_version"] == "two_tower_source_index_v1"
    assert source_manifest["source"] == "two_tower"
    assert source_manifest["canonical_source"] == "two_tower"
    assert source_manifest["source_name"] == "two_tower_youtube_dnn"
    assert source_manifest["variant"] == "youtube_dnn"
    assert source_manifest["model_type"] == "youtube_dnn_two_tower_v1"
    assert source_manifest["index_scope"] == "FULL_DERIVED_INDEX"
    assert source_manifest["row_count"] == 3
    assert source_manifest["embedding_row_count"] == 3
    assert source_manifest["index_row_count"] == 3
    assert source_manifest["user_embedding_row_count"] == 2
    assert source_manifest["content_hash"].startswith("sha256:")
    _assert_no_forbidden_artifact_paths(source_manifest)


def test_two_tower_diagnostic_loop_rejects_manifest_without_diagnostic_guards(tmp_path: Path) -> None:
    paths = _write_method_dataset_fixture(tmp_path)
    manifest = read_json(paths["method_manifest"])
    manifest["data_usage_boundary"]["promotion_allowed"] = True
    write_json(paths["method_manifest"], manifest)

    with pytest.raises(ValueError, match="promotion_allowed"):
        run_pool500_two_tower_diagnostic_loop(
            method_dataset_manifest_path=paths["method_manifest"],
            output_dir=tmp_path / "diagnostic_loop",
            overwrite=True,
            enforce_venv=False,
        )


def test_two_tower_diagnostic_loop_rejects_metric_k_larger_than_top_k(tmp_path: Path) -> None:
    paths = _write_method_dataset_fixture(tmp_path)

    with pytest.raises(ValueError, match="top_k"):
        run_pool500_two_tower_diagnostic_loop(
            method_dataset_manifest_path=paths["method_manifest"],
            output_dir=tmp_path / "diagnostic_loop",
            top_k=1,
            metric_ks=[2],
            overwrite=True,
            enforce_venv=False,
        )


@pytest.mark.parametrize("token", ["eval", "oracle", "label", "valid", "validation", "test", "holdout"])
def test_two_tower_diagnostic_loop_rejects_forbidden_method_dataset_manifest_path(tmp_path: Path, token: str) -> None:
    paths = _write_method_dataset_fixture(tmp_path / "safe")
    forbidden_dir = tmp_path / token / "method_dataset"
    forbidden_dir.mkdir(parents=True)
    forbidden_manifest = forbidden_dir / "method_dataset_manifest.json"
    forbidden_manifest.write_text(paths["method_manifest"].read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden method dataset input path"):
        run_pool500_two_tower_diagnostic_loop(
            method_dataset_manifest_path=forbidden_manifest,
            output_dir=tmp_path / "diagnostic_loop",
            overwrite=True,
            enforce_venv=False,
        )


@pytest.mark.parametrize("token", ["eval", "oracle", "label", "valid", "validation", "test", "holdout"])
def test_two_tower_diagnostic_loop_rejects_forbidden_train_input_output_paths(tmp_path: Path, token: str) -> None:
    paths = _write_method_dataset_fixture(tmp_path / "safe")
    forbidden_dir = tmp_path / "inputs" / token
    forbidden_dir.mkdir(parents=True)
    forbidden_samples = forbidden_dir / "two_tower_train_samples.jsonl"
    forbidden_samples.write_text(paths["train_samples"].read_text(encoding="utf-8"), encoding="utf-8")
    manifest = read_json(paths["method_manifest"])
    manifest["outputs"]["two_tower_train_samples"] = str(forbidden_samples)
    write_json(paths["method_manifest"], manifest)

    with pytest.raises(ValueError, match="forbidden method dataset input path"):
        run_pool500_two_tower_diagnostic_loop(
            method_dataset_manifest_path=paths["method_manifest"],
            output_dir=tmp_path / "diagnostic_loop",
            overwrite=True,
            enforce_venv=False,
        )


def test_two_tower_diagnostic_loop_rejects_eval_method_dataset_smoke_pattern(tmp_path: Path) -> None:
    paths = _write_method_dataset_fixture(tmp_path / "safe")
    forbidden_dir = tmp_path / "eval" / "method_dataset"
    forbidden_dir.mkdir(parents=True)
    forbidden_manifest = forbidden_dir / "method_dataset_manifest.json"
    forbidden_manifest.write_text(paths["method_manifest"].read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="method_dataset_manifest_path"):
        run_pool500_two_tower_diagnostic_loop(
            method_dataset_manifest_path=forbidden_manifest,
            output_dir=tmp_path / "diagnostic_loop",
            overwrite=True,
            enforce_venv=False,
        )


def test_two_tower_diagnostic_loop_rejects_forbidden_manifest_path_like_values(tmp_path: Path) -> None:
    paths = _write_method_dataset_fixture(tmp_path / "safe")
    manifest = read_json(paths["method_manifest"])
    manifest["diagnostic_inputs"] = {
        "source_index_manifest_path": str(tmp_path / "oracle" / "source_index_manifest.json"),
        "label_path": str(tmp_path / "labels" / "train_labels.jsonl"),
    }
    write_json(paths["method_manifest"], manifest)

    with pytest.raises(ValueError, match="manifest.diagnostic_inputs.source_index_manifest_path"):
        run_pool500_two_tower_diagnostic_loop(
            method_dataset_manifest_path=paths["method_manifest"],
            output_dir=tmp_path / "diagnostic_loop",
            overwrite=True,
            enforce_venv=False,
        )


def _write_method_dataset_fixture(tmp_path: Path) -> dict[str, Path]:
    dataset_dir = tmp_path / "method_dataset"
    dataset_dir.mkdir(parents=True)
    train_samples = dataset_dir / "two_tower_train_samples.jsonl"
    training_item_universe = dataset_dir / "training_item_universe.jsonl"
    method_manifest = dataset_dir / "method_dataset_manifest.json"
    write_jsonl(
        train_samples,
        [
            {"user_id": "u1", "history_items": ["item_a"], "target_item": "item_b", "positive_item_id": "item_b", "negative_item_ids": ["item_c"]},
            {"user_id": "u2", "history_items": ["item_c"], "target_item": "item_missing", "positive_item_id": "item_missing", "negative_item_ids": ["item_a"]},
        ],
    )
    write_jsonl(
        training_item_universe,
        [
            {"parent_asin": "item_a", "item_id": "item_a", "title_clean": "A"},
            {"parent_asin": "item_b", "item_id": "item_b", "title_clean": "B"},
            {"parent_asin": "item_c", "item_id": "item_c", "title_clean": "C"},
        ],
    )
    write_json(
        method_manifest,
        {
            "schema_version": "pool500_two_tower_method_dataset_v1",
            "dataset_role": "train_only_two_tower_method_dataset",
            "train_only": True,
            "diagnostic_only": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "final_pool500_ready_claimed": False,
            "data_usage_boundary": {
                "diagnostic_only": True,
                "candidate_generation_allowed": False,
                "ranking_input_replacement_allowed": False,
                "promotion_allowed": False,
                "final_pool500_ready_claimed": False,
                "label_artifacts": {"allowed_uses": ["diagnostic_eval_only"], "forbidden_uses": ["training", "index_build"]},
                "oracle_artifacts": {"allowed_uses": ["diagnostic_eval_only"], "forbidden_uses": ["training", "index_build"]},
            },
            "outputs": {
                "two_tower_train_samples": str(train_samples),
                "training_item_universe": str(training_item_universe),
            },
        },
    )
    return {"method_manifest": method_manifest, "train_samples": train_samples, "training_item_universe": training_item_universe}


def _patch_training(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_train_two_tower_recall(train_config_path: Path, *, output_dir: Path, limit_users: int, variant: str, item_vocab_manifest: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True)
        model_path = output_dir / "two_tower_model.json"
        item_embeddings_path = output_dir / "item_embeddings.jsonl"
        user_embeddings_path = output_dir / "user_embeddings.jsonl"
        recall_index_path = output_dir / "two_tower_recall_index.jsonl"
        train_metrics_path = output_dir / "train_metrics.json"
        artifact_manifest_path = output_dir / "artifact_manifest.json"
        rows = [
            {"item_id": "item_a", "parent_asin": "item_a", "embedding": [0.2, 0.0]},
            {"item_id": "item_b", "parent_asin": "item_b", "embedding": [1.0, 0.0]},
            {"item_id": "item_c", "parent_asin": "item_c", "embedding": [0.0, 1.0]},
        ]
        write_json(model_path, {"model_type": "youtube_dnn_two_tower_v1", "variant": variant, "source_name": "two_tower_youtube_dnn"})
        write_jsonl(item_embeddings_path, rows)
        write_jsonl(recall_index_path, rows)
        write_jsonl(user_embeddings_path, [{"user_id": "u1", "embedding": [1.0, 0.0]}, {"user_id": "u2", "embedding": [0.0, 1.0]}])
        write_json(train_metrics_path, {"variant": variant, "training_backend": {"name": "fixture"}, "training_input_users": limit_users, "users_with_training_rows": 2})
        write_json(
            artifact_manifest_path,
            {
                "artifact_type": "two_tower_training_artifacts_v1",
                "variant": variant,
                "source_name": "two_tower_youtube_dnn",
                "default_enabled": False,
                "contract": {
                    "train_config": str(train_config_path),
                    "model": str(model_path),
                    "item_embeddings": str(item_embeddings_path),
                    "user_embeddings": str(user_embeddings_path),
                    "train_metrics": str(train_metrics_path),
                    "recall_index": str(recall_index_path),
                    "artifact_manifest": str(artifact_manifest_path),
                },
            },
        )
        return {
            "artifact_manifest_path": artifact_manifest_path,
            "user_embeddings_path": user_embeddings_path,
            "item_embeddings_path": item_embeddings_path,
            "train_metrics_path": train_metrics_path,
            "metrics": {"training_input_users": limit_users, "users_with_training_rows": 2},
        }

    monkeypatch.setattr(diagnostic_module, "train_two_tower_recall", fake_train_two_tower_recall)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _assert_no_forbidden_artifact_paths(value: Any) -> None:
    for text in _walk_strings(value):
        normalized = text.replace("\\", "/").lower()
        if "/" not in normalized and not normalized.endswith((".json", ".jsonl")):
            continue
        parts = set(Path(normalized).parts)
        assert parts.isdisjoint(FORBIDDEN_ARTIFACT_TOKENS), text


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(str(key))
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)
