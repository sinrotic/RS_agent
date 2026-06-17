from __future__ import annotations

import os
import platform
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rs_core.training.qwen_loader import check_training_imports

GIB = 1024 ** 3
DEFAULT_QWEN4B_PARAMETER_COUNT = 4_000_000_000
RESOURCE_GATE_SCHEMA_VERSION = "qwen_resource_gate_v1"


@dataclass(frozen=True)
class LocalResourceSnapshot:
    platform: str
    python_platform: str
    cpu_count: int
    total_ram_gib: float
    available_ram_gib: float | None = None
    disk_free_gib: float | None = None
    cuda_available: bool = False
    cuda_device_count: int = 0
    gpu_name: str = ""
    gpu_total_vram_gib: float | None = None
    gpu_free_vram_gib: float | None = None
    model_cache_present: bool = False
    model_cache_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkloadRequirement:
    workload: str
    min_ram_gib: float
    min_vram_gib: float
    recommended_vram_gib: float
    min_disk_free_gib: float
    requires_cuda: bool
    required_imports: list[str]
    requires_model_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceReadiness:
    schema_version: str
    workload: str
    status: str
    can_run_locally: bool
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    recommendations: list[str]
    hardware: dict[str, Any]
    requirements: dict[str, Any]
    imports: dict[str, Any]
    config_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess_qwen_resource_readiness(
    config: dict[str, Any],
    *,
    workload: str = "smoke",
    snapshot: LocalResourceSnapshot | None = None,
    import_status: dict[str, Any] | None = None,
) -> ResourceReadiness:
    """Assess whether the current machine should enter a Qwen heavy path.

    The gate is intentionally conservative: deterministic smoke checks may run with
    missing trainer dependencies, but model loading or training must have enough
    GPU/RAM/disk and the required imports before the runner enters the heavy path.
    """
    normalized_workload = _normalize_workload(workload)
    hardware = snapshot or collect_local_resource_snapshot(config)
    imports = import_status if import_status is not None else check_training_imports()
    requirement = build_workload_requirement(config, normalized_workload)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    _check_dependencies(requirement, imports, blockers, warnings)
    _check_hardware(requirement, hardware, blockers, warnings)
    _check_model_cache(requirement, hardware, blockers, warnings)

    status = "pass"
    if blockers:
        status = "block"
    elif warnings:
        status = "warn"
    return ResourceReadiness(
        schema_version=RESOURCE_GATE_SCHEMA_VERSION,
        workload=normalized_workload,
        status=status,
        can_run_locally=not blockers,
        blockers=blockers,
        warnings=warnings,
        recommendations=_recommendations(normalized_workload, blockers, warnings),
        hardware=hardware.to_dict(),
        requirements=requirement.to_dict(),
        imports=dict(imports),
        config_summary=_config_summary(config),
    )


def assert_qwen_resource_readiness(config: dict[str, Any], *, workload: str = "inference") -> ResourceReadiness:
    readiness = assess_qwen_resource_readiness(config, workload=workload)
    if not readiness.can_run_locally:
        reasons = "; ".join(str(blocker.get("reason")) for blocker in readiness.blockers)
        raise RuntimeError(f"Qwen {workload} resource gate blocked local heavy path: {reasons}")
    return readiness


def collect_local_resource_snapshot(config: dict[str, Any] | None = None) -> LocalResourceSnapshot:
    model_id = str((config or {}).get("model", {}).get("model_id") or "Qwen/Qwen3.5-4B") if isinstance((config or {}).get("model"), dict) else "Qwen/Qwen3.5-4B"
    ram = _memory_snapshot()
    cuda = _cuda_snapshot()
    usage = shutil.disk_usage(Path.cwd())
    cache_paths = _model_cache_paths(model_id)
    return LocalResourceSnapshot(
        platform=platform.system().lower(),
        python_platform=platform.platform(),
        cpu_count=os.cpu_count() or 1,
        total_ram_gib=round(ram.get("total", 0.0), 2),
        available_ram_gib=ram.get("available"),
        disk_free_gib=round(usage.free / GIB, 2),
        cuda_available=bool(cuda.get("cuda_available")),
        cuda_device_count=int(cuda.get("cuda_device_count") or 0),
        gpu_name=str(cuda.get("gpu_name") or ""),
        gpu_total_vram_gib=cuda.get("gpu_total_vram_gib"),
        gpu_free_vram_gib=cuda.get("gpu_free_vram_gib"),
        model_cache_present=bool(cache_paths),
        model_cache_paths=cache_paths,
    )


