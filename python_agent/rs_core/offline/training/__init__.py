from __future__ import annotations

OFFLINE_DEFERRED_CONTRACT = {
    "owner": "rs_core.offline.training",
    "legacy_import": None,
    "migration_status": "implemented",
    "allowed_execution_modes": ("dry_run", "smoke"),
    "forbidden_actions": ("full_train", "refresh_artifact"),
}

from rs_core.offline.training.config import load_training_config, validate_training_config
from rs_core.offline.training.data_contracts import synthetic_grpo_samples, synthetic_sft_samples
from rs_core.offline.training.reward_adapter import compute_grpo_reward, grpo_reward_function

__all__ = [
    "OFFLINE_DEFERRED_CONTRACT",
    "compute_grpo_reward",
    "grpo_reward_function",
    "load_training_config",
    "synthetic_grpo_samples",
    "synthetic_sft_samples",
    "validate_training_config",
]
