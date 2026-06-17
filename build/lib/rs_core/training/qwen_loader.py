from __future__ import annotations

import importlib.util
import platform
from typing import Any

REQUIRED_TRAINING_IMPORTS = ["torch", "transformers", "accelerate", "datasets", "peft", "trl"]
OPTIONAL_TRAINING_IMPORTS = ["bitsandbytes"]


def check_training_imports() -> dict[str, Any]:
    """Check import availability without importing or downloading model weights."""
    missing_required = [name for name in REQUIRED_TRAINING_IMPORTS if importlib.util.find_spec(name) is None]
    missing_optional = [name for name in OPTIONAL_TRAINING_IMPORTS if importlib.util.find_spec(name) is None]
    warnings: list[str] = []
    if "bitsandbytes" in missing_optional and platform.system().lower() == "windows":
        warnings.append("bitsandbytes is optional on Windows smoke checks")
    return {
        "ok": not missing_required,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "warnings": warnings,
    }


def build_quantization_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    quantization_config = build_quantization_config(config)
    return {"quantization_config": quantization_config} if quantization_config is not None else {}


def build_quantization_config(config: dict[str, Any]) -> Any | None:
    """Build a Transformers BitsAndBytesConfig only on explicit heavy paths."""
    quantization = config.get("quantization", {}) if isinstance(config.get("quantization"), dict) else {}
    mode = str(quantization.get("mode", "none")).lower()
    if mode == "none":
        return None

    from transformers import BitsAndBytesConfig

    if mode == "8bit":
        return BitsAndBytesConfig(load_in_8bit=True)
    if mode == "4bit_nf4":
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=quantization.get("bnb_4bit_quant_type", "nf4"),
            bnb_4bit_use_double_quant=bool(quantization.get("bnb_4bit_use_double_quant", True)),
            bnb_4bit_compute_dtype=_torch_dtype(quantization.get("bnb_4bit_compute_dtype", "bfloat16")),
        )
    raise ValueError(f"Unsupported quantization mode: {mode}")


def build_lora_config(config: dict[str, Any]) -> Any | None:
    """Build a PEFT LoraConfig for explicit trainer initialization."""
    lora = config.get("lora", {}) if isinstance(config.get("lora"), dict) else {}
    if not bool(lora.get("enabled", True)):
        return None

    from peft import LoraConfig

    return LoraConfig(
        r=int(lora.get("r", 16)),
        lora_alpha=int(lora.get("alpha", 32)),
        lora_dropout=float(lora.get("dropout", 0.05)),
        bias=str(lora.get("bias", "none")),
        task_type=str(lora.get("task_type", "CAUSAL_LM")),
        target_modules=[str(module) for module in lora.get("target_modules", [])],
    )


def load_qwen_model_and_tokenizer(config: dict[str, Any]) -> tuple[Any, Any]:
    """Load Qwen only for explicit heavy-path invocations."""
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_config = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    model_id = model_config["model_id"]
    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        trust_remote_code=bool(model_config.get("trust_remote_code", True)),
        local_files_only=bool(model_config.get("local_files_only", True)),
    )
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        trust_remote_code=bool(model_config.get("trust_remote_code", True)),
        local_files_only=bool(model_config.get("local_files_only", True)),
        device_map=model_config.get("device_map", "auto"),
        torch_dtype=_torch_dtype(model_config.get("torch_dtype", "auto")),
        **build_quantization_kwargs(config),
    )
    return model, tokenizer


def _torch_dtype(value: Any) -> Any:
    if value in (None, "", "auto"):
        return "auto"
    import torch

    if isinstance(value, str) and hasattr(torch, value):
        return getattr(torch, value)
    return value
