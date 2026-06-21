from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from rs_core.display import (
    DEFAULT_PUBLIC_COMMENT_MAX_CHARS,
    sanitize_public_payload,
    sanitize_public_text,
    validate_public_display_payload,
    validate_public_timeline_payload,
)

LOGGER = logging.getLogger(__name__)

PERSISTENCE_ENABLED_ENV = "RS_SERVING_PERSISTENCE_ENABLED"
SQLITE_PATH_ENV = "RS_SERVING_SQLITE_PATH"
JSONL_PATH_ENV = "RS_SERVING_JSONL_PATH"
PERSISTENCE_SCHEMA_VERSION = "serving_persistence_v1"
EVENT_SCHEMA_VERSION = "serving_persistence_event_v1"
_LOCAL_FALSE_VALUES = {"", "0", "false", "no", "off"}
RETENTION_DAYS = {
    "session_public_timeline": 7,
    "request_log": 14,
    "feedback_comment": 90,
    "simulation_namespace": 7,
}


class ServingPersistenceStore(Protocol):
    def record_session_started(self, *, session_id: str, user_id: str, request_id: str | None = None) -> None:
        ...

    def record_turn_committed(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_index: int,
        event_type: str,
        user_message: str,
        assistant_message: str,
        display: dict[str, Any],
        request_id: str | None = None,
    ) -> None:
        ...

    def record_feedback_event(
        self,
        *,
        session_id: str,
        turn_index: int,
        action_type: str,
        item_id: str | None = None,
        comment: str | None = None,
        request_id: str | None = None,
    ) -> None:
        ...

    def record_session_ended(
        self,
        *,
        session_id: str,
        reason: str,
        client_event: str | None = None,
        request_id: str | None = None,
        public_summary: dict[str, Any] | None = None,
    ) -> None:
        ...

    def record_request_summary(
        self,
        *,
        request_id: str,
        endpoint: str,
        user_id: str | None = None,
        item_count: int | None = None,
        candidate_count: int | None = None,
        fallback_used: bool | None = None,
        public_summary: dict[str, Any] | None = None,
    ) -> None:
        ...

    def load_public_session_export(self, session_id: str) -> dict[str, Any] | None:
        ...

    def cleanup_expired_public_records(self, *, now: datetime | None = None) -> dict[str, int]:
        ...


class NoopServingPersistenceStore:
    def record_session_started(self, **_: Any) -> None:
        return None

    def record_turn_committed(self, **_: Any) -> None:
        return None

    def record_feedback_event(self, **_: Any) -> None:
        return None

    def record_session_ended(self, **_: Any) -> None:
        return None

    def record_request_summary(self, **_: Any) -> None:
        return None

    def load_public_session_export(self, session_id: str) -> dict[str, Any] | None:
        return None

    def cleanup_expired_public_records(self, *, now: datetime | None = None) -> dict[str, int]:
        return _empty_cleanup_counts()


