from __future__ import annotations

import pytest

from rs_core.offline.training.config import load_training_config
from rs_core.offline.training.resource_gate import (
    LocalResourceSnapshot,
    assess_qwen_resource_readiness,
    build_workload_requirement,
)

pytestmark = pytest.mark.unit


def test_resource_gate_allows_smoke_without_trainer_dependencies() -> None:
    config = load_training_config()
    snapshot = _snapshot(total_ram_gib=8.0, disk_free_gib=4.0, cuda_available=False)
    import_status = {
        "ok": False,
        "missing_required": ["peft", "trl"],
        "missing_optional": ["bitsandbytes"],
        "warnings": ["bitsandbytes is optional on Windows smoke checks"],
    }

    readiness = assess_qwen_resource_readiness(config, workload="smoke", snapshot=snapshot, import_status=import_status)

    assert readiness.can_run_locally is True
    assert readiness.status in {"pass", "warn"}
    assert readiness.blockers == []
    assert readiness.requirements["requires_cuda"] is False


def test_resource_gate_blocks_sft_when_required_training_imports_are_missing() -> None:
    config = load_training_config()
    snapshot = _snapshot(total_ram_gib=32.0, disk_free_gib=100.0, cuda_available=True, vram_gib=16.0)
    import_status = {
        "ok": False,
        "missing_required": ["peft", "trl"],
        "missing_optional": ["bitsandbytes"],
        "warnings": [],
    }

    readiness = assess_qwen_resource_readiness(config, workload="sft", snapshot=snapshot, import_status=import_status)

    assert readiness.can_run_locally is False
    assert readiness.status == "block"
    assert readiness.blockers[0]["reason"] == "missing_required_imports"
    assert set(readiness.blockers[0]["imports"]) == {"peft", "trl", "bitsandbytes"}
    assert any("remote server" in recommendation for recommendation in readiness.recommendations)


def test_resource_gate_blocks_grpo_on_local_16gb_vram_even_with_imports() -> None:
    config = load_training_config()
    snapshot = _snapshot(total_ram_gib=32.0, disk_free_gib=100.0, cuda_available=True, vram_gib=16.0)
    import_status = {"ok": True, "missing_required": [], "missing_optional": [], "warnings": []}

    readiness = assess_qwen_resource_readiness(config, workload="grpo", snapshot=snapshot, import_status=import_status)

    assert readiness.can_run_locally is False
    assert any(blocker["reason"] == "insufficient_total_vram" for blocker in readiness.blockers)
    assert readiness.requirements["recommended_vram_gib"] == 24.0


def test_resource_gate_marks_qwen_inference_ready_with_cached_model_and_16gb_vram() -> None:
    config = load_training_config()
    snapshot = _snapshot(
        total_ram_gib=32.0,
        disk_free_gib=100.0,
        cuda_available=True,
        vram_gib=16.0,
        model_cache_present=True,
    )
    import_status = {"ok": True, "missing_required": [], "missing_optional": [], "warnings": []}

    readiness = assess_qwen_resource_readiness(config, workload="inference", snapshot=snapshot, import_status=import_status)

    assert readiness.can_run_locally is True
    assert readiness.blockers == []
    assert readiness.hardware["model_cache_present"] is True


def test_build_workload_requirement_rejects_unknown_workload() -> None:
    config = load_training_config()

    with pytest.raises(ValueError, match="workload must be one of"):
        build_workload_requirement(config, "full_train")


def _snapshot(
    *,
    total_ram_gib: float,
    disk_free_gib: float,
    cuda_available: bool,
    vram_gib: float = 0.0,
    model_cache_present: bool = True,
) -> LocalResourceSnapshot:
    return LocalResourceSnapshot(
        platform="windows",
        python_platform="Windows-11",
        cpu_count=12,
        total_ram_gib=total_ram_gib,
        available_ram_gib=total_ram_gib / 2,
        disk_free_gib=disk_free_gib,
        cuda_available=cuda_available,
        cuda_device_count=1 if cuda_available else 0,
        gpu_name="NVIDIA GeForce RTX 4070 Ti SUPER" if cuda_available else "",
        gpu_total_vram_gib=vram_gib if cuda_available else None,
        gpu_free_vram_gib=vram_gib if cuda_available else None,
        model_cache_present=model_cache_present,
        model_cache_paths=["C:/Users/luo/.cache/huggingface/hub/models--Qwen--Qwen3.5-4B"] if model_cache_present else [],
    )
