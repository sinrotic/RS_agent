from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.unit, pytest.mark.smoke]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_DEPENDENCY_PATHS = (
    PROJECT_ROOT / "rs_core" / "serving" / "runtime" / "split_engines.py",
)


class _FakeRecommender:
    def __init__(self) -> None:
        self.recall_calls: list[dict[str, Any]] = []

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "service": "fake-online-runtime",
            "mode": "test-bound",
            "session_state": "fake",
        }

    def recall(self, request: dict[str, Any]) -> dict[str, Any]:
        self.recall_calls.append(request)
        return {
            "request_id": "fake-recall-request",
            "candidate_item_ids": ["i2", "i1"],
            "candidate_count": 2,
            "retrieval_summary": {"target_pool_size": request.get("candidate_pool_size"), "path_count": 1},
        }

    def recommend(self, user_sequence: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {
            "request_id": "fake-recommend-request",
            "display": {"assistant_message": "bound online recommender", "items": [{"parent_asin": "i1"}]},
            "items": [{"parent_asin": "i1"}],
            "item_count": 1,
            "candidate_count": 1,
            "fallback_used": False,
            "ranking_trace": {"route": "bound_fake_recommender", "user_sequence_size": len(user_sequence)},
            "top_k": kwargs.get("top_k"),
        }

    def tool_retrieve_candidates(
        self,
        user_sequence: dict[str, Any],
        *,
        prior_turn_items: set[str] | None = None,
        candidate_pool_size: int | None = None,
        retrieve_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.recall_calls.append({
            "user_sequence": user_sequence,
            "prior_turn_items": sorted(prior_turn_items or set()),
            "candidate_pool_size": candidate_pool_size,
            "retrieve_policy": retrieve_policy,
        })
        return {
            "candidate_item_ids": ["i2", "i1"],
            "candidate_count": 2,
            "retrieval_summary": {"target_pool_size": candidate_pool_size, "path_count": 1},
            "diagnostics": {"route": "fake_tool_retrieve_candidates"},
        }


class _FakeRecommendationService:
    def __init__(self) -> None:
        self.online_recommender = _FakeRecommender()

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "service": "fake-agent-service",
            "mode": "test-bound",
            "session_state": "fake",
            "online_route": {"status": "ready"},
        }

    def start_session(self, user_id: str | None = None, request_id: str | None = None) -> str:
        return user_id or request_id or "fake-session"

    def chat(self, session_id: str, message: str, request_id: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            session_id=session_id,
            display={"assistant_message": f"bound chat: {message}", "items": [{"parent_asin": "i1"}]},
        )

    def feedback(
        self,
        session_id: str,
        action_type: str,
        item_id: str | None = None,
        comment: str | None = None,
        request_id: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            session_id=session_id,
            display={"assistant_message": f"bound feedback: {action_type}", "items": [{"parent_asin": item_id or "i1"}]},
        )

    def end_session(
        self,
        session_id: str,
        reason: str = "unknown",
        client_event: str | None = None,
        write_summary: bool = True,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return {"session_id": session_id, "status": "ended", "turn_count": 1, "summary_document": None}

    def export_session(self, session_id: str) -> dict[str, Any]:
        return {"session_id": session_id, "user_id": "u1", "turn_count": 1, "public_timeline": {}, "display_responses": []}


def test_runtime_exposes_provider_seam_without_secondary_root(monkeypatch: pytest.MonkeyPatch) -> None:
    import rs_core.serving.runtime.composition as runtime

    fake_service = _FakeRecommendationService()
    monkeypatch.setattr(runtime, "get_recommendation_service", lambda: fake_service)

    assert runtime.get_online_recommender() is fake_service.online_recommender
    assert runtime.get_agent_recommendation_service() is fake_service

    online_source = inspect.getsource(runtime.get_online_recommender)
    agent_source = inspect.getsource(runtime.get_agent_recommendation_service)
    assert "RecommendationService(" not in online_source
    assert "RecommendationService(" not in agent_source
    assert "get_recommendation_service()" in online_source
    assert "get_recommendation_service()" in agent_source


def test_split_service_dependencies_import_only_runtime_bridge() -> None:
    violations: list[str] = []
    for source_path in SERVICE_DEPENDENCY_PATHS:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "rs_core.serving.application.recommendation_service":
                violations.append(f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports RecommendationService directly")
            elif isinstance(node, ast.ImportFrom) and node.module == "rs_core.serving.runtime.composition":
                imported_members = {alias.name for alias in node.names}
                if imported_members != {"get_recommendation_service"}:
                    violations.append(
                        f"{source_path.relative_to(PROJECT_ROOT)}:{node.lineno} imports unexpected runtime members {sorted(imported_members)}"
                    )

    assert violations == []


def test_online_service_dependency_binds_real_composition_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    import rs_core.serving.runtime.split_engines as dependencies

    fake_service = _FakeRecommendationService()
    monkeypatch.setattr(dependencies, "get_recommendation_service", lambda: fake_service)
    dependencies.clear_online_engine_cache()
    try:
        engine = dependencies.get_online_engine()
    finally:
        dependencies.clear_online_engine_cache()

    assert engine.recommender is fake_service.online_recommender
    ready = engine.ready()
    assert ready["status"] == "ready"
    assert ready.get("reason") != "no_recommender_bound"


def test_agent_service_dependency_binds_real_composition_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    import rs_core.serving.runtime.split_engines as dependencies

    fake_service = _FakeRecommendationService()
    monkeypatch.setattr(dependencies, "get_recommendation_service", lambda: fake_service)
    dependencies.clear_agent_engine_cache()
    try:
        engine = dependencies.get_agent_engine()
    finally:
        dependencies.clear_agent_engine_cache()

    assert engine.service is fake_service
    ready = engine.ready()
    assert ready["status"] == "ready"
    assert ready.get("reason") != "no_service_bound"


def test_online_service_routes_do_not_use_unbound_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import rs_core.serving.runtime.split_engines as dependencies
    from rs_core.serving.api.online_app import create_app

    fake_service = _FakeRecommendationService()
    monkeypatch.setattr(dependencies, "get_recommendation_service", lambda: fake_service)
    dependencies.clear_online_engine_cache()
    app = create_app()
    try:
        with TestClient(app) as client:
            ready = client.get("/ready")
            response = client.post("/recommend", json={"user_sequence": {"recent_item_ids": ["i1"]}, "top_k": 1})
            recall = client.post("/recall", json={"user_sequence": {"recent_item_ids": ["i1"]}, "candidate_pool_size": 2})
    finally:
        dependencies.clear_online_engine_cache()

    assert ready.status_code == 200
    assert ready.json().get("reason") != "no_recommender_bound"
    assert response.status_code == 200
    body = response.json()
    assert body["ranking_trace"]["route"] != "unbound_fallback"
    assert body["display"]["assistant_message"] == "bound online recommender"
    assert recall.status_code == 200
    assert recall.json()["candidate_item_ids"] == ["i2", "i1"]
    assert fake_service.online_recommender.recall_calls == [
        {
            "user_id": None,
            "user_sequence": {"recent_item_ids": ["i1"]},
            "candidate_pool_size": 2,
            "prior_turn_items": [],
        }
    ]


def test_agent_service_routes_do_not_use_unbound_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import rs_core.serving.runtime.split_engines as dependencies
    from rs_core.serving.api.agent_app import create_app

    monkeypatch.setattr(dependencies, "get_recommendation_service", lambda: _FakeRecommendationService())
    dependencies.clear_agent_engine_cache()
    app = create_app()
    try:
        with TestClient(app) as client:
            ready = client.get("/ready")
            session = client.post("/session/start", json={"user_id": "u1"})
            chat = client.post("/chat", json={"session_id": "u1", "message": "想看新品"})
            feedback = client.post(
                "/feedback",
                json={"session_id": "u1", "action_type": "skip", "item_id": "i1", "comment": "smoke"},
            )
    finally:
        dependencies.clear_agent_engine_cache()

    assert ready.status_code == 200
    assert ready.json().get("reason") != "no_service_bound"
    assert session.json() == {"session_id": "u1"}
    assert chat.status_code == 200
    assert chat.json()["display"]["assistant_message"] == "bound chat: 想看新品"
    assert feedback.status_code == 200
    assert feedback.json()["display"]["assistant_message"] == "bound feedback: skip"


def test_agent_service_chat_stream_returns_sse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    import rs_core.serving.runtime.split_engines as dependencies
    from rs_core.serving.api.agent_app import create_app

    monkeypatch.setattr(dependencies, "get_recommendation_service", lambda: _FakeRecommendationService())
    dependencies.clear_agent_engine_cache()
    app = create_app()
    try:
        with TestClient(app) as client:
            response = client.post("/chat/stream", json={"session_id": "u1", "message": "hello"})
    finally:
        dependencies.clear_agent_engine_cache()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: token" in response.text
    assert '"delta":"bound chat: hello"' in response.text
    assert "event: done" in response.text
