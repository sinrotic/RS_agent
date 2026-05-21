from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import read_json, write_json, write_jsonl
from rs_core.recsys.candidate_merge import load_two_tower_index
from rs_core.recsys.vector_index import VectorIndex
from rs_lab.experiments.recall.run_full_data_pool500_recall_only import _apply_source_generation_overrides
from rs_lab.experiments.recall.pool500.methods.two_tower.builder import build_two_tower_method_source

pytestmark = pytest.mark.unit

PYTHON = Path("D:/sinrotic_code/python_project/summer/RS_agent/.venv/Scripts/python.exe")

REQUIRED_OUTPUTS = {
    "method_dataset_manifest.json",
    "source_index_manifest.json",
    "candidates.jsonl",
    "coverage_audit.json",
    "undercoverage_audit.json",
    "resource_audit.json",
    "no_holdout_audit.json",
}
GATE_FIELDS = {
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "pool1000_allowed",
    "auto_promotion_allowed",
    "promotion_allowed",
    "final_pool500_ready_claimed",
}


def test_build_two_tower_method_source_writes_target_slice_diagnostic_contract(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)

    manifest = build_two_tower_method_source(
        artifact_manifest_path=paths["artifact_manifest"],
        clean_manifest_path=paths["clean_manifest"],
        output_root=tmp_path / "method_sources",
        run_id="unit",
        target_user_limit=4,
        batch_size=2,
        candidate_limit_per_user=3,
        seed_window=3,
        overwrite=True,
        enforce_venv=False,
    )

    output_dir = tmp_path / "method_sources" / "two_tower" / "unit"
    assert REQUIRED_OUTPUTS <= {path.name for path in output_dir.iterdir()}
    _assert_diagnostic_manifest_contract(manifest)
    assert "FULL_POOL500_READY" not in json.dumps(manifest, ensure_ascii=False)

    source_index = read_json(output_dir / "source_index_manifest.json")
    assert source_index["recall_index_path"] == str(paths["artifact_manifest"].resolve())
    assert source_index["artifact_manifest_path"] == str(paths["artifact_manifest"].resolve())
    assert source_index["candidate_path"] == str((output_dir / "candidates.jsonl").resolve())

    rows = _read_jsonl(output_dir / "candidates.jsonl")
    assert rows
    assert len({(row["user_id"], row["item_id"]) for row in rows}) == len(rows)
    assert {row["source"] for row in rows} == {"two_tower"}
    assert {row["canonical_source"] for row in rows} == {"two_tower"}
    assert all(row["score"] > 0.0 for row in rows)
    assert all(row["metadata"]["artifact_manifest_path"] == str(paths["artifact_manifest"].resolve()) for row in rows)
    assert all(row["metadata"].get("config_hash") for row in rows)
    assert all("seed_item_count" in row["metadata"] for row in rows)

    by_user = _rows_by_user(rows)
    assert [row["item_id"] for row in by_user["u_artifact"]] == ["item_b", "item_c", "item_d"]
    assert [row["rank"] for row in by_user["u_artifact"]] == [1, 2, 3]
    assert by_user["u_artifact"][0]["metadata"]["query_vector_source"] == "artifact_user_embedding"
    assert [row["item_id"] for row in by_user["u_seed_fallback"]] == ["item_c", "item_a", "item_d"]
    assert by_user["u_seed_fallback"][0]["metadata"]["query_vector_source"] == "seed_item_average"
    assert by_user["u_seed_fallback"][0]["metadata"]["seed_item_count"] == 1
    assert "u_missing_seed_vector" not in by_user
    assert "u_no_seed" not in by_user

    coverage = read_json(output_dir / "coverage_audit.json")
    undercoverage = read_json(output_dir / "undercoverage_audit.json")
    assert coverage["artifact_user_embedding_hit_count"] == 1
    assert coverage["seed_fallback_user_count"] == 1
    assert coverage["candidate_under_limit_user_count"] >= 1
    assert undercoverage["undercovered_user_count"] >= 2


