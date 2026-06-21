from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DEFAULT_PUBLIC_COMMENT_MAX_CHARS = 500
PUBLIC_FORBIDDEN_FIELD_NAMES = {
    "api_key",
    "apikey",
    "cookie",
    "diagnostics",
    "ground_truth",
    "holdout",
    "label",
    "oracle",
    "password",
    "raw_prompt",
    "secret",
    "target_item",
    "token",
    "tool_trace",
}
_COMPOUND_SECRET_FIELD_NAMES = {"auth_token", "session_cookie"}
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(auth[_-]?token|session[_-]?cookie|token|cookie|secret|api[_-]?key|password)\b\s*(?::|=|\s)\s*[^\s,;]+"
)
_FORBIDDEN_TERM_PATTERN = re.compile(
    r"(?i)\b(raw\s*prompt|tool\s*trace|diagnostics?|oracle|holdout|ground[_\s-]?truth|target[_\s-]?item)\b"
)
_LABEL_FIELD_PATTERN = re.compile(r"(?i)\blabel\s*[:=]\s*[^\s,;]+")


@dataclass(frozen=True)
class PublicText:
    text: str
    truncated: bool = False
    redacted: bool = False


def sanitize_public_text(value: Any, *, max_chars: int | None = None) -> PublicText:
    """Return public-safe free text for trial exports and audit rows."""

    text = "" if value is None else str(value)
    redacted = False

    def _secret_replacement(match: re.Match[str]) -> str:
        nonlocal redacted
        redacted = True
        return "[REDACTED]"

    text = _SECRET_ASSIGNMENT_PATTERN.sub(_secret_replacement, text)
    text, forbidden_count = _FORBIDDEN_TERM_PATTERN.subn("[FILTERED]", text)
    if forbidden_count:
        redacted = True
    text, label_count = _LABEL_FIELD_PATTERN.subn("label=[FILTERED]", text)
    if label_count:
        redacted = True

    truncated = False
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return PublicText(text=text, truncated=truncated, redacted=redacted)


def sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            normalized = _normalize_key(key)
            if _is_forbidden_public_key(normalized):
                continue
            sanitized[str(key)] = sanitize_public_payload(child)
        return sanitized
    if isinstance(value, list):
        return [sanitize_public_payload(child) for child in value]
    if isinstance(value, str):
        return sanitize_public_text(value).text
    return value


def _is_forbidden_public_key(normalized_key: str) -> bool:
    return normalized_key in PUBLIC_FORBIDDEN_FIELD_NAMES or normalized_key in _COMPOUND_SECRET_FIELD_NAMES


def _normalize_key(key: Any) -> str:
    raw_key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key).strip())
    return re.sub(r"[\s\-]+", "_", raw_key.lower())
