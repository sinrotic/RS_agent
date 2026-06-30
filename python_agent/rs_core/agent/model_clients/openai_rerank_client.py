from __future__ import annotations

import json
import re
from typing import Any

from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content, safe_response_metadata
from rs_core.common.recsys_types import MergedCandidate
from rs_core.agent.inference import (
    InferencePolicyError,
    ModelOutputParseError,
    QWEN_POLICY_TYPE,
    RerankPolicyResult,
    build_rerank_prompt_payload,
)
from rs_core.agent.model_clients.qwen_client import _signals_from_payload, extract_first_json_object
from rs_core.agent.contracts.schema import FeedbackConstraints


class OpenAICompatibleRerankClient:
    def __init__(self, policy_config: dict[str, Any], client: OpenAICompatibleClient | None = None) -> None:
        self.policy_config = policy_config
        self.client = client or _build_openai_client(policy_config)

    def rerank(
        self,
        *,
        user_sequence: dict[str, Any],
        feedback_constraints: FeedbackConstraints | None,
        candidates: list[MergedCandidate],
        config: dict[str, Any],
    ) -> RerankPolicyResult:
        openai_config = dict(self.policy_config.get("openai_compatible", {}) or {})
        model = str(openai_config.get("model") or self.policy_config.get("model", {}).get("model_id") or "").strip()
        if not model:
            raise InferencePolicyError("OpenAI-compatible inference model is not configured.")
        payload = build_rerank_prompt_payload(
            user_sequence=user_sequence,
            feedback_constraints=feedback_constraints,
            candidates=candidates,
            policy=self.policy_config,
        )
        try:
            response = self.client.chat_completion(
                model=model,
                messages=_messages_for_payload(payload),
                temperature=float(openai_config.get("temperature", 0.0)),
                max_tokens=int(openai_config.get("max_tokens", 512)),
                response_format=openai_config.get("response_format") if isinstance(openai_config.get("response_format"), dict) else None,
                extra_body=openai_config.get("extra_body") if isinstance(openai_config.get("extra_body"), dict) else None,
            )
            output_text = first_message_content(response)
            parsed = extract_first_json_object(output_text)
        except ModelOutputParseError:
            raise
        except (RuntimeError, ValueError) as exc:
            raise InferencePolicyError(f"OpenAI-compatible inference request failed: {_safe_error_message(exc)}") from exc
        except Exception as exc:
            raise InferencePolicyError(f"OpenAI-compatible inference request failed: {exc.__class__.__name__}") from exc
        try:
            signals = _signals_from_payload(parsed)
        except ModelOutputParseError:
            raise
        except Exception as exc:
            raise ModelOutputParseError("OpenAI-compatible model output could not be converted to rerank signals.") from exc
        return RerankPolicyResult(
            policy_type=str(self.policy_config.get("policy_type", QWEN_POLICY_TYPE)),
            signals=signals,
            diagnostics={
                "provider": "openai_compatible",
                "raw_policy_notes": str(parsed.get("policy_notes", ""))[:500],
                "response_metadata": safe_response_metadata(response),
            },
        )


def _build_openai_client(policy_config: dict[str, Any]) -> OpenAICompatibleClient:
    openai_config = dict(policy_config.get("openai_compatible", {}) or {})
    return OpenAICompatibleClient(
        base_url=str(openai_config.get("base_url") or "https://api.openai.com"),
        api_key_env=str(openai_config.get("api_key_env") or "RS_AGENT_OPENAI_COMPATIBLE_API_KEY"),
        timeout_seconds=float(openai_config.get("timeout_seconds", 30.0)),
        allow_insecure_local_api_base=bool(openai_config.get("allow_insecure_local_api_base", False)),
    )


def _messages_for_payload(payload: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You are a rerank-signal generator. Return exactly one JSON object and no prose.",
        },
        {
            "role": "user",
            "content": "Return JSON matching the requested output_schema. Payload: "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _safe_error_message(exc: Exception) -> str:
    text = str(exc)
    text = re.sub(r"Bearer\s+[^\s\"']+", "Bearer <redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", text)
    text = re.sub(r"(api[_-]?key\s*[\"']?\s*[:=]\s*[\"']?)[^\"'\s,;}]+", r"\1<redacted>", text, flags=re.IGNORECASE)
    return text[:500]
