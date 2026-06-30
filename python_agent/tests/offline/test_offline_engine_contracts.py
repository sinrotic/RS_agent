from __future__ import annotations

import json
import subprocess
import sys

import pytest

from rs_core.offline.engine import OfflineModelEngine

pytestmark = pytest.mark.unit


def test_offline_deferred_facades_expose_freeze_contracts() -> None:
    from rs_core.offline.evaluation import OFFLINE_DEFERRED_CONTRACT as evaluation_contract
    from rs_core.offline.simulation import OFFLINE_DEFERRED_CONTRACT as simulation_contract
    from rs_core.offline.training import OFFLINE_DEFERRED_CONTRACT as training_contract

    assert training_contract == {
        "owner": "rs_core.offline.training",
        "legacy_import": None,
        "migration_status": "implemented",
        "allowed_execution_modes": ("dry_run", "smoke"),
        "forbidden_actions": ("full_train", "refresh_artifact"),
    }
    assert evaluation_contract == {
        "owner": "rs_core.offline.evaluation",
        "legacy_import": None,
        "migration_status": "implemented",
        "allowed_execution_modes": ("smoke",),
        "forbidden_actions": ("full_eval", "refresh_artifact"),
    }
    assert simulation_contract == {
        "owner": "rs_core.offline.simulation",
        "legacy_import": None,
        "migration_status": "implemented",
        "allowed_execution_modes": ("smoke",),
        "forbidden_actions": ("full_simulation", "refresh_artifact"),
    }



def test_offline_engine_training_job_is_dry_run_by_default() -> None:
    engine = OfflineModelEngine()

    job = engine.start_training_job("train-smoke", config_path="configs/train.yaml", model_family="DeepFM")

    assert job["job_id"] == "train-smoke"
    assert job["status"] == "dry_run_ready"
    assert job["execution_mode"] == "dry_run"
    assert job["metadata"] == {"no_training_started": True}
    assert job["resource_estimate"]["heavy_job"] is False
    assert job["resource_estimate"]["recommendation"] == "local_smoke"


def test_offline_engine_blocks_heavy_training_contract_without_running_it() -> None:
    engine = OfflineModelEngine()

    job = engine.start_training_job(
        "train-heavy",
        model_family="qwen",
        execution_mode="full_train",
        estimated_memory_gb=16.0,
    )

    assert job["status"] == "blocked_heavy_job"
    assert job["metadata"]["no_training_started"] is True
    assert job["resource_estimate"]["heavy_job"] is True
    assert job["resource_estimate"]["recommendation"] == "remote_or_limited_smoke"


def test_offline_engine_evaluation_and_artifact_contracts_are_public_safe() -> None:
    engine = OfflineModelEngine()

    artifact = engine.register_model_artifact(
        "deepfm-smoke",
        "models/deepfm.json",
        model_family="DeepFM",
        metrics_ref="metrics/deepfm.json",
    )
    result = engine.run_evaluation_smoke(
        eval_id="eval-smoke",
        dataset_ref="datasets/eval.jsonl",
        model_artifact_id="deepfm-smoke",
    )

    assert artifact["model_family"] == "DeepFM"
    assert artifact["metrics_ref"] == "metrics/deepfm.json"
    assert artifact["metadata"] == {"registered_by": "OfflineModelEngine"}
    assert result["status"] == "ok"
    assert result["report"]["metrics"] == {"smoke_passed": 1.0}
    assert result["report"]["metadata"] == {"public_safe": True, "no_full_eval": True}
    assert result["job"]["dataset_ref"] == "datasets/eval.jsonl"
    assert result["job"]["metadata"] == {"no_full_eval": True}
    rendered = json.dumps(result)
    for forbidden in ["oracle", "holdout", "label_binary", "training_samples"]:
        assert forbidden not in rendered


def test_offline_engine_experiment_and_simulation_smoke_contracts() -> None:
    engine = OfflineModelEngine()

    experiment = engine.experiment_smoke("experiment-smoke")
    simulation = engine.simulation_smoke("simulation-smoke", sample_count=2)

    assert experiment["route"] == "offline"
    assert experiment["status"] == "smoke_planned"
    assert experiment["metadata"] == {"no_full_run": True}
    assert simulation["sample_count"] == 2
    assert simulation["metrics"] == {"smoke_passed": 1.0}
    assert simulation["metadata"] == {"offline_only": True, "public_serving_excluded": True}


def test_offline_worker_module_execution_is_lightweight() -> None:
    command = [
        sys.executable,
        "-m",
        "rs_core.offline.runtime.worker",
        "resource-estimate",
        "training",
        "--estimated-memory-gb",
        "16",
        "--heavy-job",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)

    payload = json.loads(result.stdout)

    assert payload["job_type"] == "training"
    assert payload["heavy_job"] is True
    assert payload["recommendation"] == "remote_or_limited_smoke"
    assert "RuntimeWarning" not in result.stderr
