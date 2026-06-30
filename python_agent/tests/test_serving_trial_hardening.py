from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from rs_core.display.public_safety import sanitize_public_payload
from rs_core.serving.persistence import RETENTION_DAYS, SQLiteJsonlServingPersistenceStore

pytestmark = [pytest.mark.serving, pytest.mark.smoke]

FORBIDDEN_PUBLIC_TERMS = {
    "token",
    "cookie",
    "secret",
    "api_key",
    "auth_token",
    "session_cookie",
    "authtoken",
    "sessioncookie",
    "password",
    "raw prompt",
    "tool trace",
    "diagnostics",
    "oracle",
    "label=1",
    "holdout",
    "ground_truth",
    "target_item",
}


def test_feedback_comment_is_truncated_redacted_and_queryable(tmp_path: Path) -> None:
    store = SQLiteJsonlServingPersistenceStore(tmp_path / "serving.sqlite", tmp_path / "events.jsonl")
    comment = "auth_token abc authToken def sessionCookie xyz session_cookie zzz raw prompt label=1 " + "x" * 650

    store.record_feedback_event(
        session_id="s1",
        turn_index=1,
        action_type="why",
        item_id="item-1",
        comment=comment,
        request_id="req-feedback",
    )

    with sqlite3.connect(tmp_path / "serving.sqlite") as connection:
        row = connection.execute(
            "SELECT comment, comment_truncated, comment_redacted FROM serving_feedback_events WHERE session_id = 's1'"
        ).fetchone()
    assert row is not None
    persisted_comment, truncated, redacted = row
    assert len(persisted_comment) == 500
    assert truncated == 1
    assert redacted == 1
    assert "[REDACTED]" in persisted_comment
    assert "[FILTERED]" in persisted_comment
    _assert_public_safe(json.dumps(row, ensure_ascii=False).lower())


def test_session_export_sanitizes_public_timeline_messages(tmp_path: Path) -> None:
    store = SQLiteJsonlServingPersistenceStore(tmp_path / "serving.sqlite", tmp_path / "events.jsonl")
    display = _display_payload("Safe public explanation")

    store.record_turn_committed(
        session_id="s1",
        user_id="u1",
        turn_index=1,
        event_type="chat",
        user_message="Need headphones token=abc raw prompt target_item=B001",
        assistant_message="No diagnostics or tool trace should leak.",
        display=display,
        request_id="req-chat",
    )

    public_export = store.load_public_session_export("s1")

    assert public_export is not None
    serialized = json.dumps(public_export, ensure_ascii=False).lower()
    _assert_public_safe(serialized)
    event = public_export["public_timeline"]["events"][0]
    assert event["user_message"] == "Need headphones [REDACTED] [FILTERED] [FILTERED]=B001"
    assert event["assistant_message"] == "No [FILTERED] or [FILTERED] should leak."
    assert set(public_export) == {"session_id", "user_id", "turn_count", "public_timeline", "display_responses"}


def test_payload_sanitizer_drops_secret_keys_without_deleting_safe_neighbors() -> None:
    payload = {
        "token": "abc",
        "cookie": "xyz",
        "auth_token": "abc",
        "authToken": "def",
        "sessionCookie": "cookie-1",
        "session_cookie": "cookie-2",
        "api_key": "key-1",
        "password": "pw",
        "customer_token_preference": "allowed public preference",
        "sessionCookiePolicy": "allowed public policy",
        "tokenized": "allowed public word",
        "path_count": 2,
    }

    assert sanitize_public_payload(payload) == {
        "customer_token_preference": "allowed public preference",
        "sessionCookiePolicy": "allowed public policy",
        "tokenized": "allowed public word",
        "path_count": 2,
    }