def test_two_tower_method_source_blocks_forbidden_actual_reads_but_ignores_declared_eval_splits(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    clean_manifest = read_json(paths["clean_manifest"])
    clean_manifest["split_paths"] = {
        "train": str(paths["train_sequences"]),
        "valid": str(tmp_path / "unused_eval" / "valid.jsonl"),
        "test": str(tmp_path / "unused_eval" / "test.jsonl"),
    }
    write_json(paths["clean_manifest"], clean_manifest)

    manifest = build_two_tower_method_source(
        artifact_manifest_path=paths["artifact_manifest"],
        clean_manifest_path=paths["clean_manifest"],
        output_root=tmp_path / "method_sources",
        run_id="clean_manifest_eval_metadata",
        target_user_limit=2,
        batch_size=1,
        candidate_limit_per_user=2,
        overwrite=True,
        enforce_venv=False,
    )

    no_holdout = read_json(Path(manifest["outputs"]["no_holdout_audit"]))
    assert no_holdout["uses_holdout"] is False
    assert no_holdout["uses_valid"] is False
    assert no_holdout["uses_test"] is False
    assert no_holdout["ignored_evaluation_only_paths"] == [
        str((tmp_path / "unused_eval" / "valid.jsonl").resolve()),
        str((tmp_path / "unused_eval" / "test.jsonl").resolve()),
    ]

    forbidden_dir = tmp_path / "valid" / "clean"
    forbidden_dir.mkdir(parents=True)
    forbidden_train = forbidden_dir / "user_sequences.train.jsonl"
    write_jsonl(forbidden_train, [{"user_id": "u1", "recent_item_sequence": [], "recent_positive_item_sequence": []}])
    forbidden_manifest = forbidden_dir / "manifest.json"
    write_json(forbidden_manifest, {"train_user_sequences_path": str(forbidden_train)})

    with pytest.raises(ValueError, match="forbidden|holdout|valid|test"):
        build_two_tower_method_source(
            artifact_manifest_path=paths["artifact_manifest"],
            clean_manifest_path=forbidden_manifest,
            output_root=tmp_path / "method_sources",
            run_id="forbidden_actual_read",
            overwrite=True,
            enforce_venv=False,
        )


def test_two_tower_method_source_checkpoint_resume_and_overwrite_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _write_fixture(tmp_path)
    output_root = tmp_path / "method_sources"
    output_dir = output_root / "two_tower" / "resume"

    import rs_lab.experiments.recall.pool500.methods.two_tower.builder as builder_module

    original_write_batch = builder_module._write_candidate_batch
    calls = {"count": 0}

    def interrupt_once(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        result = original_write_batch(*args, **kwargs)
        if calls["count"] == 1:
            raise KeyboardInterrupt("simulated interrupted batch")
        return result

    monkeypatch.setattr(builder_module, "_write_candidate_batch", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        build_two_tower_method_source(
            artifact_manifest_path=paths["artifact_manifest"],
            clean_manifest_path=paths["clean_manifest"],
            output_root=output_root,
            run_id="resume",
            target_user_limit=4,
            batch_size=1,
            candidate_limit_per_user=3,
            overwrite=True,
            enforce_venv=False,
        )
    assert not (output_dir / "_FINALIZED.json").exists()
    assert not (output_dir / "method_dataset_manifest.json").exists()

    monkeypatch.setattr(builder_module, "_write_candidate_batch", original_write_batch)
    first_manifest = build_two_tower_method_source(
        artifact_manifest_path=paths["artifact_manifest"],
        clean_manifest_path=paths["clean_manifest"],
        output_root=output_root,
        run_id="resume",
        target_user_limit=4,
        batch_size=1,
        candidate_limit_per_user=3,
        resume=True,
        overwrite=False,
        enforce_venv=False,
    )
    assert (output_dir / "_FINALIZED.json").is_file()
    rows = _read_jsonl(output_dir / "candidates.jsonl")
    assert len(rows) == len({(row["user_id"], row["item_id"]) for row in rows})

    with pytest.raises(ValueError, match="config hash|resume"):
        build_two_tower_method_source(
            artifact_manifest_path=paths["artifact_manifest"],
            clean_manifest_path=paths["clean_manifest"],
            output_root=output_root,
            run_id="resume",
            target_user_limit=4,
            batch_size=1,
            candidate_limit_per_user=2,
            resume=True,
            overwrite=False,
            enforce_venv=False,
        )

    with pytest.raises(FileExistsError, match="already exists"):
        build_two_tower_method_source(
            artifact_manifest_path=paths["artifact_manifest"],
            clean_manifest_path=paths["clean_manifest"],
            output_root=output_root,
            run_id="resume",
            target_user_limit=4,
            batch_size=1,
            candidate_limit_per_user=3,
            resume=False,
            overwrite=False,
            enforce_venv=False,
        )
    assert read_json(output_dir / "method_dataset_manifest.json")["config_hash"] == first_manifest["config_hash"]


def test_two_tower_method_source_explicit_args_override_config_defaults(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    config_path = tmp_path / "source_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "schema_version: pool500_method_source_config_v1",
                "source: two_tower",
                f"output_root: {tmp_path / 'configured_outputs'}",
                "method_config:",
                f"  artifact_manifest_path: {paths['artifact_manifest']}",
                f"  clean_manifest_path: {paths['clean_manifest']}",
                "  target_user_limit: 4",
                "  batch_size: 2",
                "  per_user_candidate_limit: 3",
                "  seed_window: 3",
            ]
        ),
        encoding="utf-8",
    )

    manifest = build_two_tower_method_source(
        config_path=config_path,
        output_root=tmp_path / "explicit_outputs",
        run_id="explicit",
        target_user_limit=2,
        batch_size=1,
        per_user_candidate_limit=2,
        overwrite=True,
        enforce_venv=False,
    )

    assert manifest["output_dir"] == str((tmp_path / "explicit_outputs" / "two_tower" / "explicit").resolve())
    assert manifest["coverage_audit"]["target_user_count"] == 2
    assert manifest["coverage_audit"]["candidate_count_stats"]["max"] <= 2


def test_two_tower_method_source_cli_and_runner_compatibility(tmp_path: Path) -> None:
    paths = _write_fixture(tmp_path)
    output_root = tmp_path / "cli_outputs"
    result = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "rs_lab.experiments.recall.pool500.methods.two_tower.builder",
            "--artifact-manifest-path",
            str(paths["artifact_manifest"]),
            "--clean-manifest-path",
            str(paths["clean_manifest"]),
            "--output-root",
            str(output_root),
            "--run-id",
            "cli",
            "--target-user-limit",
            "3",
            "--batch-size",
            "2",
            "--candidate-limit-per-user",
            "2",
            "--seed-window",
            "3",
            "--overwrite",
            "--no-enforce-venv",
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd="D:/sinrotic_code/python_project/summer/RS_agent",
    )
    payload = json.loads(result.stdout)
    manifest_path = Path(payload["method_dataset_manifest"])
    manifest = read_json(manifest_path)
    source_index = read_json(manifest["outputs"]["source_index_manifest"])

    index = load_two_tower_index(source_index["recall_index_path"])
    assert isinstance(index, VectorIndex)
    config = {"two_tower_per_user": 20, "two_tower_seed_window": 10, "two_tower_query_batch_size": 25}
    _apply_source_generation_overrides(config, {"two_tower": {"manifest": source_index}})
    assert config["two_tower_per_user"] == 2
    assert config["two_tower_seed_window"] == 3
    assert config["two_tower_query_batch_size"] == 2


