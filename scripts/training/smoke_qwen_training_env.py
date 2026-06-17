from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.training.config import load_training_config
from rs_core.training.data_contracts import synthetic_grpo_samples, synthetic_sft_samples, validate_grpo_samples, validate_sft_samples
from rs_core.training.qwen_loader import check_training_imports, load_qwen_model_and_tokenizer
from rs_core.training.resource_gate import assess_qwen_resource_readiness
from rs_core.training.reward_adapter import compute_grpo_reward


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check the Qwen training scaffold without loading Qwen by default.")
    parser.add_argument("--config", default="configs/training/qwen_training_base.yaml")
    parser.add_argument("--check-model-load", action="store_true", help="Explicitly load Qwen model/tokenizer and report their classes.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_training_config(args.config)
    sft_samples = synthetic_sft_samples()
    grpo_samples = synthetic_grpo_samples()
    validate_sft_samples(sft_samples)
    validate_grpo_samples(grpo_samples)
    import_status = check_training_imports()
    smoke_readiness = assess_qwen_resource_readiness(config, workload="smoke", import_status=import_status)
    inference_readiness = assess_qwen_resource_readiness(config, workload="inference", import_status=import_status)
    sft_readiness = assess_qwen_resource_readiness(config, workload="sft", import_status=import_status)
    grpo_readiness = assess_qwen_resource_readiness(config, workload="grpo", import_status=import_status)
    result = {
        "ok": True,
        "config": config["experiment_name"],
        "dry_run": config["dry_run"],
        "sft_sample_count": len(sft_samples),
        "grpo_sample_count": len(grpo_samples),
        "grpo_rewards": [compute_grpo_reward(sample) for sample in grpo_samples],
        "imports": import_status,
        "resource_readiness": {
            "smoke": smoke_readiness.to_dict(),
            "inference": inference_readiness.to_dict(),
            "sft": sft_readiness.to_dict(),
            "grpo": grpo_readiness.to_dict(),
        },
        "model_load_checked": False,
    }
    if args.check_model_load:
        if not inference_readiness.can_run_locally:
            raise RuntimeError(f"Local Qwen inference is not ready: {inference_readiness.blockers}")
        model, tokenizer = load_qwen_model_and_tokenizer(config)
        result.update({
            "model_load_checked": True,
            "model_type": type(model).__name__,
            "tokenizer_type": type(tokenizer).__name__,
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
