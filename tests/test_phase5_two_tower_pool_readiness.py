from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from scripts.experiments.recall.run_phase5_two_tower_pool_readiness import run_phase5_two_tower_pool_readiness


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    config_dir = tmp_path / "configs"
    baseline_dir = tmp_path / "lightweight_representative_e2e"
    phase0_dir = tmp_path / "phase0_contract_precheck"
    two_tower_config = config_dir / "two_tower_full_safe.json"
    ranking_config = config_dir / "pool200_full_safe.json"

    write_text(baseline_dir / "candidates.jsonl", '{"user_id": "u1", "item_id": "i1"}\n')
    write_json(
        two_tower_config,
        {
            "clean_dir": str(clean_dir),
            "views_dir": str(tmp_path / "amazon_2023_recall_views_full_lightweight"),
            "two_tower_enabled": True,
            "two_tower_variant": "youtube_dnn",
            "two_tower_artifact_path": "outputs/training/two_tower/artifact_manifest.json",
            "two_tower_seed_artifact_path": "outputs/training/two_tower/seed_neighbors.jsonl",
            "two_tower_seed_manifest_path": "outputs/training/two_tower/seed_manifest.json",
        },
    )
    write_json(ranking_config, {"export_frozen_candidates": True, "candidate_pool_size": 200})
    write_json(
        phase0_dir / "manifest.json",
        {
            "status": "PASS",
            "ranking_frozen_pool200_gate": {
                "config_file": str(ranking_config),
                "separate_from_recall_promotion_gate": True,
                "pool500_pool1000_cannot_replace_pool200": True,
            },
        },
    )
    write_json(
        phase0_dir / "resolved_inputs.json",
        {
            "full_clean_dir": {"path": str(clean_dir)},
            "phase5_two_tower_config_file": str(two_tower_config),
            "phase5_pool_readiness_inputs": {
                "frozen_pool200_candidate_source": {"path": str(baseline_dir / "candidates.jsonl")},
                "pool500_status": "READINESS_ONLY_NOT_RANKING_INPUT",
                "pool1000_status": "READINESS_ONLY_NOT_RANKING_INPUT",
                "ranking_gate": "Use ranking_frozen_pool200_gate, not recall_promotion_gate.",
            },
        },
    )
    return phase0_dir, tmp_path / "two_tower_pool_readiness"


def test_phase5_two_tower_pool_readiness_writes_feasibility_artifacts(tmp_path: Path) -> None:
    phase0_dir, output_dir = make_fixture(tmp_path)

    manifest = run_phase5_two_tower_pool_readiness(
        phase0_dir=phase0_dir,
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )

    source_audit = read_json(output_dir / "source_audit.json")
    metrics = read_json(output_dir / "metrics.json")
    two_tower = read_json(output_dir / "two_tower_feasibility.json")
    pool = read_json(output_dir / "pool_readiness.json")
    assert manifest["status"] == "EXECUTED_PASS_FEASIBILITY_ONLY"
    assert manifest["feasibility_only"] is True
    assert manifest["no_two_tower_training_executed"] is True
    assert manifest["required_artifacts"].keys() == {
        "manifest",
        "source_audit",
        "metrics",
        "two_tower_feasibility",
        "pool_readiness",
    }
    assert source_audit["train_only_candidate_generation"] is True
    assert source_audit["feasibility_only_no_candidate_generation"] is True
    assert source_audit["candidate_generation_uses_holdout"] is False
    assert source_audit["evaluation_only_read_files"] == []
    assert source_audit["no_10k_source"] is True
    assert source_audit["disabled_outputs"] == {
        "two_tower_training": True,
        "recall_promotion": True,
        "pool500_as_ranking_input": True,
        "pool1000_as_ranking_input": True,
    }
    candidate_read_names = [Path(path).name for path in source_audit["candidate_generation_read_files"]]
    assert "canonical_interactions.valid.jsonl" not in candidate_read_names
    assert "canonical_interactions.test.jsonl" not in candidate_read_names
    assert "holdout.jsonl" not in candidate_read_names
    assert metrics["no_two_tower_training_executed"] is True
    assert two_tower["training_default_action"] == "defer_until_explicit_gpu_training_approval"
    assert two_tower["training_executed"] is False
    assert pool["pool500_status"] == "READINESS_ONLY_NOT_RANKING_INPUT"
    assert pool["pool1000_status"] == "READINESS_ONLY_NOT_RANKING_INPUT"
    assert pool["pool500_pool1000_cannot_replace_pool200"] is True


def test_phase5_two_tower_pool_readiness_blocks_pool500_ranking_input(tmp_path: Path) -> None:
    phase0_dir, output_dir = make_fixture(tmp_path)
    resolved = read_json(phase0_dir / "resolved_inputs.json")
    resolved["phase5_pool_readiness_inputs"]["pool500_status"] = "RANKING_INPUT"
    write_json(phase0_dir / "resolved_inputs.json", resolved)

    manifest = run_phase5_two_tower_pool_readiness(
        phase0_dir=phase0_dir,
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )

    source_audit = read_json(output_dir / "source_audit.json")
    assert manifest["status"] == "blocked"
    assert manifest["failure_reason"] == "feasibility_or_readiness_contract_failed"
    assert source_audit["no_10k_source"] is True


def test_phase5_two_tower_pool_readiness_requires_phase0_pass(tmp_path: Path) -> None:
    phase0_dir, output_dir = make_fixture(tmp_path)
    write_json(phase0_dir / "manifest.json", {"status": "INVALID_SCOPE_DRIFT"})

    with pytest.raises(RuntimeError, match="Phase 0 must PASS"):
        run_phase5_two_tower_pool_readiness(
            phase0_dir=phase0_dir,
            output_dir=output_dir,
            min_free_bytes=0,
            enforce_venv=False,
        )
