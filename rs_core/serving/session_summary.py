from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_ENABLED_ENV = "RS_SESSION_SUMMARY_ENABLED"
SUMMARY_OUTPUT_DIR_ENV = "RS_SESSION_SUMMARY_DIR"
SUMMARY_MODEL_ENV = "RS_SESSION_SUMMARY_MODEL"
SUMMARY_BASE_URL_ENV = "RS_SESSION_SUMMARY_BASE_URL"
SUMMARY_API_KEY_ENV_ENV = "RS_SESSION_SUMMARY_API_KEY_ENV"
SUMMARY_TIMEOUT_ENV = "RS_SESSION_SUMMARY_TIMEOUT_SECONDS"
SUMMARY_MAX_INPUT_CHARS_ENV = "RS_SESSION_SUMMARY_MAX_INPUT_CHARS"
SUMMARY_API_KEY_DEFAULT_ENV = "RS_SESSION_SUMMARY_API_KEY"

_FALSE_VALUES = {"", "0", "false", "no", "off"}
_SAFE_SESSION_ID = re.compile(r"[^A-Za-z0-9_.-]+")
_FORBIDDEN_SUMMARY_TERMS = {
    "agent_tool_trace",
    "agent_tool_events",
    "agent_tool_summary",
    "diagnostics",
    "query_rag",
    "rag_context",
    "raw_evidence",
    "reward_evidence",
    "runtime_trace",
    "score_trace",
    "source_path",
    "source_scores",
    "tool_trace",
    "tool_traces",
    "training_samples",
}
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|password|passwd|pwd|bearer)\b\s*[:=]\s*[^\s,;]+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


@dataclass(frozen=True)
class SummaryDocumentResult:
    relative_path: str | None = None
    created: bool = False
    error: str | None = None


class SessionSummaryServiceProtocol(Protocol):
    def summarize_and_write(
        self,
        public_export: dict[str, Any],
        *,
        reason: str,
        client_event: str | None = None,
        request_id: str | None = None,
    ) -> SummaryDocumentResult:
        ...


class DisabledSessionSummaryService:
    def summarize_and_write(self, public_export: dict[str, Any], **_: Any) -> SummaryDocumentResult:
        return SummaryDocumentResult(created=False, error="LLM_SESSION_SUMMARY_DISABLED")


class LLMSessionSummaryService:
    """Generate a public-safe end-of-session markdown summary through an LLM."""

    def __init__(
        self,
        *,
        output_dir: str | Path,
        model: str,
        client: OpenAICompatibleClient,
        max_input_chars: int = 12000,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.model = model
        self.client = client
        self.max_input_chars = max(1000, int(max_input_chars))

    def summarize_and_write(
        self,
        public_export: dict[str, Any],
        *,
        reason: str,
        client_event: str | None = None,
        request_id: str | None = None,
    ) -> SummaryDocumentResult:
        session_id = str(public_export.get("session_id") or "unknown-session")
        try:
            safe_export = _public_summary_input(public_export)
            messages = _build_summary_messages(safe_export, reason=reason, client_event=client_event, max_input_chars=self.max_input_chars)
            response = self.client.chat_completion(
                model=self.model,
                messages=messages,
                temperature=0.2,
                max_tokens=1200,
            )
            markdown = _normalize_markdown(_redact_sensitive_text(first_message_content(response)), safe_export, reason, client_event, request_id)
            _reject_forbidden_summary_terms(markdown)
            path = self._document_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown, encoding="utf-8")
            return SummaryDocumentResult(relative_path=_relative_to_project(path), created=True, error=None)
        except Exception as exc:
            return SummaryDocumentResult(relative_path=None, created=False, error=_safe_error_code(exc))

    def _document_path(self, session_id: str) -> Path:
        safe_id = _safe_session_id(session_id)
        return self.output_dir / f"{safe_id}.md"