def test_request_and_jsonl_public_summaries_drop_sensitive_fields(tmp_path: Path) -> None:
    store = SQLiteJsonlServingPersistenceStore(tmp_path / "serving.sqlite", tmp_path / "events.jsonl")

    store.record_request_summary(
        request_id="req-1",
        endpoint="recall",
        user_id="u1",
        candidate_count=10,
        public_summary={
            "http_request_id": "http-1",
            "token": "abc",
            "cookie": "xyz",
            "auth_token": "abc",
            "authToken": "def",
            "api_key": "key-1",
            "sessionCookie": "cookie-1",
            "session_cookie": "cookie-2",
            "password": "pw",
            "customer_token_preference": "allowed public preference",
            "sessionCookiePolicy": "allowed public policy",
            "tokenized": "allowed public word",
            "ground_truth": "positive item",
            "retrieval_summary": {
                "target_pool_size": 500,
                "path_count": 2,
                "diagnostics": "internal",
                "target_item": "B001",
                "password": "pw",
            },
        },
    )
    store.record_session_ended(
        session_id="s1",
        reason="secret=abc",
        client_event="tool trace",
        public_summary={
            "turn_count": 1,
            "summary_document": {
                "relative_path": "summaries/s1.md",
                "created": True,
                "error": "secret=abc",
                "diagnostics": "internal",
            },
            "oracle": "never public",
        },
    )

    with sqlite3.connect(tmp_path / "serving.sqlite") as connection:
        summary_json = connection.execute(
            "SELECT public_summary_json FROM serving_request_summaries WHERE request_id = 'req-1'"
        ).fetchone()[0]
    assert json.loads(summary_json) == {
        "http_request_id": "http-1",
        "retrieval_summary": {"target_pool_size": 500, "path_count": 2},
    }
    assert json.loads(summary_json)["http_request_id"] == "http-1"
    persisted_text = (tmp_path / "events.jsonl").read_text(encoding="utf-8").lower()
    _assert_public_safe(summary_json.lower())
    _assert_public_safe(persisted_text)


def test_retention_policy_documents_trial_windows() -> None:
    assert RETENTION_DAYS == {
        "session_public_timeline": 7,
        "request_log": 14,
        "feedback_comment": 90,
        "simulation_namespace": 7,
    }


def test_cleanup_expired_public_records_uses_trial_retention_windows(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "serving.sqlite"
    store = SQLiteJsonlServingPersistenceStore(sqlite_path, tmp_path / "events.jsonl")
    now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
    display = _display_payload("Safe public explanation")

    store.record_turn_committed(
        session_id="old-session",
        user_id="u1",
        turn_index=1,
        event_type="chat",
        user_message="old",
        assistant_message="old",
        display=display,
    )
    store.record_turn_committed(
        session_id="fresh-session",
        user_id="u1",
        turn_index=1,
        event_type="chat",
        user_message="fresh",
        assistant_message="fresh",
        display=display,
    )
    store.record_feedback_event(session_id="fresh-session", turn_index=1, action_type="why", comment="old feedback")
    store.record_request_summary(request_id="old-request", endpoint="recommend", user_id="u1")
    store.record_request_summary(request_id="fresh-request", endpoint="recommend", user_id="u1")

    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("UPDATE serving_sessions SET updated_at = ? WHERE session_id = 'old-session'", ("2026-06-12T11:59:59+00:00",))
        connection.execute("UPDATE serving_turns SET created_at = ? WHERE session_id = 'old-session'", ("2026-06-12T11:59:59+00:00",))
        connection.execute("UPDATE serving_feedback_events SET created_at = ?", ("2026-03-21T11:59:59+00:00",))
        connection.execute("UPDATE serving_request_summaries SET created_at = ? WHERE request_id = 'old-request'", ("2026-06-06T11:59:59+00:00",))

    counts = store.cleanup_expired_public_records(now=now)

    assert counts == {"sessions": 1, "turns": 1, "feedback_events": 1, "request_summaries": 1}
    with sqlite3.connect(sqlite_path) as connection:
        assert connection.execute("SELECT session_id FROM serving_sessions").fetchall() == [("fresh-session",)]
        assert connection.execute("SELECT request_id FROM serving_request_summaries").fetchall() == [("fresh-request",)]
        assert connection.execute("SELECT COUNT(*) FROM serving_feedback_events").fetchone()[0] == 0
    events_text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "cleanup_expired_public_records" in events_text


def _display_payload(message: str) -> dict[str, object]:
    return {
        "schema_version": "rs_agent_display_v1",
        "session_id": "s1",
        "user_id": "u1",
        "turn_index": 1,
        "assistant_message": message,
        "items": [],
        "feedback_actions": [{"type": "why", "label": "为什么推荐"}],
        "ui_state": {"image_fallback_enabled": True, "can_request_more": True},
    }


def _assert_public_safe(serialized: str) -> None:
    for term in FORBIDDEN_PUBLIC_TERMS:
        assert term not in serialized