def build_workload_requirement(config: dict[str, Any], workload: str) -> WorkloadRequirement:
    normalized_workload = _normalize_workload(workload)
    model = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    quantization = config.get("quantization", {}) if isinstance(config.get("quantization"), dict) else {}
    model_id = str(model.get("model_id") or "Qwen/Qwen3.5-4B")
    parameter_count = _estimate_parameter_count(model_id)
    quantization_mode = str(quantization.get("mode") or "none").lower()
    inference_vram = _estimate_inference_vram_gib(parameter_count, quantization_mode)

    if normalized_workload == "smoke":
        return WorkloadRequirement(
            workload=normalized_workload,
            min_ram_gib=4.0,
            min_vram_gib=0.0,
            recommended_vram_gib=0.0,
            min_disk_free_gib=2.0,
            requires_cuda=False,
            required_imports=["torch"],
        )
    if normalized_workload == "inference":
        return WorkloadRequirement(
            workload=normalized_workload,
            min_ram_gib=8.0,
            min_vram_gib=max(8.0, inference_vram),
            recommended_vram_gib=max(12.0, inference_vram + 2.0),
            min_disk_free_gib=20.0,
            requires_cuda=True,
            required_imports=["torch", "transformers", "accelerate"],
            requires_model_cache=bool(model.get("local_files_only", True)),
        )
    if normalized_workload == "sft":
        return WorkloadRequirement(
            workload=normalized_workload,
            min_ram_gib=16.0,
            min_vram_gib=12.0,
            recommended_vram_gib=16.0,
            min_disk_free_gib=40.0,
            requires_cuda=True,
            required_imports=_training_required_imports(quantization_mode, include_trl=True),
            requires_model_cache=bool(model.get("local_files_only", True)),
        )
    return WorkloadRequirement(
        workload=normalized_workload,
        min_ram_gib=24.0,
        min_vram_gib=20.0,
        recommended_vram_gib=24.0,
        min_disk_free_gib=60.0,
        requires_cuda=True,
        required_imports=_training_required_imports(quantization_mode, include_trl=True),
        requires_model_cache=bool(model.get("local_files_only", True)),
    )