class FakeLLMSessionSummaryService:
    """Small injectable LLM-like summary service for tests."""

    def __init__(self, output_dir: str | Path, markdown: str | None = None) -> None:
        self.output_dir = Path(output_dir)
        self.markdown = markdown or "# 会话总结\n\n## 本次用户目标\n\n用户完成了一次推荐会话。\n"
        self.calls: list[dict[str, Any]] = []

    def summarize_and_write(
        self,
        public_export: dict[str, Any],
        *,
        reason: str,
        client_event: str | None = None,
        request_id: str | None = None,
    ) -> SummaryDocumentResult:
        self.calls.append({
            "public_export": public_export,
            "reason": reason,
            "client_event": client_event,
            "request_id": request_id,
        })
        session_id = str(public_export.get("session_id") or "unknown-session")
        path = self.output_dir / f"{_safe_session_id(session_id)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.markdown, encoding="utf-8")
        return SummaryDocumentResult(relative_path=_relative_to_project(path), created=True, error=None)


def build_session_summary_service(config: dict[str, Any] | None = None) -> SessionSummaryServiceProtocol:
    summary_config = _summary_config(config)
    enabled = _env_bool(SUMMARY_ENABLED_ENV, bool(summary_config.get("enabled", False)))
    model = str(os.environ.get(SUMMARY_MODEL_ENV) or summary_config.get("model") or "").strip()
    if not enabled or not model:
        return DisabledSessionSummaryService()
    base_url = str(os.environ.get(SUMMARY_BASE_URL_ENV) or summary_config.get("base_url") or "https://api.openai.com")
    api_key_env = str(os.environ.get(SUMMARY_API_KEY_ENV_ENV) or summary_config.get("api_key_env") or SUMMARY_API_KEY_DEFAULT_ENV)
    timeout = float(os.environ.get(SUMMARY_TIMEOUT_ENV) or summary_config.get("timeout_seconds") or 30)
    output_dir = os.environ.get(SUMMARY_OUTPUT_DIR_ENV) or summary_config.get("output_dir") or PROJECT_ROOT / "outputs" / "serving" / "session_summaries"
    max_input_chars = int(os.environ.get(SUMMARY_MAX_INPUT_CHARS_ENV) or summary_config.get("max_input_chars") or 12000)
    client = OpenAICompatibleClient(
        base_url=base_url,
        api_key_env=api_key_env,
        timeout_seconds=timeout,
        allow_insecure_local_api_base=True,
    )
    return LLMSessionSummaryService(output_dir=output_dir, model=model, client=client, max_input_chars=max_input_chars)


