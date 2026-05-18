from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.serving, pytest.mark.smoke]

from rs_core.common.io import write_jsonl
from rs_core.serving import app as serving_app
from rs_core.serving.service import RecommendationService

BLOCKED_PUBLIC_KEYS = {
    "ranking",
    "diagnostics",
    "reward",
    "reward_evidence",
    "score",
    "base_score",
    "agent_boost",
    "coarse_score",
    "fine_score",
    "rerank_score",
    "final_score",
    "score_trace",
    "rank_movement",
    "training_samples",
    "tool_events",
    "constraint_filter_events",
    "scorecard",
    "judge_scores",
}
BLOCKED_PUBLIC_TERMS = {
    "agent_boost",
    "base_score",
    "coarse_score",
    "diagnostic",
    "constraint_filter",
    "feedback_source",
    "fine_score",
    "final_score",
    "hybrid recall",
    "itemcf",
    "rank_weights",
    "ranked highest",
    "ranking",
    "rank_movement",
    "recall source",
    "rerank_score",
    "score_trace",
    "reward",
    "reward_evidence",
    "scorecard",
    "source",
    "training",
    "training_samples",
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _write_serving_fixture(tmp_path)
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)
    with TestClient(serving_app.app) as test_client:
        yield test_client


def test_health_returns_demo_mode(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "rs-agent-serving",
        "mode": "single-process-demo",
    }


def test_start_session_uses_unique_uuid_per_user(client: TestClient):
    first = client.post("/session/start", json={"user_id": "u1"}).json()
    second = client.post("/session/start", json={"user_id": "u1"}).json()

    assert first["session_id"] != second["session_id"]
    assert _is_uuid(first["session_id"])
    assert _is_uuid(second["session_id"])


def test_chat_returns_display_response_without_internal_fields(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]

    response = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    display = payload["display"]
    assert display["session_id"] == session_id
    assert display["schema_version"] == "rs_agent_display_v1"
    assert display["items"]
    assert display["items"][0]["parent_asin"] == "speaker_1"
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_fixed_smoke_user_returns_public_display_items_without_recovery_diagnostics(tmp_path: Path):
    config_path = _write_serving_fixture(tmp_path)
    service = RecommendationService(str(config_path))
    session_id = service.start_session("u1")

    result = service.chat(session_id, "For commute, prefer bluetooth and Audio")

    assert result.display["session_id"] == session_id
    assert result.display["schema_version"] == "rs_agent_display_v1"
    assert result.display["items"]
    _assert_no_blocked_keys(result.display)
    _assert_no_blocked_public_terms(result.display)


def test_repeated_user_sessions_do_not_conflict(client: TestClient):
    first_session = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    second_session = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]

    first = client.post("/chat", json={"session_id": first_session, "message": "For commute, prefer bluetooth and Audio"}).json()
    second = client.post("/chat", json={"session_id": second_session, "message": "why?"}).json()

    assert first["display"]["session_id"] == first_session
    assert second["display"]["session_id"] == second_session
    assert second["display"]["items"] == []


def test_unknown_session_returns_stable_404_error(client: TestClient):
    response = client.post("/chat", json={"session_id": "missing-session", "message": "hello"})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "SESSION_NOT_FOUND", "message": "Unknown session_id"}}


