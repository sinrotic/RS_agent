from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

from rs_core.training.config import is_deferred_data_config, load_training_config, validate_training_config


def test_load_training_config_merges_safe_defaults() -> None:
    config = load_training_config("configs/training/qwen_qlora_sft_smoke.yaml")

    assert config["experiment_name"] == "qwen_qlora_sft_smoke"
    assert config["dry_run"] is True
    assert config["model"]["model_id"] == "Qwen/Qwen3.5-4B"
    assert config["quantization"]["mode"] == "4bit_nf4"
    assert config["sft"]["max_steps"] == 0
    assert is_deferred_data_config(config) is True


def test_training_config_rejects_invalid_quantization() -> None:
    config = load_training_config(overrides={"quantization": {"mode": "none"}})
    config["quantization"]["mode"] = "bad_mode"

    with pytest.raises(ValueError, match="quantization.mode"):
        validate_training_config(config)


def test_training_config_allows_non_deferred_data_with_path(tmp_path: Path) -> None:
    data_path = tmp_path / "sft.jsonl"
    data_path.write_text("{}\n", encoding="utf-8")

    config = load_training_config(
        overrides={
            "data": {"status": "ready", "source": "local_jsonl", "sft_path": str(data_path)},
            "quantization": {"mode": "none", "load_in_4bit": False},
        }
    )

    assert is_deferred_data_config(config) is False
    assert config["data"]["sft_path"] == str(data_path)
