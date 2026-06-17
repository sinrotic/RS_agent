from __future__ import annotations

from typing import Any

from rs_core.training.config import load_training_config
from rs_core.training.data_contracts import synthetic_grpo_samples, validate_grpo_samples
from rs_core.training.qwen_loader import build_lora_config, check_training_imports, load_qwen_model_and_tokenizer
from rs_core.training.resource_gate import assess_qwen_resource_readiness
from rs_core.training.reward_adapter import compute_grpo_reward


def run_grpo(config_path: str, *, dry_run: bool = True, init_only: bool = False, max_steps: int | None = None) -> dict[str, Any]:
    config = load_training_config(config_path)
    if max_steps is not None:
        config.setdefault("grpo", {})["max_steps"] = max_steps
    samples = synthetic_grpo_samples()
    validate_grpo_samples(samples)
    rewards = [compute_grpo_reward(sample) for sample in samples]
    import_status = check_training_imports()
    readiness = assess_qwen_resource_readiness(config, workload="grpo", import_status=import_status)
    result: dict[str, Any] = {
        "mode": "grpo",
        "dry_run": dry_run,
        "sample_count": len(samples),
        "rewards": rewards,
        "imports": import_status,
        "resource_readiness": readiness.to_dict(),
        "heavy_path_entered": False,
    }
    if dry_run and not init_only and int(config.get("grpo", {}).get("max_steps", 0) or 0) <= 0:
        return result
    if not readiness.can_run_locally:
        raise RuntimeError(f"Local GRPO resource gate blocked heavy path: {readiness.blockers}")
    if not init_only and int(config.get("grpo", {}).get("max_steps", 0) or 0) <= 0:
        raise ValueError("GRPO heavy path requires --init-only or --max-steps > 0")

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

    from trl import GRPOTrainer

    result["trainer_class"] = GRPOTrainer.__name__
    return result
