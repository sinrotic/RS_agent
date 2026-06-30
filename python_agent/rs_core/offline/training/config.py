from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config

TRAINING_DATA_DEFERRED = "deferred"
VALID_QUANTIZATION_MODES = {"4bit_nf4", "8bit", "none"}

DEFAULT_TRAINING_CONFIG: dict[str, Any] = {
    "experiment_name": "qwen_training_base",
    "stage": "environment_scaffold",
    "dry_run": True,
    "seed": 20260606,
    "model": {
        "model_id": "Qwen/Qwen3.5-4B",
        "local_files_only": True,
        "trust_remote_code": True,
        "torch_dtype": "auto",
        "device_map": "auto",
        "max_seq_length": 2048,
    },
    "quantization": {
        "mode": "4bit_nf4",
        "load_in_4bit": True,
        "load_in_8bit": False,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
        "bnb_4bit_compute_dtype": "bfloat16",
        "windows_bitsandbytes_optional": True,
    },
    "lora": {
        "enabled": True,
        "r": 16,
        "alpha": 32,
        "dropout": 0.05,
        "bias": "none",
        "task_type": "CAUSAL_LM",
        "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    },
    "data": {
        "status": TRAINING_DATA_DEFERRED,
        "source": "synthetic_smoke_only",
        "sft_path": None,
        "grpo_path": None,
        "rollout_schema": "rs_agent_rollout_v1",
        "training_signals_schema": "rs_agent_training_signals_v1",
    },
    "sft": {
        "enabled": True,
        "max_steps": 0,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 1,
        "learning_rate": 2e-4,
        "max_seq_length": 2048,
        "report_to": "none",
        "output_dir": "outputs/training/qwen_qlora_sft_smoke",
    },
    "grpo": {
        "enabled": True,
        "max_steps": 0,
        "per_device_train_batch_size": 1,
        "num_generations": 2,
        "learning_rate": 1e-6,
        "max_prompt_length": 1024,
        "max_completion_length": 256,
        "report_to": "none",
        "output_dir": "outputs/training/qwen_grpo_smoke",
    },
}


def load_training_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load a Qwen training config and merge it with safe smoke defaults."""
    config = deepcopy(DEFAULT_TRAINING_CONFIG)
    if path is not None:
        config = _merge_nested(config, load_config(path))
    if overrides:
        config = _merge_nested(config, overrides)
    _normalize_config(config)
    validate_training_config(config)
    return config


def validate_training_config(config: dict[str, Any]) -> None:
    errors: list[str] = []
    model = _as_dict(config.get("model"))
    data = _as_dict(config.get("data"))
    quantization = _as_dict(config.get("quantization"))
    lora = _as_dict(config.get("lora"))

    if not str(model.get("model_id", "")).strip():
        errors.append("model.model_id is required")
    if int(model.get("max_seq_length", 0) or 0) <= 0:
        errors.append("model.max_seq_length must be positive")

    data_status = str(data.get("status", "")).strip().lower()
    if data_status != TRAINING_DATA_DEFERRED:
        if not data.get("sft_path") and not data.get("grpo_path"):
            errors.append("non-deferred data requires data.sft_path or data.grpo_path")
    if data_status == TRAINING_DATA_DEFERRED and str(data.get("source", "")).strip() != "synthetic_smoke_only":
        errors.append("deferred data must keep data.source=synthetic_smoke_only")

    mode = str(quantization.get("mode", "")).strip().lower()
    if mode not in VALID_QUANTIZATION_MODES:
        errors.append(f"quantization.mode must be one of {sorted(VALID_QUANTIZATION_MODES)}, got {mode!r}")
    if mode == "4bit_nf4" and not bool(quantization.get("load_in_4bit")):
        errors.append("quantization.mode=4bit_nf4 requires load_in_4bit=true")
    if mode == "8bit" and not bool(quantization.get("load_in_8bit")):
        errors.append("quantization.mode=8bit requires load_in_8bit=true")

    if lora.get("enabled", True):
        if int(lora.get("r", 0) or 0) <= 0:
            errors.append("lora.r must be positive when LoRA is enabled")
        target_modules = lora.get("target_modules")
        if not isinstance(target_modules, list) or not all(str(value).strip() for value in target_modules):
            errors.append("lora.target_modules must be a non-empty list")

    for section_name in ["sft", "grpo"]:
        section = _as_dict(config.get(section_name))
        if int(section.get("per_device_train_batch_size", 0) or 0) <= 0:
            errors.append(f"{section_name}.per_device_train_batch_size must be positive")
        if int(section.get("max_steps", 0) or 0) < 0:
            errors.append(f"{section_name}.max_steps must be >= 0")

    if errors:
        raise ValueError("Invalid Qwen training config: " + "; ".join(errors))


def is_deferred_data_config(config: dict[str, Any]) -> bool:
    return str(_as_dict(config.get("data")).get("status", "")).strip().lower() == TRAINING_DATA_DEFERRED


def _normalize_config(config: dict[str, Any]) -> None:
    for section_name in ["sft", "grpo"]:
        section = _as_dict(config.get(section_name))
        if section.get("report_to") is None:
            section["report_to"] = "none"
    quantization = _as_dict(config.get("quantization"))
    quantization["mode"] = str(quantization.get("mode", "none")).strip().lower()


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
