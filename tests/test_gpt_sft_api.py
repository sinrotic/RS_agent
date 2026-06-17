from __future__ import annotations

import json
from typing import Any

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.openai_compatible_client import OpenAICompatibleClient
from rs_core.common.io import read_jsonl, write_json
from rs_core.training.data_contracts import synthetic_sft_samples, validate_sft_sample, validate_sft_samples
from rs_core.training.gpt_sft_config import load_gpt_sft_config
from rs_core.training.gpt_sft_generator import build_gpt_sft_messages, extract_first_json_object, generate_gpt_sft_sample
from rs_core.training.gpt_sft_runner import GptSftExecutionDisabledError, run_gpt_sft


def test_load_gpt_sft_config_uses_safe_defaults() -> None:
    config = load_gpt_sft_config("configs/training/gpt_sft_api_smoke.yaml")

    assert config["dry_run"] is True
    assert config["gpt_sft"]["api_key_env"] == "RS_AGENT_GPT_SFT_API_KEY"
    assert config["gpt_sft"]["provider"] == "openai_compatible"
    assert config["data"]["max_samples"] == 3
    assert config["data"]["sft_schema"] == "rs_agent_sft_sample_v1"


def test_gpt_sft_config_allows_env_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_GPT_SFT_MODEL", "gpt-env-model")
    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_BASE", "https://proxy.example.com")

    config = load_gpt_sft_config("configs/training/gpt_sft_api_smoke.yaml")

    assert config["gpt_sft"]["model"] == "gpt-env-model"
    assert config["gpt_sft"]["api_base"] == "https://proxy.example.com"


def test_gpt_sft_config_rejects_insecure_remote_api_base() -> None:
    with pytest.raises(ValueError, match="https"):
        load_gpt_sft_config("configs/training/gpt_sft_api_smoke.yaml", overrides={"gpt_sft": {"api_base": "http://proxy.example.com"}})


def test_gpt_sft_config_allows_explicit_insecure_localhost() -> None:
    config = load_gpt_sft_config(
        "configs/training/gpt_sft_api_smoke.yaml",
        overrides={"gpt_sft": {"api_base": "http://localhost:8000", "allow_insecure_local_api_base": True}},
    )

    assert config["gpt_sft"]["api_base"] == "http://localhost:8000"


def test_gpt_sft_runner_dry_run_does_not_require_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_AGENT_GPT_SFT_API_KEY", raising=False)

    result = run_gpt_sft("configs/training/gpt_sft_api_smoke.yaml", limit=1)

    assert result["dry_run"] is True
    assert result["api_called"] is False
    assert result["api_key_env"] == "RS_AGENT_GPT_SFT_API_KEY"
    assert "api_key" not in result
    assert result["first_message_summary"][0]["role"] == "system"
    assert "first_messages" not in result
    assert result["sample_count"] == 1


def test_gpt_sft_runner_extracts_training_signals_input(tmp_path) -> None:
    sample = synthetic_sft_samples()[0]
    input_path = tmp_path / "training_signals.json"
    write_json(input_path, {"schema_version": "rs_agent_training_signals_v1", "sft": [sample]})

    result = run_gpt_sft("configs/training/gpt_sft_api_smoke.yaml", input_path=str(input_path), limit=1)

    assert result["input_path"] == str(input_path)
    assert result["seed_count"] == 1
    assert result["sample_count"] == 1


def test_gpt_sft_runner_extracts_raw_json_sample_list(tmp_path) -> None:
    input_path = tmp_path / "samples.json"
    input_path.write_text(json.dumps(synthetic_sft_samples(), ensure_ascii=False), encoding="utf-8")

    result = run_gpt_sft("configs/training/gpt_sft_api_smoke.yaml", input_path=str(input_path), limit=1)

    assert result["seed_count"] == 1
    assert result["sample_count"] == 1


def test_gpt_sft_runner_resolves_default_config_outside_repo_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    result = run_gpt_sft("configs/training/gpt_sft_api_smoke.yaml", limit=1)

    assert result["sample_count"] == 1
    assert result["output_path"].replace("\\", "/").endswith("RS_agent/outputs/training/gpt_sft_generation_smoke/sft_samples.jsonl")


def test_gpt_sft_runner_execute_requires_enabled_config() -> None:
    with pytest.raises(GptSftExecutionDisabledError, match="dry_run=false"):
        run_gpt_sft("configs/training/gpt_sft_api_smoke.yaml", execute=True, limit=1)