class SafeServingPersistenceStore:
    """Fail-open wrapper so persistence never breaks serving requests."""

    def __init__(self, inner: ServingPersistenceStore) -> None:
        self.inner = inner

    def record_session_started(self, **kwargs: Any) -> None:
        self._safe_call("record_session_started", kwargs)

    def record_turn_committed(self, **kwargs: Any) -> None:
        self._safe_call("record_turn_committed", kwargs)

    def record_feedback_event(self, **kwargs: Any) -> None:
        self._safe_call("record_feedback_event", kwargs)

    def record_session_ended(self, **kwargs: Any) -> None:
        self._safe_call("record_session_ended", kwargs)

    def record_request_summary(self, **kwargs: Any) -> None:
        self._safe_call("record_request_summary", kwargs)

    def load_public_session_export(self, session_id: str) -> dict[str, Any] | None:
        try:
            return self.inner.load_public_session_export(session_id)
        except Exception as exc:  # pragma: no cover - defensive guard for production I/O failures
            LOGGER.warning("serving persistence export fallback failed: %s", exc)
            return None

    def cleanup_expired_public_records(self, *, now: datetime | None = None) -> dict[str, int]:
        try:
            return self.inner.cleanup_expired_public_records(now=now)
        except Exception as exc:  # pragma: no cover - defensive guard for production I/O failures
            LOGGER.warning("serving persistence cleanup failed: %s", exc)
            return _empty_cleanup_counts()

    def _safe_call(self, method_name: str, kwargs: dict[str, Any]) -> None:
        try:
            getattr(self.inner, method_name)(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive guard for production I/O failures
            LOGGER.warning("serving persistence %s failed: %s", method_name, exc)


class SQLiteJsonlServingPersistenceStore:
    """SQLite query store plus append-only JSONL event log for public serving records."""

    def __init__(self, sqlite_path: str | Path, jsonl_path: str | Path | None = None) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.jsonl_path = Path(jsonl_path) if jsonl_path else None
        self._lock = threading.RLock()
        self._initialize()

    def record_session_started(self, *, session_id: str, user_id: str, request_id: str | None = None) -> None:
        created_at = _utc_now()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO serving_sessions(
                    session_id, user_id, created_at, updated_at, status, schema_version, turn_count, last_request_id
                ) VALUES (?, ?, ?, ?, 'active', ?, 0, ?)
                """,
                (session_id, user_id, created_at, created_at, PERSISTENCE_SCHEMA_VERSION, request_id),
            )
            connection.execute(
                """
                UPDATE serving_sessions
                SET user_id = ?, updated_at = ?, last_request_id = COALESCE(?, last_request_id)
                WHERE session_id = ?
                """,
                (user_id, created_at, request_id, session_id),
            )
        self._append_event({
            "event_type": "session_started",
            "session_id": session_id,
            "user_id": user_id,
            "request_id": request_id,
            "created_at": created_at,
        })

    def record_turn_committed(
        self,
        *,
        session_id: str,
        user_id: str,
        turn_index: int,
        event_type: str,
        user_message: str,
        assistant_message: str,
        display: dict[str, Any],
        request_id: str | None = None,
    ) -> None:
        safe_event_type = event_type if event_type in {"chat", "feedback", "turn"} else "turn"
        display_payload = validate_public_display_payload(dict(display))
        created_at = _utc_now()
        safe_user_message = sanitize_public_text(user_message).text
        safe_assistant_message = sanitize_public_text(assistant_message).text
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO serving_sessions(
                    session_id, user_id, created_at, updated_at, status, schema_version, turn_count, last_request_id
                ) VALUES (?, ?, ?, ?, 'active', ?, 0, ?)
                """,
                (session_id, user_id, created_at, created_at, PERSISTENCE_SCHEMA_VERSION, request_id),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO serving_turns(
                    session_id, turn_index, event_type, user_message, assistant_message, display_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn_index,
                    safe_event_type,
                    safe_user_message,
                    safe_assistant_message,
                    _json_dumps(display_payload),
                    created_at,
                ),
            )
            connection.execute(
                """
                UPDATE serving_sessions
                SET user_id = ?, updated_at = ?, turn_count = MAX(turn_count, ?), last_request_id = COALESCE(?, last_request_id)
                WHERE session_id = ?
                """,
                (user_id, created_at, turn_index, request_id, session_id),
            )
        self._append_event({
            "event_type": "turn_committed",
            "session_id": session_id,
            "user_id": user_id,
            "turn_index": turn_index,
            "public_event_type": safe_event_type,
            "request_id": request_id,
            "created_at": created_at,
        })

    def record_feedback_event(
        self,
        *,
        session_id: str,
        turn_index: int,
        action_type: str,
        item_id: str | None = None,
        comment: str | None = None,
        request_id: str | None = None,
    ) -> None:
        created_at = _utc_now()
        event_id = f"{session_id}:feedback:{turn_index}"
        safe_comment = sanitize_public_text(comment, max_chars=DEFAULT_PUBLIC_COMMENT_MAX_CHARS) if comment is not None else None
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO serving_feedback_events(
                    event_id, session_id, turn_index, action_type, item_id, comment, comment_truncated, comment_redacted, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    session_id,
                    turn_index,
                    action_type.strip().lower(),
                    item_id,
                    None if safe_comment is None else safe_comment.text,
                    0 if safe_comment is None else int(safe_comment.truncated),
                    0 if safe_comment is None else int(safe_comment.redacted),
                    created_at,
                ),
            )
        self._append_event({
            "event_type": "feedback_event",
            "event_id": event_id,
            "session_id": session_id,
            "turn_index": turn_index,
            "action_type": action_type.strip().lower(),
            "item_id": item_id,
            "request_id": request_id,
            "created_at": created_at,
        })

    def record_session_ended(
        self,
        *,
        session_id: str,
        reason: str,
        client_event: str | None = None,
        request_id: str | None = None,
        public_summary: dict[str, Any] | None = None,
    ) -> None:
        created_at = _utc_now()
        summary = _public_session_end_summary(public_summary or {})
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE serving_sessions
                SET status = 'ended', updated_at = ?, last_request_id = COALESCE(?, last_request_id)
                WHERE session_id = ?
                """,
                (created_at, request_id, session_id),
            )
        self._append_event({
            "event_type": "session_ended",
            "session_id": session_id,
            "reason": sanitize_public_text(reason).text,
            "client_event": None if client_event is None else sanitize_public_text(client_event).text,
            "request_id": request_id,
            "public_summary": summary,
            "created_at": created_at,
        })

    def record_request_summary(
        self,
        *,
        request_id: str,
        endpoint: str,
        user_id: str | None = None,
        item_count: int | None = None,
        candidate_count: int | None = None,
        fallback_used: bool | None = None,
        public_summary: dict[str, Any] | None = None,
    ) -> None:
        created_at = _utc_now()
        summary = _public_request_summary(public_summary or {})
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO serving_request_summaries(
                    request_id, endpoint, user_id, item_count, candidate_count, fallback_used, created_at, public_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    endpoint,
                    user_id,
                    item_count,
                    candidate_count,
                    None if fallback_used is None else int(fallback_used),
                    created_at,
                    _json_dumps(summary),
                ),
            )
        self._append_event({
            "event_type": "request_summary",
            "request_id": request_id,
            "endpoint": endpoint,
            "user_id": user_id,
            "item_count": item_count,
            "candidate_count": candidate_count,
            "fallback_used": fallback_used,
            "created_at": created_at,
        })

    def load_public_session_export(self, session_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            session_row = connection.execute(
                """
                SELECT session_id, user_id, turn_count
                FROM serving_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if session_row is None:
                return None
            turn_rows = connection.execute(
                """
                SELECT turn_index, event_type, user_message, assistant_message, display_json
                FROM serving_turns
                WHERE session_id = ?
                ORDER BY turn_index ASC
                """,
                (session_id,),
            ).fetchall()
        display_responses = [validate_public_display_payload(json.loads(row[4])) for row in turn_rows]
        timeline_events = [
            {
                "public_event_id": f"{session_id}:turn:{int(row[0])}",
                "event_type": str(row[1]),
                "turn_index": int(row[0]),
                "user_message": str(row[2]),
                "assistant_message": str(row[3]),
                "display_response_index": index,
            }
            for index, row in enumerate(turn_rows)
        ]
        timeline = validate_public_timeline_payload({
            "schema_version": "rs_agent_public_timeline_v1",
            "session_id": str(session_row[0]),
            "user_id": str(session_row[1]),
            "events": timeline_events,
        })
        return {
            "session_id": str(session_row[0]),
            "user_id": str(session_row[1]),
            "turn_count": len(turn_rows),
            "public_timeline": timeline,
            "display_responses": display_responses,
        }

    def cleanup_expired_public_records(self, *, now: datetime | None = None) -> dict[str, int]:
        reference = now or datetime.now(timezone.utc)
        session_cutoff = _retention_cutoff(reference, "session_public_timeline")
        request_cutoff = _retention_cutoff(reference, "request_log")
        feedback_cutoff = _retention_cutoff(reference, "feedback_comment")
        counts = _empty_cleanup_counts()
        with self._lock, self._connect() as connection:
            expired_sessions = [
                row[0]
                for row in connection.execute(
                    "SELECT session_id FROM serving_sessions WHERE updated_at < ?",
                    (session_cutoff,),
                ).fetchall()
            ]
            if expired_sessions:
                placeholders = ",".join("?" for _ in expired_sessions)
                cursor = connection.execute(
                    f"DELETE FROM serving_turns WHERE session_id IN ({placeholders}) OR created_at < ?",
                    (*expired_sessions, session_cutoff),
                )
                counts["turns"] = cursor.rowcount if cursor.rowcount > 0 else 0
                cursor = connection.execute(
                    f"DELETE FROM serving_sessions WHERE session_id IN ({placeholders})",
                    tuple(expired_sessions),
                )
                counts["sessions"] = cursor.rowcount if cursor.rowcount > 0 else 0
            else:
                cursor = connection.execute("DELETE FROM serving_turns WHERE created_at < ?", (session_cutoff,))
                counts["turns"] = cursor.rowcount if cursor.rowcount > 0 else 0
            cursor = connection.execute("DELETE FROM serving_feedback_events WHERE created_at < ?", (feedback_cutoff,))
            counts["feedback_events"] = cursor.rowcount if cursor.rowcount > 0 else 0
            cursor = connection.execute("DELETE FROM serving_request_summaries WHERE created_at < ?", (request_cutoff,))
            counts["request_summaries"] = cursor.rowcount if cursor.rowcount > 0 else 0
        if any(counts.values()):
            self._append_event({"event_type": "cleanup_expired_public_records", "counts": counts, "created_at": _utc_now()})
        return counts

    def _initialize(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        if self.jsonl_path is not None:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA busy_timeout=1000;

                CREATE TABLE IF NOT EXISTS serving_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    schema_version TEXT NOT NULL,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    last_request_id TEXT
                );

                CREATE TABLE IF NOT EXISTS serving_turns (
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    assistant_message TEXT NOT NULL,
                    display_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, turn_index)
                );

                CREATE TABLE IF NOT EXISTS serving_feedback_events (
                    event_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    item_id TEXT,
                    comment TEXT,
                    comment_truncated INTEGER NOT NULL DEFAULT 0,
                    comment_redacted INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS serving_request_summaries (
                    request_id TEXT PRIMARY KEY,
                    endpoint TEXT NOT NULL,
                    user_id TEXT,
                    item_count INTEGER,
                    candidate_count INTEGER,
                    fallback_used INTEGER,
                    created_at TEXT NOT NULL,
                    public_summary_json TEXT NOT NULL
                );
                """
            )
            _ensure_column(connection, "serving_feedback_events", "comment_truncated", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(connection, "serving_feedback_events", "comment_redacted", "INTEGER NOT NULL DEFAULT 0")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path)
        connection.execute("PRAGMA busy_timeout=1000")
        return connection

    def _append_event(self, payload: dict[str, Any]) -> None:
        if self.jsonl_path is None:
            return
        record = {"schema_version": EVENT_SCHEMA_VERSION, **payload}
        with self._lock:
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(_json_dumps(record) + "\n")


def build_serving_persistence_store() -> ServingPersistenceStore:
    if os.environ.get(PERSISTENCE_ENABLED_ENV, "").strip().lower() in _LOCAL_FALSE_VALUES:
        return NoopServingPersistenceStore()
    sqlite_path = os.environ.get(SQLITE_PATH_ENV, "outputs/serving/serving_persistence.sqlite").strip()
    jsonl_path = os.environ.get(JSONL_PATH_ENV, "outputs/serving/serving_events.jsonl").strip() or None
    try:
        return SafeServingPersistenceStore(SQLiteJsonlServingPersistenceStore(sqlite_path, jsonl_path))
    except Exception as exc:  # pragma: no cover - depends on host filesystem permissions
        LOGGER.warning("serving persistence initialization failed; continuing without persistence: %s", exc)
        return NoopServingPersistenceStore()


def ensure_safe_persistence_store(store: ServingPersistenceStore | None) -> ServingPersistenceStore:
    if store is None:
        return build_serving_persistence_store()
    if isinstance(store, (NoopServingPersistenceStore, SafeServingPersistenceStore)):
        return store
    return SafeServingPersistenceStore(store)


def _public_session_end_summary(payload: dict[str, Any]) -> dict[str, Any]:
    safe_payload = sanitize_public_payload(payload)
    if not isinstance(safe_payload, dict):
        return {}
    summary: dict[str, Any] = {}
    document = safe_payload.get("summary_document")
    if isinstance(document, dict):
        summary["summary_document"] = sanitize_public_payload(
            {
                "relative_path": document.get("relative_path"),
                "created": bool(document.get("created")),
                "error": document.get("error"),
            }
        )
    turn_count = safe_payload.get("turn_count")
    if turn_count is not None:
        summary["turn_count"] = int(turn_count)
    return summary


def _public_request_summary(payload: dict[str, Any]) -> dict[str, Any]:
    safe_payload = sanitize_public_payload(payload)
    if not isinstance(safe_payload, dict):
        return {}
    summary: dict[str, Any] = {}
    http_request_id = safe_payload.get("http_request_id")
    if http_request_id:
        summary["http_request_id"] = str(http_request_id)
    retrieval_summary = safe_payload.get("retrieval_summary")
    if isinstance(retrieval_summary, dict):
        summary["retrieval_summary"] = {
            key: retrieval_summary.get(key)
            for key in ("target_pool_size", "path_count")
            if retrieval_summary.get(key) is not None
        }
    return summary


def _empty_cleanup_counts() -> dict[str, int]:
    return {"sessions": 0, "turns": 0, "feedback_events": 0, "request_summaries": 0}


def _ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


def _retention_cutoff(reference: datetime, policy_key: str) -> str:
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (reference.astimezone(timezone.utc) - timedelta(days=RETENTION_DAYS[policy_key])).isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
