from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DEFAULT_API_KEY_ENV = "RS_AGENT_GPT_SFT_API_KEY"
DEFAULT_BASE_URL = "https://api.openai.com"

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


@dataclass(frozen=True)
class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat completions client for offline SFT data jobs."""

    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_seconds: float = 60.0
    allow_insecure_local_api_base: bool = False
    transport: Transport | None = None

    def chat_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not str(model).strip():
            raise ValueError("model is required")
        self._validate_base_url()
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"API key environment variable is not set: {self.api_key_env}")

        payload: dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format:
            payload["response_format"] = response_format
        if extra_body:
            payload.update(extra_body)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        transport = self.transport or _default_transport
        try:
            return transport(self._chat_completions_url(), headers, payload, self.timeout_seconds)
        except HTTPError as exc:
            raise RuntimeError(f"OpenAI-compatible request failed with HTTP {exc.code}: {_safe_http_error_body(exc)}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI-compatible request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI-compatible response was not valid JSON") from exc

    def _chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"

    def _validate_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme == "https":
            return
        if self.allow_insecure_local_api_base and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            return
        raise ValueError("OpenAI-compatible base_url must use https unless allow_insecure_local_api_base=true for localhost/127.0.0.1")


def first_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI-compatible response missing choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("OpenAI-compatible response missing choices[0].message")
    if message.get("refusal"):
        raise ValueError(f"OpenAI-compatible response contained refusal: {str(message['refusal'])[:200]}")
    content = _message_content_text(message.get("content"))
    if not content.strip():
        raise ValueError("OpenAI-compatible response missing non-empty message content")
    return content


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


def safe_response_metadata(response: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": response.get("id"),
        "model": response.get("model"),
        "usage": response.get("usage"),
        "finish_reason": _first_finish_reason(response),
    }


def _default_transport(url: str, headers: dict[str, str], payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310 - endpoint is explicit user config.
        return json.loads(response.read().decode("utf-8"))


def _safe_http_error_body(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")[:500]
    except Exception:
        return "<unavailable>"
    return _redact_sensitive_text(body.replace("\r", " ").replace("\n", " "))


def _redact_sensitive_text(text: str) -> str:
    redacted = re.sub(r"Bearer\s+[^\s\"']+", "Bearer <redacted>", text, flags=re.IGNORECASE)
    redacted = re.sub(r"(Authorization\s*[:=]\s*)[^,;}]+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"(api[_-]?key\s*[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;}]+", r"\1<redacted>", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", redacted)
    return redacted


def _first_finish_reason(response: dict[str, Any]) -> Any:
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason")
    return None
