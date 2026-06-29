from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import rs_core.serving.api.app as serving_app
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.persistence import SQLiteJsonlServingPersistenceStore
from rs_core.serving.session_summary import FakeLLMSessionSummaryService
from tests.services.test_serving_smoke import _write_serving_fixture

pytestmark = [pytest.mark.serving, pytest.mark.smoke]

BLOCKED_PERSISTED_TERMS = {
    "agent_tool_trace",
    "diagnostics",
    "long_memory",
    "rag_context",
    "runtime_trace",
    "score_trace",
    "source_scores",
    "tool_traces",
    "user_profile",
}


@pytest.fixture()
def persisted_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _write_persistence_fixture(tmp_path)
    store = SQLiteJsonlServingPersistenceStore(
        tmp_path / "serving.sqlite",
        tmp_path / "serving_events.jsonl",
    )
    service = RecommendationService(str(config), limit_users=1, persistence_store=store)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)
    with TestClient(serving_app.app) as test_client:
        yield service, test_client, tmp_path / "serving.sqlite", tmp_path / "serving_events.jsonl"


def test_persistence_records_session_chat_feedback_public_rows(persisted_service) -> None:
    service, client, sqlite_path, jsonl_path = persisted_service

    start = client.post("/session/start", json={"user_id": "u1"}, headers={"X-Request-ID": "req-start"})
    session_id = start.json()["session_id"]
    chat = client.post(
        "/chat",
        json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"},
        headers={"X-Request-ID": "req-chat"},
    ).json()
    feedback = client.post(
        "/feedback",
        json={"session_id": session_id, "action_type": "why", "item_id": "speaker_1", "comment": "Need a short explanation."},
        headers={"X-Request-ID": "req-feedback"},
    ).json()

    with sqlite3.connect(sqlite_path) as connection:
        session_row = connection.execute(
            "SELECT user_id, turn_count, last_request_id FROM serving_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        turns = connection.execute(
            "SELECT turn_index, event_type, display_json FROM serving_turns WHERE session_id = ? ORDER BY turn_index",
            (session_id,),
        ).fetchall()
        feedback_rows = connection.execute(
            "SELECT action_type, item_id, comment FROM serving_feedback_events WHERE session_id = ?",
            (session_id,),
        ).fetchall()

    assert session_row == ("u1", 2, "req-feedback")
    assert [(row[0], row[1]) for row in turns] == [(1, "chat"), (2, "feedback")]
    assert json.loads(turns[0][2]) == chat["display"]
    assert json.loads(turns[1][2]) == feedback["display"]
    assert feedback_rows == [("why", "speaker_1", "Need a short explanation.")]

    persisted_text = jsonl_path.read_text(encoding="utf-8").lower()
    assert "session_started" in persisted_text
    assert "turn_committed" in persisted_text
    assert "feedback_event" in persisted_text
    _assert_no_blocked_terms(persisted_text)
    _assert_sqlite_has_no_blocked_terms(sqlite_path)
    assert service.export_session(session_id)["display_responses"] == [chat["display"], feedback["display"]]


