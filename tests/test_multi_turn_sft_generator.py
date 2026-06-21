from __future__ import annotations

import json
from typing import Any

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.openai_compatible_client import OpenAICompatibleClient
from rs_core.training.multi_turn_sft_generator import (
    OpenAICompletionAdapter,
    RecommendationAgentComposer,
    run_multi_turn_sft_generation,
    validate_multi_turn_sft_sample,
)


def test_multi_turn_sft_dry_run_generates_scene_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_agent", raising=False)

    result = run_multi_turn_sft_generation("configs/training/multi_turn_sft_gpt53.yaml", limit=2)

    assert result["dry_run"] is True
    assert result["api_called"] is False
    assert result["generated_count"] == 2
    assert result["model"]["model"] == "gpt5.3codexspark"
    assert result["model"]["api_key_env"] == "RS_agent"
    assert result["quality_summary"]["min_dialogue_turn_count"] >= 2
    assert result["first_sample_preview"]["dialogue_turn_count"] >= 2


def test_validate_multi_turn_sft_rejects_unknown_selected_item() -> None:
    sample = {
        "schema_version": "rs_agent_multi_turn_sft_sample_v1",
        "sample_id": "sample-1",
        "dialogue": [
            {
                "turn_index": 1,
                "user_message": "show me audio",
                "assistant_message": "try item a",
                "display_item_ids": ["a"],
                "selected_item_ids": ["missing"],
                "target_action": {"allowed_item_ids": ["a"], "selected_item_ids": ["missing"], "must_select_from_candidates": True},
            },
            {
                "turn_index": 2,
                "user_message": "why?",
                "assistant_message": "because it matches",
                "display_item_ids": ["a"],
                "selected_item_ids": [],
                "target_action": {"allowed_item_ids": ["a"], "selected_item_ids": [], "must_select_from_candidates": True},
            },
        ],
        "grounding": {"forbidden_eval_fields_present": False},
    }

    with pytest.raises(ValueError, match="selected_item_ids"):
        validate_multi_turn_sft_sample(sample)


def test_multi_turn_sft_dry_run_override_prevents_writes(tmp_path) -> None:
    output_path = tmp_path / "samples.jsonl"
    flat_path = tmp_path / "flat.jsonl"
    manifest_path = tmp_path / "manifest.json"
    rejects_path = tmp_path / "rejects.jsonl"
    config_path = tmp_path / "config.yaml"
    output_value = output_path.as_posix()
    flat_value = flat_path.as_posix()
    manifest_value = manifest_path.as_posix()
    rejects_value = rejects_path.as_posix()
    config_path.write_text(
        f"""
generation:
  enabled: true
  dry_run: false
  target_samples: 1
  seed: 20260621
  service_config: configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml
  min_turns_per_scene: 2
  max_turns_per_scene: 2
  output_path: {output_value}
  flat_output_path: {flat_value}
  manifest_path: {manifest_value}
  rejects_path: {rejects_value}
model:
  api_base: https://cpa2api.sinrotic233.com
  api_key_env: RS_agent
  model: gpt5.3codexspark
""".strip(),
        encoding="utf-8",
    )

    result = run_multi_turn_sft_generation(config_path, limit=1, dry_run_override=True)

    assert result["dry_run"] is True
    assert not output_path.exists()
    assert not flat_path.exists()
    assert not manifest_path.exists()
    assert not rejects_path.exists()


def test_recommendation_composer_uses_openai_compatible_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        assert payload["model"] == "gpt5.3codexspark"
        return {
            "id": "chatcmpl-test",
            "model": payload["model"],
            "choices": [
                {
                    "message": {"role": "assistant", "content": json.dumps({"assistant_message": "这几件都来自当前展示商品。"}, ensure_ascii=False)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 9},
        }

    monkeypatch.setenv("RS_agent", "secret-test-key")
    adapter = OpenAICompletionAdapter(
        client=OpenAICompatibleClient(base_url="https://cpa2api.sinrotic233.com", api_key_env="RS_agent", transport=fake_transport),
        model="gpt5.3codexspark",
        response_format={"type": "json_object"},
    )
    composer = RecommendationAgentComposer(adapter)

    message, metadata = composer.compose(
        persona={"shopping_goal": "audio"},
        user_message="show me audio",
        display={"assistant_message": "Here are items.", "items": [{"parent_asin": "a", "title": "A"}]},
        history=[],
    )

    assert message == "这几件都来自当前展示商品。"
    assert metadata["api_called"] is True
    assert metadata["response"]["usage"] == {"total_tokens": 9}
    assert "secret-test-key" not in str(metadata)