def test_generate_gpt_sft_sample_preserves_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        sample_payload = synthetic_sft_samples()[0]["sample"]
        generated_sample = {
            **sample_payload,
            "assistant_response": "推荐 speaker_1，因为它满足音频偏好。",
            "target_explanation": "speaker_1 属于 Audio，并且来自候选池。",
        }
        return {
            "id": "chatcmpl-test",
            "model": payload["model"],
            "choices": [{"message": {"role": "assistant", "content": json.dumps(generated_sample, ensure_ascii=False)}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 12},
        }

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    sample = synthetic_sft_samples()[0]
    client = OpenAICompatibleClient(transport=fake_transport)

    generated = generate_gpt_sft_sample(
        sample,
        client=client,
        model="gpt-test",
        system_prompt="生成推荐回复",
        temperature=0.2,
        max_tokens=64,
        response_format={"type": "json_object"},
    )

    validate_sft_sample(generated)
    assert generated["sample"]["assistant_response"] == "推荐 speaker_1，因为它满足音频偏好。"
    assert generated["metadata"]["provider"] == "openai_compatible"
    assert generated["metadata"]["response"]["usage"] == {"total_tokens": 12}
    assert "secret-test-key" not in str(generated["metadata"])


def test_generate_gpt_sft_sample_rejects_unknown_item(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        sample_payload = synthetic_sft_samples()[0]["sample"]
        generated_sample = {
            **sample_payload,
            "target_action": {
                **sample_payload["target_action"],
                "selected_item_ids": ["missing"],
                "allowed_item_ids": ["speaker_1", "wired_1", "missing"],
            },
        }
        return {"choices": [{"message": {"content": json.dumps(generated_sample)}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    client = OpenAICompatibleClient(transport=fake_transport)

    with pytest.raises(ValueError, match="seed candidate pool|candidate_summary|seed allowed item set"):
        generate_gpt_sft_sample(
            synthetic_sft_samples()[0],
            client=client,
            model="gpt-test",
            system_prompt="生成推荐回复",
            temperature=0.2,
            max_tokens=64,
            response_format={"type": "json_object"},
        )


def test_generate_gpt_sft_sample_rejects_spoofed_candidate_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        sample_payload = synthetic_sft_samples()[0]["sample"]
        generated_sample = {
            **sample_payload,
            "candidate_summary": [*sample_payload["candidate_summary"], {"item_id": "missing", "sources": ["gpt"], "category": "Audio"}],
            "target_action": {
                **sample_payload["target_action"],
                "selected_item_ids": ["missing"],
                "allowed_item_ids": ["speaker_1", "wired_1", "missing"],
            },
        }
        return {"choices": [{"message": {"content": json.dumps(generated_sample)}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    client = OpenAICompatibleClient(transport=fake_transport)

    with pytest.raises(ValueError, match="seed candidate pool"):
        generate_gpt_sft_sample(
            synthetic_sft_samples()[0],
            client=client,
            model="gpt-test",
            system_prompt="生成推荐回复",
            temperature=0.2,
            max_tokens=64,
            response_format={"type": "json_object"},
        )


def test_generate_gpt_sft_sample_keeps_seed_candidate_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        sample_payload = synthetic_sft_samples()[0]["sample"]
        generated_sample = {
            **sample_payload,
            "candidate_summary": [{"item_id": "speaker_1", "sources": ["gpt"], "category": "Books"}],
            "assistant_response": "推荐 speaker_1。",
        }
        return {"choices": [{"message": {"content": json.dumps(generated_sample)}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    client = OpenAICompatibleClient(transport=fake_transport)

    generated = generate_gpt_sft_sample(
        synthetic_sft_samples()[0],
        client=client,
        model="gpt-test",
        system_prompt="生成推荐回复",
        temperature=0.2,
        max_tokens=64,
        response_format={"type": "json_object"},
    )

    assert generated["sample"]["candidate_summary"] == synthetic_sft_samples()[0]["sample"]["candidate_summary"]


def test_generate_gpt_sft_sample_forces_candidate_constraint_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        sample_payload = synthetic_sft_samples()[0]["sample"]
        generated_sample = {
            **sample_payload,
            "target_action": {**sample_payload["target_action"], "must_select_from_candidates": False},
        }
        return {"choices": [{"message": {"content": json.dumps(generated_sample)}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    client = OpenAICompatibleClient(transport=fake_transport)

    generated = generate_gpt_sft_sample(
        synthetic_sft_samples()[0],
        client=client,
        model="gpt-test",
        system_prompt="生成推荐回复",
        temperature=0.2,
        max_tokens=64,
        response_format={"type": "json_object"},
    )

    assert generated["sample"]["target_action"]["must_select_from_candidates"] is True


def test_extract_first_json_object_handles_markdown_fence() -> None:
    assert extract_first_json_object('```json\n{"assistant_response":"ok"}\n```') == {"assistant_response": "ok"}


def test_build_gpt_sft_messages_contains_contract_context() -> None:
    messages = build_gpt_sft_messages(synthetic_sft_samples()[0], system_prompt="生成推荐回复")

    assert messages[0] == {"role": "system", "content": "生成推荐回复"}
    assert "allowed_item_ids" in messages[1]["content"]
    assert "candidate_summary" in messages[1]["content"]
    assert "target_action" in messages[1]["content"]


def test_runner_non_strict_returns_failure_summary_without_output(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    config_path = tmp_path / "execute_config.json"
    output_path = tmp_path / "generated.jsonl"
    write_json(config_path, {"dry_run": False, "gpt_sft": {"enabled": True, "strict": False}, "data": {"output_path": str(output_path)}})

    def fake_chat_completion(self, **_kwargs: Any) -> dict[str, Any]:
        return {"choices": [{"message": {"content": "not json"}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    monkeypatch.setattr(OpenAICompatibleClient, "chat_completion", fake_chat_completion)

    result = run_gpt_sft(str(config_path), execute=True, limit=1)

    assert result["api_called"] is True
    assert result["generated_count"] == 0
    assert result["failed_count"] == 1
    assert not output_path.exists()


def test_runner_execute_writes_valid_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    output_path = tmp_path / "generated.jsonl"

    def fake_chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sample_payload = synthetic_sft_samples()[0]["sample"]
        generated_sample = {**sample_payload, "assistant_response": "推荐 speaker_1。"}
        return {"model": model, "choices": [{"message": {"content": json.dumps(generated_sample, ensure_ascii=False)}, "finish_reason": "stop"}]}

    config_path = tmp_path / "execute_config.json"
    write_json(config_path, {"dry_run": False, "gpt_sft": {"enabled": True}})
    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    monkeypatch.setattr(OpenAICompatibleClient, "chat_completion", fake_chat_completion)

    result = run_gpt_sft(str(config_path), execute=True, limit=1, output_path=str(output_path))

    records = read_jsonl(output_path)
    validate_sft_samples(records)
    assert result["api_called"] is True
    assert result["generated_count"] == 1
    assert records[0]["sample"]["assistant_response"] == "推荐 speaker_1。"