def _assert_diagnostic_manifest_contract(manifest: dict[str, Any]) -> None:
    assert manifest["source"] == "two_tower"
    assert manifest["canonical_source"] == "two_tower"
    assert manifest["source_status"] == "TARGET_SLICE_DIAGNOSTIC"
    assert manifest["diagnostic_only"] is True
    for field in GATE_FIELDS:
        assert manifest[field] is False


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    clean_dir = tmp_path / "clean"
    run_dir = tmp_path / "artifacts" / "two_tower" / "run_001"
    clean_dir.mkdir()
    run_dir.mkdir(parents=True)

    train_sequences = clean_dir / "user_sequences.train.jsonl"
    write_jsonl(
        train_sequences,
        [
            {"user_id": "u_artifact", "recent_item_sequence": ["item_a"], "recent_positive_item_sequence": ["item_a"]},
            {"user_id": "u_seed_fallback", "recent_item_sequence": ["item_b"], "recent_positive_item_sequence": ["item_b"]},
            {"user_id": "u_missing_seed_vector", "recent_item_sequence": ["missing_seed"], "recent_positive_item_sequence": ["missing_seed"]},
            {"user_id": "u_no_seed", "recent_item_sequence": [], "recent_positive_item_sequence": []},
        ],
    )
    clean_manifest = clean_dir / "manifest.json"
    write_json(clean_manifest, {"schema_version": "fixture_clean_v1", "train_user_sequences_path": str(train_sequences)})

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
        {"item_id": "item_a", "parent_asin": "item_a", "embedding": [1.0, 0.0], "main_category": "seed"},
        {"item_id": "item_b", "parent_asin": "item_b", "embedding": [0.8, 0.2], "main_category": "tie"},
        {"item_id": "item_c", "parent_asin": "item_c", "embedding": [0.8, 0.2], "main_category": "tie"},
        {"item_id": "item_d", "parent_asin": "item_d", "embedding": [0.2, 0.8], "main_category": "fallback"},
        {"item_id": "item_negative", "parent_asin": "item_negative", "embedding": [-1.0, 0.0], "main_category": "filtered"},
    ]
    write_jsonl(item_embeddings, rows)
    write_jsonl(recall_index, rows)
    write_jsonl(user_embeddings, [{"user_id": "u_artifact", "embedding": [1.0, 0.0]}])
    write_json(train_metrics, {"variant": "youtube_dnn", "training_backend": {"name": "fixture"}, "users_with_training_rows": 1})
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
        "clean_manifest": clean_manifest,
        "train_sequences": train_sequences,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rows_by_user(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["user_id"]), []).append(row)
    for user_rows in grouped.values():
        assert [row["rank"] for row in user_rows] == list(range(1, len(user_rows) + 1))
        assert user_rows == sorted(user_rows, key=lambda row: (row["rank"], row["item_id"]))
        assert user_rows == sorted(user_rows, key=lambda row: (-float(row["score"]), row["item_id"]))
    return grouped