def _summary_config(config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    serving = config.get("serving") if isinstance(config.get("serving"), dict) else {}
    summary = serving.get("session_summary") if isinstance(serving.get("session_summary"), dict) else config.get("session_summary")
    if not isinstance(summary, dict):
        return {}
    llm = summary.get("llm") if isinstance(summary.get("llm"), dict) else {}
    merged = {key: value for key, value in summary.items() if key != "llm"}
    merged.update(llm)
    return merged


def build_public_session_summary_input(public_export: dict[str, Any]) -> dict[str, Any]:
    return _public_summary_input(public_export)


def _public_summary_input(public_export: dict[str, Any]) -> dict[str, Any]:
    timeline = public_export.get("public_timeline") if isinstance(public_export.get("public_timeline"), dict) else {}
    events = timeline.get("events") if isinstance(timeline.get("events"), list) else []
    displays = public_export.get("display_responses") if isinstance(public_export.get("display_responses"), list) else []
    return {
        "schema_version": "rs_agent_session_summary_input_v1",
        "session_id": _redact_sensitive_text(public_export.get("session_id") or ""),
        "user_id": _redact_sensitive_text(public_export.get("user_id") or ""),
        "turn_count": int(public_export.get("turn_count") or len(events)),
        "events": [_public_event(event) for event in events],
        "display_responses": [_public_display(display) for display in displays],
    }


def _public_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        return {}
    return {
        "event_type": str(event.get("event_type") or ""),
        "turn_index": event.get("turn_index"),
        "user_message": _redact_sensitive_text(_truncate_text(event.get("user_message"), 800)),
        "assistant_message": _redact_sensitive_text(_truncate_text(event.get("assistant_message"), 1000)),
    }


def _public_display(display: Any) -> dict[str, Any]:
    if not isinstance(display, dict):
        return {}
    items = display.get("items") if isinstance(display.get("items"), list) else []
    return {
        "turn_index": display.get("turn_index"),
        "assistant_message": _redact_sensitive_text(_truncate_text(display.get("assistant_message"), 1000)),
        "items": [_public_item(item) for item in items[:10]],
        "feedback_actions": [
            {"type": str(action.get("type") or ""), "label": str(action.get("label") or "")}
            for action in display.get("feedback_actions", [])
            if isinstance(action, dict)
        ][:8],
    }


def _public_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {
        "parent_asin": _safe_frontmatter_scalar(item.get("parent_asin") or ""),
        "title": _redact_sensitive_text(_truncate_text(item.get("title"), 180)),
        "category": _redact_sensitive_text(_truncate_text(item.get("category"), 120)),
        "price": item.get("price"),
        "rating": item.get("rating"),
        "features": [_redact_sensitive_text(_truncate_text(feature, 160)) for feature in (item.get("features") or [])[:5]],
        "badges": [_safe_frontmatter_scalar(badge) for badge in (item.get("badges") or [])[:5]],
        "summary": _redact_sensitive_text(_truncate_text(item.get("summary"), 240)),
    }


def _build_summary_messages(public_input: dict[str, Any], *, reason: str, client_event: str | None, max_input_chars: int = 12000) -> list[dict[str, str]]:
    payload = _truncate_text(_json_dumps(public_input), max_input_chars)
    system = (
        "你是推荐系统的会话总结助手。只能根据提供的 public-safe 会话数据总结，"
        "不要编造未出现的商品、偏好或行为。不要提及工具链路、RAG 原始证据、召回分路、分数、source、diagnostics、训练或内部 trace。"
        "输出中文 Markdown，包含：本次用户目标、关键偏好与约束、推荐与反馈过程、明确喜欢/不喜欢的方向、最终可能的购买或继续探索方向、下次会话可继承的信息。"
    )
    user = (
        f"结束原因: {reason}\n"
        f"客户端事件: {client_event or 'unknown'}\n"
        "请总结以下 public-safe 推荐会话数据：\n"
        f"```json\n{payload}\n```"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _normalize_markdown(markdown: str, public_input: dict[str, Any], reason: str, client_event: str | None, request_id: str | None) -> str:
    body = markdown.strip()
    if not body.startswith("#"):
        body = "# 会话总结\n\n" + body
    header = [
        "---",
        "schema_version: rs_agent_session_summary_document_v1",
        f"session_id: {_frontmatter_scalar(_redact_sensitive_text(public_input.get('session_id', '')))}",
        f"user_id: {_frontmatter_scalar(_redact_sensitive_text(public_input.get('user_id', '')))}",
        f"turn_count: {public_input.get('turn_count', 0)}",
        f"end_reason: {_frontmatter_scalar(_redact_sensitive_text(reason))}",
        f"client_event: {_frontmatter_scalar(_redact_sensitive_text(client_event or 'unknown'))}",
        f"request_id: {_frontmatter_scalar(_redact_sensitive_text(request_id or ''))}",
        "---",
        "",
    ]
    return "\n".join(header) + body + "\n"


def _reject_forbidden_summary_terms(markdown: str) -> None:
    lowered = markdown.lower()
    matched = sorted(term for term in _FORBIDDEN_SUMMARY_TERMS if term in lowered)
    if matched:
        raise ValueError(f"LLM summary contained forbidden internal terms: {matched[:3]}")


def _safe_session_id(session_id: str) -> str:
    normalized = _SAFE_SESSION_ID.sub("-", str(session_id).strip()).strip(".-")
    return normalized or "unknown-session"


def _relative_to_project(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return resolved.name


def _safe_error_code(exc: Exception) -> str:
    text = str(exc).lower()
    if "api key" in text:
        return "LLM_API_KEY_MISSING"
    if "forbidden internal terms" in text:
        return "LLM_SUMMARY_FORBIDDEN_TERM"
    if "model is required" in text:
        return "LLM_MODEL_MISSING"
    return "LLM_SESSION_SUMMARY_FAILED"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in _FALSE_VALUES


def _truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "").replace("\r", " ").strip()
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _redact_sensitive_text(value: Any) -> str:
    text = str(value or "")
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[REDACTED_SECRET]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED_SECRET]", text)
    text = _OPENAI_KEY_RE.sub("[REDACTED_SECRET]", text)
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    return _LONG_TOKEN_RE.sub("[REDACTED_TOKEN]", text)


def _frontmatter_scalar(value: Any) -> str:
    text = _safe_frontmatter_scalar(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _safe_frontmatter_scalar(value: Any) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _json_dumps(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