def test_feedback_show_different_returns_display_response(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    first = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"}).json()

    response = client.post("/feedback", json={"session_id": session_id, "action_type": "show_different", "item_id": "speaker_1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["display"]["schema_version"] == "rs_agent_display_v1"
    assert payload["display"]["session_id"] == session_id
    assert payload["display"]["items"] != first["display"]["items"]
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_feedback_why_can_return_dialogue_only_display(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"})

    response = client.post("/feedback", json={"session_id": session_id, "action_type": "why"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["display"]["items"] == []
    assert "speaker_1" in payload["display"]["assistant_message"]
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_feedback_why_explains_requested_latest_item(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    recommendation = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"}).json()
    item = recommendation["display"]["items"][0]

    response = client.post("/feedback", json={"session_id": session_id, "action_type": "why", "item_id": item["parent_asin"]})

    assert response.status_code == 200
    payload = response.json()
    assert payload["display"]["items"] == []
    assert item["parent_asin"] in payload["display"]["assistant_message"]
    assert payload["display"]["assistant_message"] != "我只能解释最近一次推荐列表里的商品。"
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_feedback_why_rejects_stale_item_with_exact_public_text(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"})

    response = client.post("/feedback", json={"session_id": session_id, "action_type": "why", "item_id": "stale_item_1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["display"]["assistant_message"] == "我只能解释最近一次推荐列表里的商品。"
    assert payload["display"]["items"] == []
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_feedback_why_without_prior_recommendation_returns_exact_public_text(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]

    response = client.post("/feedback", json={"session_id": session_id, "action_type": "why"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["display"]["assistant_message"] == "我现在还没有可以解释的最近推荐。你可以先让我推荐一些商品，然后再问为什么推荐其中某一件。"
    assert payload["display"]["items"] == []
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_feedback_rejects_unknown_action_type(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]

    response = client.post("/feedback", json={"session_id": session_id, "action_type": "bookmark"})

    assert response.status_code == 422
    assert "Unsupported feedback action_type" in response.json()["detail"]


def test_feedback_unknown_session_returns_stable_404_error(client: TestClient):
    response = client.post("/feedback", json={"session_id": "missing-session", "action_type": "why"})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "SESSION_NOT_FOUND", "message": "Unknown session_id"}}


def test_demo_roundtrip_returns_two_safe_display_responses(client: TestClient):
    response = client.post("/demo/e2e", json={
        "user_id": "u1",
        "message": "For commute, prefer bluetooth and Audio",
        "feedback_action": "show_different",
    })

    assert response.status_code == 200
    payload = response.json()
    assert _is_uuid(payload["session_id"])
    first_display = payload["first_display"]
    feedback_display = payload["feedback_display"]
    assert first_display["schema_version"] == "rs_agent_display_v1"
    assert feedback_display["schema_version"] == "rs_agent_display_v1"
    assert first_display["session_id"] == payload["session_id"]
    assert feedback_display["session_id"] == payload["session_id"]
    assert first_display["turn_index"] == 1
    assert feedback_display["turn_index"] == 2
    assert first_display["items"]
    assert payload["change_summary"]["changed"] is True
    assert payload["change_summary"]["first_item_ids"] != payload["change_summary"]["feedback_item_ids"]
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_demo_roundtrip_rejects_unknown_feedback_action(client: TestClient):
    response = client.post("/demo/e2e", json={
        "user_id": "u1",
        "message": "For commute, prefer bluetooth and Audio",
        "feedback_action": "bookmark",
    })

    assert response.status_code == 422
    assert "Unsupported feedback action_type" in response.json()["detail"]


def test_session_export_returns_safe_turn_history(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    chat = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"}).json()
    feedback = client.post("/feedback", json={
        "session_id": session_id,
        "action_type": "why",
        "item_id": "speaker_1",
        "comment": "Need a short explanation.",
    }).json()

    response = client.get(f"/session/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["user_id"] == "u1"
    assert payload["turn_count"] == 2
    assert payload["public_timeline"] == {
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
            },
            {
                "public_event_id": f"{session_id}:turn:2",
                "event_type": "feedback",
                "turn_index": 2,
                "user_message": "why? item_id=speaker_1 Need a short explanation.",
                "assistant_message": feedback["display"]["assistant_message"],
                "display_response_index": 1,
            },
        ],
    }
    assert payload["display_responses"] == [chat["display"], feedback["display"]]
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_session_export_unknown_session_returns_stable_404_error(client: TestClient):
    response = client.get("/session/missing-session")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "SESSION_NOT_FOUND", "message": "Unknown session_id"}}


def _assert_no_blocked_keys(value):
    if isinstance(value, dict):
        assert not BLOCKED_PUBLIC_KEYS & set(value)
        for child in value.values():
            _assert_no_blocked_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blocked_keys(child)


def _assert_no_blocked_public_terms(value):
    if isinstance(value, dict):
        for child in value.values():
            _assert_no_blocked_public_terms(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_blocked_public_terms(child)
    elif isinstance(value, str):
        lowered = value.lower()
        for term in BLOCKED_PUBLIC_TERMS:
            assert term not in lowered


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _write_serving_fixture(root: Path) -> Path:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{
        "user_id": "u1",
        "recent_item_sequence": ["seed_audio"],
        "recent_positive_item_sequence": ["seed_audio"],
        "recent_strong_positive_item_sequence": [],
    }])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "speaker_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [
        {"parent_asin": "charger_1", "category": "Accessories", "pop_score": 5},
    ])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [
        {"src_item": "seed_audio", "dst_item": "speaker_1", "score": 2.0, "category": "Audio", "title_clean": "Bluetooth speaker for commute"},
    ])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [
        {"parent_asin": "seed_audio", "main_category": "Audio"},
        {"parent_asin": "speaker_1", "main_category": "Audio"},
    ])
    write_jsonl(views / "category_top_items.jsonl", [{"bucket": "main::Audio", "top_items": [
        {"parent_asin": "earbuds_1", "score": 1.0, "category": "Audio", "title_clean": "Wireless bluetooth earbuds"},
    ]}])
    config = root / "config.yaml"
    config.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "output_dir": str(root / "out"),
        "report_path": str(root / "report.md"),
        "top_k": 3,
        "candidate_pool_size": 10,
        "popular_fallback_count": 3,
        "rank_weights": {
            "popular": 1.0,
            "itemcf_weak": 1.0,
            "category": 1.0,
            "feedback_category": 10.0,
            "feedback_keyword": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_keyword_boost": 1.0,
    }), encoding="utf-8")
    return config
