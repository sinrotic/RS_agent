from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from scripts.experiments.recall.run_phase4_graph_mf_contract_validation import run_phase4_graph_mf_contract_validation


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    clean_dir = tmp_path / "amazon_2023_recall_clean_full"
    graph_config = tmp_path / "configs" / "graph_full_safe.json"
    mf_config = tmp_path / "configs" / "mf.yaml"
    phase0_dir = tmp_path / "phase0_contract_precheck"

    for name in ["user_sequences.train.jsonl", "canonical_interactions.train.jsonl", "canonical_items.jsonl"]:
        write_text(clean_dir / name, '{"ok": true}\n')
    write_json(
        graph_config,
        {
            "strategy_name": "phase_1_19_graph_walk_seed_deepwalk",
            "clean_dir": str(clean_dir),
            "views_dir": str(tmp_path / "amazon_2023_recall_views_full_lightweight"),
            "graph_walk_seed_enabled": False,
        },
    )
    write_text(
        mf_config,
        "implicit_svd_enabled: true\nals_mf_enabled: true\nbpr_mf_enabled: true\nlightfm_enabled: true\n",
    )
    write_json(phase0_dir / "manifest.json", {"status": "PASS"})
    write_json(
        phase0_dir / "resolved_inputs.json",
        {
            "full_clean_dir": {"path": str(clean_dir)},
            "phase4_graph_config_file": str(graph_config),
            "phase3_swing_inputs": {
                "inputs": [
                    {"path": str(clean_dir / "user_sequences.train.jsonl")},
                    {"path": str(clean_dir / "canonical_interactions.train.jsonl")},
                ]
            },
            "phase4_mf_inputs": {
                "inputs": [
                    {"path": str(clean_dir / "canonical_interactions.train.jsonl")},
                    {"path": str(clean_dir / "canonical_items.jsonl")},
                ]
            },
        },
    )
    return phase0_dir, mf_config, tmp_path / "graph_mf_contract_validation"


def test_phase4_graph_mf_contract_validation_writes_contract_artifacts(tmp_path: Path) -> None:
    phase0_dir, mf_config, output_dir = make_fixture(tmp_path)

    manifest = run_phase4_graph_mf_contract_validation(
        phase0_dir=phase0_dir,
        mf_config=mf_config,
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )

    source_audit = read_json(output_dir / "source_audit.json")
    metrics = read_json(output_dir / "metrics.json")
    graph_contract = read_json(output_dir / "graph_contract_validation.json")
    mf_contract = read_json(output_dir / "mf_contract_validation.json")
    assert manifest["status"] == "EXECUTED_PASS_CONTRACT_ONLY"
    assert manifest["contract_only"] is True
    assert manifest["no_model_training_executed"] is True
    assert manifest["required_artifacts"].keys() == {
        "manifest",
        "source_audit",
        "metrics",
        "graph_contract_validation",
        "mf_contract_validation",
    }
    assert source_audit["train_only_candidate_generation"] is True
    assert source_audit["contract_only_no_candidate_generation"] is True
    assert source_audit["candidate_generation_uses_holdout"] is False
    assert source_audit["no_10k_source"] is True
    candidate_read_names = [Path(path).name for path in source_audit["candidate_generation_read_files"]]
    assert "canonical_interactions.valid.jsonl" not in candidate_read_names
    assert "canonical_interactions.test.jsonl" not in candidate_read_names
    assert "holdout.jsonl" not in candidate_read_names
    assert source_audit["evaluation_only_read_files"] == []
    assert source_audit["disabled_outputs"] == {
        "graph_walk_training": True,
        "mf_training": True,
        "pool500": True,
        "pool1000": True,
        "ranking_default_input": True,
    }
    assert metrics["contract_only"] is True
    assert metrics["no_model_training_executed"] is True
    assert graph_contract["training_disabled"] is True
    assert graph_contract["ranking_default_input_disabled"] is True
    assert set(mf_contract["enabled_methods"]) == {"implicit_svd", "als_mf", "bpr_mf", "lightfm"}


def test_phase4_graph_mf_contract_validation_blocks_10k_config_reference(tmp_path: Path) -> None:
    phase0_dir, mf_config, output_dir = make_fixture(tmp_path)
    resolved = read_json(phase0_dir / "resolved_inputs.json")
    bad_graph_config = tmp_path / "configs" / "bad_graph.json"
    write_json(bad_graph_config, {"clean_dir": "data/processed/amazon_2023_recall_clean_10000"})
    resolved["phase4_graph_config_file"] = str(bad_graph_config)
    write_json(phase0_dir / "resolved_inputs.json", resolved)

    manifest = run_phase4_graph_mf_contract_validation(
        phase0_dir=phase0_dir,
        mf_config=mf_config,
        output_dir=output_dir,
        min_free_bytes=0,
        enforce_venv=False,
    )

    source_audit = read_json(output_dir / "source_audit.json")
    assert manifest["status"] == "blocked"
    assert manifest["failure_reason"] == "contract_validation_failed"
    assert source_audit["no_10k_source"] is False


def test_phase4_graph_mf_contract_validation_requires_phase0_pass(tmp_path: Path) -> None:
    phase0_dir, mf_config, output_dir = make_fixture(tmp_path)
    write_json(phase0_dir / "manifest.json", {"status": "INVALID_SCOPE_DRIFT"})

    with pytest.raises(RuntimeError, match="Phase 0 must PASS"):
        run_phase4_graph_mf_contract_validation(
            phase0_dir=phase0_dir,
            mf_config=mf_config,
            output_dir=output_dir,
            min_free_bytes=0,
            enforce_venv=False,
        )
