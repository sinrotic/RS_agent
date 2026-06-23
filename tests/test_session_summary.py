from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rs_core.serving.session_summary import (
    DisabledSessionSummaryService,
    LLMSessionSummaryService,
    _build_summary_messages,
    _public_summary_input,
    build_public_session_summary_input,
)

pytestmark = [pytest.mark.serving, pytest.mark.smoke]


class FakeChatClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"choices": [{"message": {"content": self.content}}]}


def test_llm_session_summary_writes_public_safe_markdown(tmp_path: Path) -> None:
    client = FakeChatClient("# 会话总结\n\n## 本次用户目标\n\n用户想找通勤蓝牙音频商品。\n")
    service = LLMSessionSummaryService(
        output_dir=tmp_path,
        model="summary-model",
        client=client,  # type: ignore[arg-type]
        max_input_chars=4000,
    )
    public_export = _public_export_with_internal_noise()

    result = service.summarize_and_write(
        public_export,
        reason="manual",
        client_event="manual",
        request_id="req-summary",
    )

    assert result.created is True
    assert result.error is None
    assert result.relative_path
    summary_path = tmp_path / "session-1.md"
    markdown = summary_path.read_text(encoding="utf-8")
    assert "schema_version: rs_agent_session_summary_document_v1" in markdown
    assert 'session_id: "session-1"' in markdown
    assert "用户想找通勤蓝牙音频商品" in markdown
    assert client.calls[0]["model"] == "summary-model"
    serialized_messages = str(client.calls[0]["messages"])
    assert "agent_thoughts" not in serialized_messages
    assert "tool_traces" not in serialized_messages
    assert "raw_evidence" not in serialized_messages
    assert "score_trace" not in serialized_messages


def test_public_summary_input_strips_internal_fields_and_redacts_sensitive_text() -> None:
    payload = _public_export_with_internal_noise()
    payload["public_timeline"]["events"][0]["user_message"] = "email me at buyer@example.com, phone +1 415 555 0100, api_key=sk-secret123456789"
    safe_input = _public_summary_input(payload)
    serialized = str(safe_input).lower()

    assert safe_input["session_id"] == "session-1"
    assert safe_input["turn_count"] == 1
    assert safe_input["events"][0]["user_message"] == "email me at [REDACTED_EMAIL], phone [REDACTED_PHONE], api_key=[REDACTED_SECRET]"
    assert safe_input["display_responses"][0]["items"][0]["title"] == "Bluetooth Speaker"
    assert "buyer@example.com" not in serialized
    assert "+1 415 555 0100" not in serialized
    assert "sk-secret" not in serialized
    assert "agent_thoughts" not in serialized
    assert "diagnostics" not in serialized
    assert "tool_traces" not in serialized
    assert "raw_evidence" not in serialized
    assert "score_trace" not in serialized


def test_public_session_summary_input_alias_matches_private_builder() -> None:
    payload = _public_export_with_internal_noise()

    safe_input = build_public_session_summary_input(payload)

    assert safe_input == _public_summary_input(payload)
    serialized = str(safe_input).lower()
    assert "diagnostics" not in serialized
    assert "raw_evidence" not in serialized
    assert "score_trace" not in serialized
    assert "agent_thoughts" not in serialized


def test_summary_frontmatter_quotes_user_controlled_values(tmp_path: Path) -> None:
    client = FakeChatClient("# 会话总结\n\n安全元数据。")
    service = LLMSessionSummaryService(
        output_dir=tmp_path,
        model="summary-model",
        client=client,  # type: ignore[arg-type]
    )
    public_export = _public_export_with_internal_noise()
    public_export["user_id"] = "u1\nend_reason: checkout buyer@example.com"

    result = service.summarize_and_write(public_export, reason="manual", client_event="manual", request_id="api_key=sk-secret123456789")

    assert result.created is True
    markdown = (tmp_path / "session-1.md").read_text(encoding="utf-8")
    assert 'user_id: "u1 end_reason: checkout [REDACTED_EMAIL]"' in markdown
    assert 'request_id: "api_key=[REDACTED_SECRET]"' in markdown
    assert "user_id: u1\nend_reason: checkout" not in markdown
    assert "buyer@example.com" not in markdown
    assert "sk-secret" not in markdown


def test_summary_prompt_uses_bounded_public_json() -> None:
    safe_input = _public_summary_input(_public_export_with_internal_noise())

    messages = _build_summary_messages(safe_input, reason="checkout", client_event="checkout", max_input_chars=200)

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "结束原因: checkout" in messages[1]["content"]
    assert len(messages[1]["content"]) < 500
    assert "agent_thoughts" not in messages[1]["content"]


def test_llm_summary_redacts_model_output_before_writing(tmp_path: Path) -> None:
    client = FakeChatClient("# 会话总结\n\n联系 buyer@example.com，token=abcdefghijklmnopqrstuvwxyz123456。")
    service = LLMSessionSummaryService(
        output_dir=tmp_path,
        model="summary-model",
        client=client,  # type: ignore[arg-type]
    )

    result = service.summarize_and_write(_public_export_with_internal_noise(), reason="manual")

    assert result.created is True
    markdown = (tmp_path / "session-1.md").read_text(encoding="utf-8")
    assert "buyer@example.com" not in markdown
    assert "abcdefghijklmnopqrstuvwxyz123456" not in markdown
    assert "[REDACTED_EMAIL]" in markdown
    assert "[REDACTED_TOKEN]" in markdown


def test_llm_summary_rejects_forbidden_internal_terms(tmp_path: Path) -> None:
    client = FakeChatClient("# 会话总结\n\n这里错误地提到了 tool_trace。")
    service = LLMSessionSummaryService(
        output_dir=tmp_path,
        model="summary-model",
        client=client,  # type: ignore[arg-type]
    )

    result = service.summarize_and_write(_public_export_with_internal_noise(), reason="manual")

    assert result.created is False
    assert result.error == "LLM_SUMMARY_FORBIDDEN_TERM"
    assert not (tmp_path / "session-1.md").exists()


def test_disabled_session_summary_service_reports_safe_error_code() -> None:
    result = DisabledSessionSummaryService().summarize_and_write(_public_export_with_internal_noise(), reason="manual")

    assert result.created is False
    assert result.relative_path is None
    assert result.error == "LLM_SESSION_SUMMARY_DISABLED"


def _public_export_with_internal_noise() -> dict[str, Any]:
    return {
        "session_id": "session-1",
        "user_id": "u1",
        "turn_count": 1,
        "agent_thoughts": [{"tool_traces": ["do not leak"]}],
        "public_timeline": {
            "events": [
                {
                    "event_type": "chat",
                    "turn_index": 1,
                    "user_message": "For commute, prefer bluetooth and Audio",
                    "assistant_message": "我推荐几款蓝牙音频商品。",
                    "diagnostics": {"internal": True},
                }
            ]
        },
        "display_responses": [
            {
                "turn_index": 1,
                "assistant_message": "我推荐几款蓝牙音频商品。",
                "diagnostics": {"raw_evidence": "do not leak"},
                "items": [
                    {
                        "parent_asin": "speaker_1",
                        "title": "Bluetooth Speaker",
                        "category": "Audio",
                        "price": 39.99,
                        "rating": 4.7,
                        "features": ["portable", "wireless"],
                        "summary": "适合通勤使用。",
                        "score_trace": {"rank": 1},
                    }
                ],
                "feedback_actions": [{"type": "like", "label": "喜欢"}],
            }
        ],
    }
