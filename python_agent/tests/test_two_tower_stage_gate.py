from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.common.io import read_json, write_json
from rs_lab.experiments.recall.two_tower_stage_gate import build_two_tower_stage_gate_manifest, ensure_stage_not_blocked


def test_two_tower_stage_gate_1k_pass_manifest(tmp_path: Path):
    training_dir = tmp_path / "run_1k"
    training_dir.mkdir()
    metrics_path = tmp_path / "metrics.json"
    write_json(
        metrics_path,
        {
            "loss_history": [1.0, 0.8],
            "sample_count": 12,
            "variant": "youtube_dnn",
            "train_inputs_only": True,
            "eval_paths_rejected": True,
            "direct_artifact_load_blocked": True,
        },
    )

    output_path = tmp_path / "gate_1000.json"
    manifest = build_two_tower_stage_gate_manifest(
        stage="1k",
        training_run_dir=training_dir,
        metrics_manifest=metrics_path,
        output_path=output_path,
    )

    assert read_json(output_path) == manifest
    assert manifest["schema_version"] == "two_tower_stage_gate_v1"
    assert manifest["stage"] == "1k"
    assert manifest["status"] == "PASS"
    assert manifest["failure_reasons"] == []
    assert manifest["thresholds"]["variant"] == "youtube_dnn"


def test_two_tower_stage_gate_5k_stop_records_failure_reasons(tmp_path: Path):
    training_dir = tmp_path / "run_5k"
    training_dir.mkdir()
    metrics_path = tmp_path / "metrics.json"
    write_json(
        metrics_path,
        {
            "peak_cuda_memory_mb": 12000,
            "peak_rss_mb": 25000,
            "free_disk_gib_after_stage": 40,
            "training_seconds": 7200,
            "epochs": 1,
            "negative_sampling_seconds": 4000,
        },
    )

    manifest = build_two_tower_stage_gate_manifest(
        stage="5k",
        training_run_dir=training_dir,
        metrics_manifest=metrics_path,
        output_path=tmp_path / "gate_5000.json",
    )

    assert manifest["status"] == "STOP"
    assert "peak_cuda_memory_mb exceeds threshold" in manifest["failure_reasons"]
    assert "peak_rss_mb exceeds threshold" in manifest["failure_reasons"]
    assert "free_disk_gib_after_stage below threshold" in manifest["failure_reasons"]
    assert "training_seconds_per_epoch exceeds threshold" in manifest["failure_reasons"]
    assert "negative_sampling_ratio exceeds threshold" in manifest["failure_reasons"]


def test_two_tower_stage_gate_10k_pass_from_source_and_eval_manifests(tmp_path: Path):
    training_dir = tmp_path / "run_10k"
    training_dir.mkdir()
    source_manifest = tmp_path / "source_index_manifest.json"
    raw_eval_manifest = tmp_path / "raw_two_tower_eval_manifest.json"
    write_json(
        source_manifest,
        {
            "row_count": 100,
            "embedding_row_count": 100,
            "index_row_count": 100,
            "item_vocab_count": 100,
            "item_embeddings_bytes": 2 * 1024**3,
            "recall_index_bytes": 3 * 1024**3,
        },
    )
    write_json(
        raw_eval_manifest,
        {
            "candidate_generation_qps": 8,
            "underfilled_user_rate": 0.1,
            "single_generation_elapsed_seconds": 3600,
        },
    )

    manifest = build_two_tower_stage_gate_manifest(
        stage="10k",
        training_run_dir=training_dir,
        source_index_manifest=source_manifest,
        raw_eval_manifest=raw_eval_manifest,
        output_path=tmp_path / "gate_10000.json",
    )

    assert manifest["status"] == "PASS"
    assert manifest["failure_reasons"] == []
    assert manifest["metrics"]["embedding_index_size_gib"] == 5


def test_two_tower_stage_gate_10k_stop_on_row_count_and_eval_failures(tmp_path: Path):
    training_dir = tmp_path / "run_10k"
    training_dir.mkdir()
    source_manifest = tmp_path / "source_index_manifest.json"
    raw_eval_manifest = tmp_path / "raw_two_tower_eval_manifest.json"
    write_json(
        source_manifest,
        {
            "row_count": 100,
            "embedding_row_count": 99,
            "index_row_count": 100,
            "item_vocab_count": 100,
            "item_embeddings_bytes": 30 * 1024**3,
            "recall_index_bytes": 11 * 1024**3,
        },
    )
    write_json(
        raw_eval_manifest,
        {
            "candidate_generation_qps": 4,
            "underfilled_user_rate": 0.21,
            "single_generation_elapsed_seconds": 15000,
        },
    )

    manifest = build_two_tower_stage_gate_manifest(
        stage="10k",
        training_run_dir=training_dir,
        source_index_manifest=source_manifest,
        raw_eval_manifest=raw_eval_manifest,
        output_path=tmp_path / "gate_10000.json",
    )

    assert manifest["status"] == "STOP"
    assert "row counts must match item vocab, embedding, and index counts" in manifest["failure_reasons"]
    assert "candidate_generation_qps below threshold" in manifest["failure_reasons"]
    assert "underfilled_user_rate exceeds threshold" in manifest["failure_reasons"]
    assert "embedding_index_size_gib exceeds threshold" in manifest["failure_reasons"]
    assert "single_generation_elapsed_seconds exceeds threshold" in manifest["failure_reasons"]


def test_two_tower_stage_gate_20k_passes_non_degradation_and_unique_hits(tmp_path: Path):
    training_dir = tmp_path / "run_20k"
    training_dir.mkdir()
    ablation_manifest = tmp_path / "pool500_with_without_two_tower_ablation.json"
    write_json(
        ablation_manifest,
        {
            "without_two_tower": {"hit_at_500": 0.32},
            "with_two_tower": {"hit_at_500": 0.33},
            "raw_two_tower_unique_positive_hits": 3,
            "marginal_unique_positive_hits": 1,
        },
    )

    manifest = build_two_tower_stage_gate_manifest(
        stage="20k",
        training_run_dir=training_dir,
        ablation_manifest=ablation_manifest,
        output_path=tmp_path / "gate_20000.json",
    )

    assert manifest["status"] == "PASS"
    assert manifest["failure_reasons"] == []


def test_two_tower_stage_gate_10k_stop_prevents_20k(tmp_path: Path):
    gate_10k = tmp_path / "gate_10000.json"
    write_json(
        gate_10k,
        {
            "schema_version": "two_tower_stage_gate_v1",
            "stage": "10k",
            "status": "STOP",
            "failure_reasons": ["candidate_generation_qps below threshold"],
        },
    )

    with pytest.raises(RuntimeError, match="20k stage blocked by 10k STOP manifest"):
        ensure_stage_not_blocked(stage="20k", previous_gate_manifest=gate_10k)

    with pytest.raises(RuntimeError, match="20k stage blocked by 10k STOP manifest"):
        build_two_tower_stage_gate_manifest(
            stage="20k",
            training_run_dir=tmp_path / "run_20k",
            previous_gate_manifest=gate_10k,
            output_path=tmp_path / "gate_20000.json",
        )

    assert not (tmp_path / "gate_20000.json").exists()
