from __future__ import annotations

from io import BytesIO
from typing import Any
from urllib.error import HTTPError

import pytest

pytestmark = pytest.mark.unit

from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content, safe_response_metadata


def test_openai_compatible_client_builds_chat_completion_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        captured.update({"url": url, "headers": headers, "payload": payload, "timeout_seconds": timeout_seconds})
        return {
            "id": "chatcmpl-test",
            "model": payload["model"],
            "choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 3},
        }

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "unit-test-key")
    client = OpenAICompatibleClient(base_url="https://example.test", timeout_seconds=9, transport=fake_transport)

    response = client.chat_completion(
        model="gpt-test",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.3,
        max_tokens=16,
        response_format={"type": "json_object"},
    )

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer unit-test-key"
    assert captured["headers"]["Accept"] == "application/json"
    assert captured["payload"] == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.3,
        "max_tokens": 16,
        "response_format": {"type": "json_object"},
    }
    assert captured["timeout_seconds"] == 9
    assert first_message_content(response) == "ok"
    assert safe_response_metadata(response) == {
        "id": "chatcmpl-test",
        "model": "gpt-test",
        "usage": {"total_tokens": 3},
        "finish_reason": "stop",
    }


def test_openai_compatible_client_accepts_base_url_with_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_transport(url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        captured["url"] = url
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "unit-test-key")
    client = OpenAICompatibleClient(base_url="https://example.test/v1/", transport=fake_transport)

    client.chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}])

    assert captured["url"] == "https://example.test/v1/chat/completions"


def test_openai_compatible_client_accepts_full_chat_completions_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_transport(url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        captured["url"] = url
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "unit-test-key")
    client = OpenAICompatibleClient(base_url="https://example.test/custom/v1/chat/completions", transport=fake_transport)

    client.chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}])

    assert captured["url"] == "https://example.test/custom/v1/chat/completions"


def test_openai_compatible_client_error_mentions_env_not_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_AGENT_GPT_SFT_API_KEY", raising=False)
    client = OpenAICompatibleClient(transport=lambda *_args: {})

    with pytest.raises(RuntimeError) as exc_info:
        client.chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}])

    message = str(exc_info.value)
    assert "RS_AGENT_GPT_SFT_API_KEY" in message
    assert "Bearer" not in message


def test_openai_compatible_client_rejects_insecure_remote_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "unit-test-key")
    client = OpenAICompatibleClient(base_url="http://proxy.example.com", transport=lambda *_args: {})

    with pytest.raises(ValueError, match="https"):
        client.chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}])


def test_openai_compatible_client_allows_explicit_insecure_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_transport(url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        captured["url"] = url
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "unit-test-key")
    client = OpenAICompatibleClient(base_url="http://localhost:8000", allow_insecure_local_api_base=True, transport=fake_transport)

    client.chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}])

    assert captured["url"] == "http://localhost:8000/v1/chat/completions"


def test_openai_compatible_client_redacts_http_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_transport(_url: str, _headers: dict[str, str], _payload: dict[str, Any], _timeout_seconds: float) -> dict[str, Any]:
        error = HTTPError(
            url="https://example.test/v1/chat/completions",
            code=401,
            msg="unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"Authorization: Bearer sk-secret-token api_key=secret-test-key"}'),
        )
        raise error

    monkeypatch.setenv("RS_AGENT_GPT_SFT_API_KEY", "secret-test-key")
    client = OpenAICompatibleClient(base_url="https://example.test", transport=fake_transport)

    with pytest.raises(RuntimeError) as exc_info:
        client.chat_completion(model="gpt-test", messages=[{"role": "user", "content": "hi"}])

    message = str(exc_info.value)
    assert "sk-secret-token" not in message
    assert "secret-test-key" not in message
    assert "<redacted>" in message


def test_first_message_content_accepts_text_parts() -> None:
    assert first_message_content({"choices": [{"message": {"content": [{"type": "text", "text": "ok"}]}}]}) == "ok"


def test_first_message_content_rejects_refusal() -> None:
    with pytest.raises(ValueError, match="refusal"):
        first_message_content({"choices": [{"message": {"content": "", "refusal": "not allowed"}}]})


def test_first_message_content_rejects_malformed_response() -> None:
    with pytest.raises(ValueError, match="choices"):
        first_message_content({"choices": []})