def test_session_end_records_status_event_and_fake_llm_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_persistence_fixture(tmp_path / "fixture")
    sqlite_path = tmp_path / "serving.sqlite"
    jsonl_path = tmp_path / "serving_events.jsonl"
    summary_dir = tmp_path / "summaries"
    store = SQLiteJsonlServingPersistenceStore(sqlite_path, jsonl_path)
    summary_service = FakeLLMSessionSummaryService(
        summary_dir,
        markdown="# 会话总结\n\n## 本次用户目标\n\n用户想找通勤蓝牙音频商品。\n",
    )
    service = RecommendationService(
        str(config),
        limit_users=1,
        persistence_store=store,
        session_summary_service=summary_service,
    )
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as client:
        session_id = client.post("/session/start", json={"user_id": "u1"}, headers={"X-Request-ID": "req-start"}).json()["session_id"]
        client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"})
        response = client.post(
            "/session/end",
            json={"session_id": session_id, "reason": "manual", "client_event": "manual", "write_summary": True},
            headers={"X-Request-ID": "req-end"},
        )
        second_response = client.post(
            "/session/end",
            json={"session_id": session_id, "reason": "manual", "client_event": "manual", "write_summary": False},
            headers={"X-Request-ID": "req-end-2"},
        )
        export = client.get(f"/session/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "ended"
    assert payload["turn_count"] == 1
    assert payload["summary_document"]["created"] is True
    assert payload["summary_document"]["relative_path"].endswith(f"{session_id}.md")
    assert second_response.status_code == 200
    assert second_response.json()["summary_document"] is None
    assert export.status_code == 200
    assert export.json()["turn_count"] == 1
    assert len(summary_service.calls) == 1
    assert set(summary_service.calls[0]["public_export"]) == {"session_id", "user_id", "turn_count", "public_timeline", "display_responses"}
    assert summary_service.calls[0]["reason"] == "manual"
    assert summary_service.calls[0]["request_id"] == "req-end"
    assert (summary_dir / f"{session_id}.md").exists()

    with sqlite3.connect(sqlite_path) as connection:
        status, last_request_id = connection.execute(
            "SELECT status, last_request_id FROM serving_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    assert status == "ended"
    assert last_request_id == "req-end-2"

    events = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    ended_events = [event for event in events if event.get("event_type") == "session_ended"]
    assert len(ended_events) == 2
    assert ended_events[0]["reason"] == "manual"
    assert ended_events[0]["public_summary"] == {
        "turn_count": 1,
        "summary_document": payload["summary_document"],
    }
    persisted_text = json.dumps(events, ensure_ascii=False).lower()
    _assert_no_blocked_terms(persisted_text)
    _assert_sqlite_has_no_blocked_terms(sqlite_path)


def test_export_falls_back_to_persisted_public_session_after_memory_clear(persisted_service) -> None:
    service, client, _, _ = persisted_service
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    chat = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"}).json()

    service.sessions.clear()
    service.session_events.clear()
    response = client.get(f"/session/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "session_id": session_id,
        "user_id": "u1",
        "turn_count": 1,
        "public_timeline": {
            "schema_version": "rs_agent_public_timeline_v1",
            "session_id": session_id,
            "user_id": "u1",
            "events": [
                {
                    "public_event_id": f"{session_id}:turn:1",
                    "event_type": "chat",
                    "turn_index": 1,
                    "user_message": "For commute, prefer bluetooth and Audio",
                    "assistant_message": chat["display"]["assistant_message"],
                    "display_response_index": 0,
                }
            ],
        },
        "display_responses": [chat["display"]],
    }
    _assert_no_blocked_terms(json.dumps(payload, ensure_ascii=False).lower())


def test_request_summaries_record_recommend_and_recall_public_contracts(persisted_service) -> None:
    _, client, sqlite_path, _ = persisted_service

    recommend = client.post(
        "/recommend",
        json={
            "user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"], "recent_positive_item_sequence": ["seed_audio"]},
            "top_k": 2,
        },
        headers={"X-Request-ID": "req-recommend"},
    )
    recall = client.post(
        "/recall",
        json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}},
        headers={"X-Request-ID": "req-recall"},
    )

    assert recommend.status_code == 200
    assert recall.status_code == 200
    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute(
            "SELECT request_id, endpoint, user_id, item_count, candidate_count, fallback_used, public_summary_json "
            "FROM serving_request_summaries ORDER BY endpoint"
        ).fetchall()

    assert [row[1] for row in rows] == ["recall", "recommend"]
    recall_row, recommend_row = rows
    assert recall_row[0] == recall.json()["request_id"]
    assert recall_row[2] == "online-u1"
    assert recall_row[3] is None
    assert recall_row[4] == recall.json()["candidate_count"]
    assert json.loads(recall_row[6]) == {
        "http_request_id": "req-recall",
        "retrieval_summary": {key: value for key, value in recall.json()["retrieval_summary"].items() if value is not None},
    }
    assert recommend_row[0] == recommend.json()["request_id"]
    assert recommend_row[2] == "online-u1"
    assert recommend_row[3] == recommend.json()["item_count"]
    assert recommend_row[4] == recommend.json()["candidate_count"]
    assert recommend_row[5] in (0, 1)
    assert json.loads(recommend_row[6]) == {"http_request_id": "req-recommend"}
    _assert_no_blocked_terms(json.dumps([tuple(row) for row in rows], ensure_ascii=False).lower())


def test_persistence_failure_does_not_break_public_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_persistence_fixture(tmp_path)
    service = RecommendationService(str(config), limit_users=1, persistence_store=ExplodingPersistenceStore())
    monkeypatch.setattr(serving_app, "get_service", lambda: service)

    with TestClient(serving_app.app) as client:
        start = client.post("/session/start", json={"user_id": "u1"})
        session_id = start.json()["session_id"]
        chat = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"})
        feedback = client.post("/feedback", json={"session_id": session_id, "action_type": "like", "item_id": "speaker_1"})
        export = client.get(f"/session/{session_id}")
        recommend = client.post("/recommend", json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}})
        recall = client.post("/recall", json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}})

    assert start.status_code == 200
    assert chat.status_code == 200
    assert feedback.status_code == 200
    assert export.status_code == 200
    assert recommend.status_code == 200
    assert recall.status_code == 200
    assert "persistence" not in json.dumps(chat.json()).lower()
    assert "persistence" not in json.dumps(recommend.json()).lower()


