from __future__ import annotations

from typing import Any

from rs_core.training.config import load_training_config
from rs_core.training.data_contracts import sft_messages_from_sample, synthetic_sft_samples, validate_sft_samples
from rs_core.training.qwen_loader import build_lora_config, check_training_imports, load_qwen_model_and_tokenizer


def run_sft(config_path: str, *, dry_run: bool = True, init_only: bool = False, max_steps: int | None = None) -> dict[str, Any]:
    config = load_training_config(config_path)
    if max_steps is not None:
        config.setdefault("sft", {})["max_steps"] = max_steps
    samples = synthetic_sft_samples()
    validate_sft_samples(samples)
    import_status = check_training_imports()
    result: dict[str, Any] = {
        "mode": "sft",
        "dry_run": dry_run,
        "sample_count": len(samples),
        "first_messages": sft_messages_from_sample(samples[0]),
        "imports": import_status,
        "heavy_path_entered": False,
    }
    if dry_run and not init_only and int(config.get("sft", {}).get("max_steps", 0) or 0) <= 0:
        return result
    if not import_status["ok"]:
        raise RuntimeError(f"Missing required training dependencies: {import_status['missing_required']}")
    if not init_only and int(config.get("sft", {}).get("max_steps", 0) or 0) <= 0:
        raise ValueError("SFT heavy path requires --init-only or --max-steps > 0")

    model, tokenizer = load_qwen_model_and_tokenizer(config)
    lora_config = build_lora_config(config)
    result.update({
        "heavy_path_entered": True,
        "model_type": type(model).__name__,
        "tokenizer_type": type(tokenizer).__name__,
        "lora_config_type": type(lora_config).__name__ if lora_config is not None else None,
    })
    if init_only:
        return result

    from trl import SFTTrainer

    result["trainer_class"] = SFTTrainer.__name__
    return result