def _check_dependencies(
    requirement: WorkloadRequirement,
    imports: dict[str, Any],
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    missing_required = set(imports.get("missing_required", []))
    missing_optional = set(imports.get("missing_optional", []))
    missing = [name for name in requirement.required_imports if name in missing_required or name in missing_optional]
    if missing and requirement.workload != "smoke":
        blockers.append({"reason": "missing_required_imports", "imports": missing})
    elif missing:
        warnings.append({"reason": "smoke_missing_heavy_imports", "imports": missing})


def _check_hardware(
    requirement: WorkloadRequirement,
    hardware: LocalResourceSnapshot,
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    if hardware.total_ram_gib < requirement.min_ram_gib:
        blockers.append({"reason": "insufficient_ram", "available_gib": hardware.total_ram_gib, "required_gib": requirement.min_ram_gib})
    if hardware.disk_free_gib is not None and hardware.disk_free_gib < requirement.min_disk_free_gib:
        blockers.append({"reason": "insufficient_disk_free", "available_gib": hardware.disk_free_gib, "required_gib": requirement.min_disk_free_gib})
    if requirement.requires_cuda and not hardware.cuda_available:
        blockers.append({"reason": "cuda_unavailable"})
        return
    total_vram = hardware.gpu_total_vram_gib or 0.0
    free_vram = hardware.gpu_free_vram_gib if hardware.gpu_free_vram_gib is not None else total_vram
    if requirement.min_vram_gib and total_vram < requirement.min_vram_gib:
        blockers.append({"reason": "insufficient_total_vram", "available_gib": total_vram, "required_gib": requirement.min_vram_gib})
    if requirement.min_vram_gib and free_vram < requirement.min_vram_gib * 0.75:
        warnings.append({"reason": "low_free_vram", "free_gib": free_vram, "target_gib": requirement.min_vram_gib})
    if requirement.recommended_vram_gib and total_vram < requirement.recommended_vram_gib:
        warnings.append({"reason": "below_recommended_vram", "available_gib": total_vram, "recommended_gib": requirement.recommended_vram_gib})


def _check_model_cache(
    requirement: WorkloadRequirement,
    hardware: LocalResourceSnapshot,
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    if requirement.requires_model_cache and not hardware.model_cache_present:
        blockers.append({"reason": "local_model_cache_missing"})
    elif hardware.model_cache_present and requirement.workload == "smoke":
        warnings.append({"reason": "model_cache_present_but_not_loaded_in_smoke", "paths": hardware.model_cache_paths[:3]})


def _recommendations(workload: str, blockers: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[str]:
    reasons = {str(item.get("reason")) for item in [*blockers, *warnings]}
    recommendations: list[str] = []
    if not blockers and workload in {"smoke", "inference", "sft"}:
        recommendations.append("Local execution is acceptable for this workload; keep dry-run/init-only before full training.")
    if workload == "grpo" or {"insufficient_total_vram", "insufficient_ram", "missing_required_imports"} & reasons:
        recommendations.append("Prefer the remote server for full SFT/GRPO training, then pull back artifacts for local verification.")
    if "missing_required_imports" in reasons:
        recommendations.append("Install or validate training-only dependencies in an isolated environment before retrying heavy training.")
    if "below_recommended_vram" in reasons or "low_free_vram" in reasons:
        recommendations.append("Close GPU-heavy local processes or reduce batch size/sequence length; do not start a long run while VRAM is borderline.")
    if "local_model_cache_missing" in reasons:
        recommendations.append("Prepare the model cache explicitly; the scaffold will not auto-download model weights.")
    if not recommendations:
        recommendations.append("No resource blockers detected.")
    return recommendations


def _training_required_imports(quantization_mode: str, *, include_trl: bool) -> list[str]:
    imports = ["torch", "transformers", "accelerate", "datasets", "peft"]
    if include_trl:
        imports.append("trl")
    if quantization_mode in {"4bit_nf4", "8bit"}:
        imports.append("bitsandbytes")
    return imports


def _memory_snapshot() -> dict[str, float]:
    if platform.system().lower() == "windows":
        return _windows_memory_snapshot()
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = pages * page_size / GIB
        return {"total": round(total, 2), "available": None}
    except (AttributeError, ValueError, OSError):
        return {"total": 0.0, "available": None}


def _windows_memory_snapshot() -> dict[str, float]:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return {"total": round(status.ullTotalPhys / GIB, 2), "available": round(status.ullAvailPhys / GIB, 2)}
    except Exception:
        return {"total": 0.0, "available": None}


def _cuda_snapshot() -> dict[str, Any]:
    try:
        import torch
    except Exception:
        return {"cuda_available": False, "cuda_device_count": 0}
    if not torch.cuda.is_available():
        return {"cuda_available": False, "cuda_device_count": 0}
    device_index = 0
    props = torch.cuda.get_device_properties(device_index)
    free_vram = None
    try:
        free_bytes, _total_bytes = torch.cuda.mem_get_info(device_index)
        free_vram = round(free_bytes / GIB, 2)
    except Exception:
        pass
    return {
        "cuda_available": True,
        "cuda_device_count": torch.cuda.device_count(),
        "gpu_name": props.name,
        "gpu_total_vram_gib": round(props.total_memory / GIB, 2),
        "gpu_free_vram_gib": free_vram,
    }


def _model_cache_paths(model_id: str) -> list[str]:
    normalized = "models--" + model_id.replace("/", "--")
    roots = []
    for env_name in ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE"):
        value = os.getenv(env_name)
        if value:
            roots.append(Path(value))
    home = Path.home()
    user_profile = Path(os.getenv("USERPROFILE", str(home)))
    roots.extend([home / ".cache" / "huggingface", user_profile / ".cache" / "huggingface"])
    paths: list[str] = []
    seen: set[str] = set()
    for root in roots:
        candidates = [root / "hub" / normalized, root / normalized]
        for candidate in candidates:
            resolved = str(candidate)
            if resolved not in seen and candidate.exists():
                seen.add(resolved)
                paths.append(resolved)
    return paths


def _estimate_parameter_count(model_id: str) -> int:
    normalized = model_id.lower()
    if "4b" in normalized:
        return DEFAULT_QWEN4B_PARAMETER_COUNT
    if "7b" in normalized:
        return 7_000_000_000
    if "1.5b" in normalized or "1_5b" in normalized:
        return 1_500_000_000
    return DEFAULT_QWEN4B_PARAMETER_COUNT


def _estimate_inference_vram_gib(parameter_count: int, quantization_mode: str) -> float:
    bytes_per_param = 2.0
    if quantization_mode in {"4bit_nf4", "4bit"}:
        bytes_per_param = 0.75
    elif quantization_mode == "8bit":
        bytes_per_param = 1.1
    base = parameter_count * bytes_per_param / GIB
    return round(base + 2.0, 2)


def _config_summary(config: dict[str, Any]) -> dict[str, Any]:
    model = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    quantization = config.get("quantization", {}) if isinstance(config.get("quantization"), dict) else {}
    sft = config.get("sft", {}) if isinstance(config.get("sft"), dict) else {}
    grpo = config.get("grpo", {}) if isinstance(config.get("grpo"), dict) else {}
    return {
        "model_id": model.get("model_id"),
        "local_files_only": model.get("local_files_only"),
        "quantization_mode": quantization.get("mode"),
        "sft_max_steps": sft.get("max_steps"),
        "grpo_max_steps": grpo.get("max_steps"),
    }


def _normalize_workload(workload: str) -> str:
    normalized = str(workload or "smoke").strip().lower().replace("-", "_")
    if normalized in {"smoke", "inference", "sft", "grpo"}:
        return normalized
    raise ValueError("workload must be one of: smoke, inference, sft, grpo")