def test_strict_auth_rejects_before_persistence_or_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get_service():
        raise AssertionError("unauthorized request must not instantiate service or persistence")

    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setattr(serving_app, "get_service", fail_get_service)
    with TestClient(serving_app.app) as client:
        response = client.post("/session/start", json={"user_id": "u1"})

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "AUTH_REQUIRED", "message": "Trial token required"}


def test_strict_auth_trial_token_cannot_persist_recall_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _write_persistence_fixture(tmp_path / "fixture")
    sqlite_path = tmp_path / "serving.sqlite"
    jsonl_path = tmp_path / "serving_events.jsonl"
    store = SQLiteJsonlServingPersistenceStore(sqlite_path, jsonl_path)
    service = RecommendationService(str(config), limit_users=1, persistence_store=store)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setenv("RS_DEBUG_TOKEN", "debug-secret")

    with TestClient(serving_app.app) as client:
        trial_response = client.post(
            "/recall",
            json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}},
            headers={"Authorization": "Bearer trial-secret"},
        )
        debug_response = client.post(
            "/recall",
            json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}},
            headers={"Authorization": "Bearer debug-secret", "X-Request-ID": "req-debug-recall"},
        )

    assert trial_response.status_code == 403
    assert debug_response.status_code == 200
    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute("SELECT endpoint, public_summary_json FROM serving_request_summaries").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "recall"
    summary = json.loads(rows[0][1])
    assert summary["http_request_id"] == "req-debug-recall"
    assert summary["retrieval_summary"] == {
        key: value for key, value in debug_response.json()["retrieval_summary"].items() if value is not None
    }
    assert "trial-secret" not in jsonl_path.read_text(encoding="utf-8")


def test_generated_request_id_is_persisted_for_missing_or_invalid_header(persisted_service) -> None:
    _, client, sqlite_path, _ = persisted_service

    start = client.post("/session/start", json={"user_id": "u1"})
    session_id = start.json()["session_id"]
    chat = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"}, headers={"X-Request-ID": "bad id"})
    recommend = client.post("/recommend", json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}})

    assert start.headers["X-Request-ID"]
    assert chat.headers["X-Request-ID"] != "bad id"
    assert recommend.headers["X-Request-ID"]
    with sqlite3.connect(sqlite_path) as connection:
        last_request_id = connection.execute("SELECT last_request_id FROM serving_sessions WHERE session_id = ?", (session_id,)).fetchone()[0]
        recommend_summary = connection.execute("SELECT public_summary_json FROM serving_request_summaries WHERE endpoint = 'recommend'").fetchone()[0]
    assert last_request_id == chat.headers["X-Request-ID"]
    assert json.loads(recommend_summary)["http_request_id"] == recommend.headers["X-Request-ID"]


def test_build_store_fails_open_when_sqlite_initialization_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from rs_core.serving.persistence import NoopServingPersistenceStore, build_serving_persistence_store

    monkeypatch.setenv("RS_SERVING_PERSISTENCE_ENABLED", "1")
    monkeypatch.setenv("RS_SERVING_SQLITE_PATH", "")

    store = build_serving_persistence_store()

    assert isinstance(store, NoopServingPersistenceStore)


class ExplodingPersistenceStore:
    def record_session_started(self, **_: Any) -> None:
        raise RuntimeError("boom")

    def record_turn_committed(self, **_: Any) -> None:
        raise RuntimeError("boom")

    def record_feedback_event(self, **_: Any) -> None:
        raise RuntimeError("boom")

    def record_request_summary(self, **_: Any) -> None:
        raise RuntimeError("boom")

    def record_session_ended(self, **_: Any) -> None:
        raise RuntimeError("boom")

    def load_public_session_export(self, session_id: str) -> dict[str, Any] | None:
        raise RuntimeError("boom")


def _assert_no_blocked_terms(serialized: str) -> None:
    for term in BLOCKED_PERSISTED_TERMS:
        assert term not in serialized


def _assert_sqlite_has_no_blocked_terms(sqlite_path: Path) -> None:
    with sqlite3.connect(sqlite_path) as connection:
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'serving_%'"
        ).fetchall()
        for (table_name,) in table_rows:
            columns = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
            text_columns = [row[1] for row in columns if str(row[2]).upper() == "TEXT"]
            if not text_columns:
                continue
            selected = ", ".join(text_columns)
            for row in connection.execute(f"SELECT {selected} FROM {table_name}").fetchall():
                _assert_no_blocked_terms(json.dumps(row, ensure_ascii=False).lower())


def _write_persistence_fixture(root: Path) -> Path:
    root.mkdir(exist_ok=True)
    return _write_serving_fixture(root)
