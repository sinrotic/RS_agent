from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.serving, pytest.mark.smoke]

from rs_core.common.io import write_jsonl
from rs_core.agent.rag.semantic_description import build_sqlite_semantic_description_index
from rs_core.agent.tools import AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT
import rs_core.serving.api.app as serving_app
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.facades import FeedbackSessionFacade, RecommendationFacade, RecallFacade
from rs_core.serving.runtime.config import resolve_serving_config
from rs_core.serving.schemas import HomeFeedEventRequest, RecallRequest, RecommendFromSequenceRequest
from rs_core.workflow.hybrid_demo import run_hybrid_demo

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
    "tool_call",
    "tool_result",
    "agent_tool_trace",
    "agent_tool_events",
    "agent_tool_summary",
    "constraint_filter_events",
    "scorecard",
    "judge_scores",
}
BLOCKED_PUBLIC_TERMS = {
    "agent_boost",
    "base_score",
    "build_recommendation_slate",
    "coarse_score",
    "diagnostic",
    "agent_tool_trace",
    "catalog_constraint_search",
    "constraint_filter",
    "feedback_source",
    "fine_score",
    "final_score",
    "get_item_evidence",
    "get_user_context",
    "holdout",
    "hybrid recall",
    "itemcf",
    "label_binary",
    "match_specific_need_in_pool",
    "rank_candidates",
    "rank_weights",
    "ranked highest",
    "ranking",
    "rank_movement",
    "recall source",
    "record_user_feedback",
    "rerank_for_browsing",
    "rerank_score",
    "retrieve_candidates",
    "score_trace",
    "reward",
    "reward_evidence",
    "scorecard",
    "source",
    "training",
    "training_samples",
}
SERVING_GOVERNANCE = {
    "promotion_allowed": False,
    "pool1000_allowed": False,
    "ranking_input_replacement_allowed": False,
    "final_pool500_ready_claimed": False,
}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = _write_serving_fixture(tmp_path)
    service = RecommendationService(str(config), limit_users=1)
    monkeypatch.setattr(serving_app, "get_service", lambda: service)
    with TestClient(serving_app.app) as test_client:
        yield test_client


def test_health_returns_online_service_mode(client: TestClient):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "rs-agent-serving",
        "mode": "online-service",
        "session_state": "single_process_in_memory",
    }



def test_health_does_not_instantiate_service_or_readiness(monkeypatch: pytest.MonkeyPatch):
    def fail_get_service():
        raise AssertionError("/health must stay liveness-only")

    monkeypatch.setattr(serving_app, "get_service", fail_get_service)
    with TestClient(serving_app.app) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]



def test_request_id_header_preserves_valid_client_id(client: TestClient):
    response = client.post("/session/start", json={"user_id": "u1"}, headers={"X-Request-ID": "web-test-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "web-test-123"



def test_request_id_header_replaces_invalid_client_id(client: TestClient):
    response = client.post("/session/start", json={"user_id": "u1"}, headers={"X-Request-ID": "bad id with spaces"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] != "bad id with spaces"
    assert _is_uuid(response.headers["X-Request-ID"])



def test_strict_auth_rejects_trial_endpoint_without_token(monkeypatch: pytest.MonkeyPatch):
    def fail_get_service():
        raise AssertionError("unauthorized request must not instantiate service")

    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setattr(serving_app, "get_service", fail_get_service)
    with TestClient(serving_app.app) as test_client:
        response = test_client.post("/session/start", json={"user_id": "u1"})

    assert response.status_code == 401
    assert response.json()["detail"] == {"code": "AUTH_REQUIRED", "message": "Trial token required"}
    assert response.headers["X-Request-ID"]



def test_strict_auth_allows_trial_token_for_public_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")

    response = client.post("/session/start", json={"user_id": "u1"}, headers={"Authorization": "Bearer trial-secret"})

    assert response.status_code == 200
    assert response.json()["session_id"]



def test_strict_auth_recall_requires_debug_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setenv("RS_DEBUG_TOKEN", "debug-secret")

    trial_response = client.post(
        "/recall",
        json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}},
        headers={"Authorization": "Bearer trial-secret"},
    )
    debug_response = client.post(
        "/recall",
        json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}},
        headers={"Authorization": "Bearer debug-secret"},
    )

    assert trial_response.status_code == 403
    assert trial_response.json()["detail"] == {"code": "FORBIDDEN", "message": "Debug token required"}
    assert debug_response.status_code == 200
    assert set(debug_response.json()) == {"request_id", "candidate_item_ids", "candidate_count", "retrieval_summary"}



def test_demo_endpoint_can_be_disabled_by_env(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_ENABLE_DEMO_ENDPOINT", "0")

    response = client.post("/demo/e2e", json={"user_id": "u1", "message": "For commute, prefer bluetooth and Audio"})

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "FORBIDDEN", "message": "Demo endpoint disabled"}



def test_recall_endpoint_can_be_disabled_by_env(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_ENABLE_RECALL_ENDPOINT", "0")

    response = client.post("/recall", json={"user_sequence": {"user_id": "online-u1", "recent_item_sequence": ["seed_audio"]}})

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "FORBIDDEN", "message": "Recall endpoint disabled"}



def test_strict_auth_leaves_health_public(monkeypatch: pytest.MonkeyPatch):
    def fail_get_service():
        raise AssertionError("/health must stay liveness-only under strict auth")

    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setattr(serving_app, "get_service", fail_get_service)
    with TestClient(serving_app.app) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"



def test_strict_auth_simulation_requires_simulation_or_debug_token(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setenv("RS_SIMULATION_TOKEN", "simulation-secret")
    monkeypatch.setenv("RS_DEBUG_TOKEN", "debug-secret")

    trial_response = client.post(
        "/simulation/scene",
        json={"role_id": "commuter_practical", "max_turns": 1},
        headers={"Authorization": "Bearer trial-secret"},
    )
    simulation_response = client.post(
        "/simulation/scene",
        json={"role_id": "commuter_practical", "max_turns": 1},
        headers={"Authorization": "Bearer simulation-secret"},
    )
    debug_response = client.post(
        "/simulation/scene",
        json={"role_id": "commuter_practical", "max_turns": 1},
        headers={"Authorization": "Bearer debug-secret"},
    )

    assert trial_response.status_code == 403
    assert trial_response.json()["detail"] == {"code": "FORBIDDEN", "message": "Simulation token required"}
    assert simulation_response.status_code == 200
    assert debug_response.status_code == 200



def test_simulation_endpoint_can_be_disabled_by_env(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_ENABLE_SIMULATION_ENDPOINTS", "0")

    response = client.post("/simulation/scene", json={"role_id": "commuter_practical", "max_turns": 1})

    assert response.status_code == 403
    assert response.json()["detail"] == {"code": "FORBIDDEN", "message": "Simulation endpoints disabled"}



def test_default_online_service_config_resolution_is_not_cwd_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    resolved = Path(resolve_serving_config())

    assert resolved.is_absolute()
    assert resolved.name == "online_service.yaml"
    assert resolved.exists()



def test_ready_returns_coarse_public_readiness(client: TestClient):
    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["mode"] == "online-service"
    assert payload["session_state"] == "single_process_in_memory"
    assert payload["online_route"] == {
        "mode": "online-service",
        "session_state": "single_process_in_memory",
        "complete_pool500_available": True,
        "online_source_indexes_available": False,
        "source_index_available_count": 0,
        "source_index_configured_count": 0,
        "pool500_artifact": {"enabled": True, "status": "ready"},
    }
    assert set(payload["candidate_retrieval"]) == {
        "enabled",
        "available",
        "status",
        "configured_provider_count",
        "available_provider_count",
        "providers",
    }
    _assert_ready_no_internal_details(payload)


def test_ready_agent_provider_does_not_leak_secret_or_base_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RS_AGENT_OPENAI_COMPATIBLE_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("RS_AGENT_OPENAI_COMPATIBLE_API_KEY", "sk-secret-ready")
    monkeypatch.setenv("RS_AGENT_OPENAI_COMPATIBLE_MODEL", "qwen-secret-path")
    service = RecommendationService(
        str(_write_serving_fixture(tmp_path)),
        limit_users=1,
        config_overrides={
            "inference_policy": {
                "enabled": True,
                "provider": "openai_compatible",
                "openai_compatible": {
                    "api_base_env": "RS_AGENT_OPENAI_COMPATIBLE_BASE_URL",
                    "api_key_env": "RS_AGENT_OPENAI_COMPATIBLE_API_KEY",
                    "model_env": "RS_AGENT_OPENAI_COMPATIBLE_MODEL",
                    "probe_enabled": True,
                },
            }
        },
    )

    payload = service.readiness()

    assert payload["agent_provider"]["provider"] == "openai_compatible"
    assert payload["agent_provider"]["endpoint_configured"] is True
    assert payload["agent_provider"]["probe_enabled"] is True
    assert payload["agent_provider"]["probe_status"] == "not_run_by_readiness"
    serialized = json.dumps(payload)
    assert "sk-secret-ready" not in serialized
    assert "localhost" not in serialized
    assert "8000" not in serialized
    assert "qwen-secret-path" not in serialized


def test_start_session_uses_unique_uuid_per_user(client: TestClient):
    first = client.post("/session/start", json={"user_id": "u1"}).json()
    second = client.post("/session/start", json={"user_id": "u1"}).json()

    assert first["session_id"] != second["session_id"]
    assert _is_uuid(first["session_id"])
    assert _is_uuid(second["session_id"])


def test_start_session_without_user_gets_independent_guest_identity(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)

    first_session = service.start_session()
    second_session = service.start_session()
    first = service.get_agent_session(first_session)
    second = service.get_agent_session(second_session)

    assert first.session_id != second.session_id
    assert first.user_id != second.user_id
    assert first.user_id == f"guest-{first_session}"
    assert second.user_id == f"guest-{second_session}"
    assert service.env.sequences_by_user[first.user_id] == _empty_sequence(first.user_id)
    assert service.env.sequences_by_user[second.user_id] == _empty_sequence(second.user_id)
    assert first.active_constraints.liked_item_ids == set()
    assert second.active_constraints.liked_item_ids == set()


def test_unknown_explicit_user_gets_cold_start_session_without_reusing_user_id(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)

    session_id = service.start_session("new-user-1")
    result = service.chat(session_id, "For commute, prefer bluetooth and Audio")
    session = service.get_agent_session(session_id)

    assert session.user_id == "new-user-1"
    assert service.env.sequences_by_user[session.user_id] == _empty_sequence("new-user-1")
    assert result.display["user_id"] == "new-user-1"
    assert result.display["items"]


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


def test_public_serving_runtime_ignores_holdout_files(tmp_path: Path):
    config_path = _write_serving_fixture(tmp_path)
    (tmp_path / "clean" / "canonical_interactions.valid.jsonl").write_text("not-json\n", encoding="utf-8")
    (tmp_path / "clean" / "canonical_interactions.test.jsonl").write_text("not-json\n", encoding="utf-8")

    service = RecommendationService(str(config_path))
    session_id = service.start_session("u1")
    result = service.chat(session_id, "For commute, prefer bluetooth and Audio")

    assert service.env.holdout_records == []
    assert result.display["items"]
    _assert_no_blocked_keys(result.display)
    _assert_no_blocked_public_terms(result.display)


@pytest.mark.parametrize(
    "config_overrides, message",
    [
        ({"evaluation_mode": "valid_test"}, "evaluation_mode"),
        ({"role": "evaluation_only"}, "role:evaluation_only"),
        ({"serving_allowed": False}, "serving_allowed:false"),
    ],
)
def test_serving_rejects_evaluation_only_configs(tmp_path: Path, config_overrides: dict[str, Any], message: str):
    config_path = _write_serving_fixture(tmp_path)

    with pytest.raises(ValueError, match=message):
        RecommendationService(str(config_path), config_overrides=config_overrides)


@pytest.mark.parametrize(
    "governance_field",
    [
        "promotion_allowed",
        "pool1000_allowed",
        "ranking_input_replacement_allowed",
        "final_pool500_ready_claimed",
    ],
)
def test_serving_rejects_online_route_governance_relaxation(tmp_path: Path, governance_field: str):
    config_path = _write_serving_fixture(tmp_path)

    governance = dict(SERVING_GOVERNANCE)
    governance[governance_field] = True

    with pytest.raises(ValueError, match=f"online_route.governance.{governance_field}:false"):
        RecommendationService(
            str(config_path),
            config_overrides={"online_route": {"governance": governance}},
        )


def test_serving_rejects_online_candidate_route_without_governance(tmp_path: Path):
    config_path = _write_serving_fixture(tmp_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["online_route"].pop("governance")
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="online_route.governance for online candidate routes"):
        RecommendationService(str(config_path))



def test_recommendation_service_holds_facades_and_delegates_public_methods(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config_path = _write_serving_fixture(tmp_path)
    service = RecommendationService(str(config_path), limit_users=1)

    assert isinstance(service.feedback_session_facade, FeedbackSessionFacade)
    assert isinstance(service.recall_facade, RecallFacade)
    assert isinstance(service.recommendation_facade, RecommendationFacade)

    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        service.feedback_session_facade,
        "start_session",
        lambda user_id=None, request_id=None: calls.append(("start_session", user_id)) or "session-1",
    )
    monkeypatch.setattr(
        service.feedback_session_facade,
        "chat",
        lambda session_id, message, request_id=None: calls.append(("chat", session_id, message)) or type("Result", (), {"session_id": session_id, "display": {"items": []}})(),
    )
    monkeypatch.setattr(
        service.feedback_session_facade,
        "feedback",
        lambda session_id, action_type, item_id=None, comment=None, request_id=None: calls.append(("feedback", session_id, action_type, item_id, comment)) or type("Result", (), {"session_id": session_id, "display": {"items": []}})(),
    )
    monkeypatch.setattr(
        service.feedback_session_facade,
        "export_session",
        lambda session_id: calls.append(("export_session", session_id)) or {"session_id": session_id},
    )
    monkeypatch.setattr(
        service.recall_facade,
        "recall",
        lambda request: calls.append(("recall", request)) or {"request_id": "recall-1", "candidate_count": 0, "retrieval_summary": {}},
    )
    monkeypatch.setattr(
        service.recommendation_facade,
        "recommend_from_sequence",
        lambda request: calls.append(("recommend_from_sequence", request)) or {"request_id": "recommend-1", "item_count": 0, "candidate_count": 0, "fallback_used": False},
    )

    recall_request = RecallRequest(user_sequence={"recent_item_sequence": ["seed_audio"]})
    recommend_request = RecommendFromSequenceRequest(user_sequence={"recent_item_sequence": ["seed_audio"]})

    assert service.start_session("u1") == "session-1"
    assert service.chat("session-1", "hello").display == {"items": []}
    assert service.feedback("session-1", "why", "speaker_1", "short").display == {"items": []}
    assert service.export_session("session-1") == {"session_id": "session-1"}
    assert service.recall(recall_request) == {"request_id": "recall-1", "candidate_count": 0, "retrieval_summary": {}}
    assert service.recommend_from_sequence(recommend_request) == {"request_id": "recommend-1", "item_count": 0, "candidate_count": 0, "fallback_used": False}
    assert calls == [
        ("start_session", "u1"),
        ("chat", "session-1", "hello"),
        ("feedback", "session-1", "why", "speaker_1", "short"),
        ("export_session", "session-1"),
        ("recall", recall_request),
        ("recommend_from_sequence", recommend_request),
    ]


def test_feed_refresh_endpoint_reranks_and_rerecalls_without_chat_prompt(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    first = client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"}).json()

    like = client.post(
        "/feed/refresh",
        json={"session_id": session_id, "event_type": "like", "item_id": "speaker_1", "display_revision": 1, "top_k": 3},
    )
    stale = client.post(
        "/feed/refresh",
        json={"session_id": session_id, "event_type": "show_different", "display_revision": 1, "top_k": 3},
    )
    show_more = client.post(
        "/feed/refresh",
        json={"session_id": session_id, "event_type": "show_different", "display_revision": like.json()["display_revision"], "top_k": 3},
    )

    assert like.status_code == 200
    like_payload = like.json()
    assert like_payload["session_id"] == session_id
    assert like_payload["display_revision"] == 2
    assert like_payload["decision"]["action"] == "rerank_existing"
    assert like_payload["decision"]["decision_source"] == "feed_refresh_policy"
    assert like_payload["display"]["session_id"] == session_id
    assert like_payload["items"] == like_payload["display"]["items"]
    assert first["display"]["session_id"] == session_id

    assert stale.status_code == 200
    assert stale.json()["display_revision"] == 2
    assert stale.json()["decision"] == {
        "action": "no_refresh",
        "decision_source": "feed_refresh_policy",
        "reason_code": "idempotency_conflict",
        "fallback_reason": "idempotency_conflict",
    }

    assert show_more.status_code == 200
    assert show_more.json()["decision"]["action"] == "rerecall_pool500"
    _assert_no_blocked_keys(like_payload)
    _assert_no_blocked_public_terms(like_payload)


def test_feed_refresh_facade_observe_only_dwell_and_search_decisions(tmp_path: Path):
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1)
    session_id = service.start_session("u1")
    service.chat(session_id, "For commute, prefer bluetooth and Audio")

    click = service.feed_refresh(HomeFeedEventRequest(session_id=session_id, event_type="click", item_id="speaker_1", display_revision=1))
    dwell = service.feed_refresh(HomeFeedEventRequest(session_id=session_id, event_type="dwell", item_id="speaker_1", dwell_ms=3500, display_revision=1))
    search = service.feed_refresh(HomeFeedEventRequest(session_id=session_id, event_type="search", query="portable charger", display_revision=dwell["display_revision"]))

    assert click["decision"]["action"] == "no_refresh"
    assert click["display_revision"] == 1
    assert dwell["decision"]["action"] == "rerank_existing"
    assert dwell["display_revision"] == 2
    assert search["decision"]["action"] == "rerecall_pool500"
    assert search["display_revision"] == 3


def test_hybrid_demo_public_serving_smoke_does_not_read_holdout_files(tmp_path: Path):
    config_path = _write_serving_fixture(tmp_path)
    (tmp_path / "clean" / "canonical_interactions.valid.jsonl").write_text("not-json\n", encoding="utf-8")
    (tmp_path / "clean" / "canonical_interactions.test.jsonl").write_text("not-json\n", encoding="utf-8")

    result = run_hybrid_demo(str(config_path), limit_users=1, config_overrides={"evaluation_mode": "public_serving"})

    assert result["metrics"]["evaluation_mode"] == "public_serving"
    assert result["metrics"]["users_with_holdout"] == 0


def test_chat_executes_internal_tool_without_public_leakage(tmp_path: Path):
    config_path = _write_serving_fixture(tmp_path)
    service = RecommendationService(str(config_path), limit_users=1)
    session_id = service.start_session("u1")

    result = service.chat(session_id, "For commute, prefer bluetooth and Audio")
    turn = service.get_agent_session(session_id).turns[-1]

    tool_names = {event["tool_name"] for event in turn.diagnostics["agent_tool_events"]}
    planner_contract = turn.diagnostics["_tool_planner_contract"]

    assert service.env.tool_planner_system_prompt.startswith(AGENT_TOOL_BOUNDARY_SYSTEM_PROMPT)
    assert "retrieve_candidates" in service.env.tool_planner_system_prompt
    assert "semantic_live is available to every user" in service.env.tool_planner_system_prompt
    assert "不要直接调用 RAG 工具" in service.env.tool_planner_system_prompt
    assert "内部 RagAgent/runtime" in service.env.tool_planner_system_prompt
    assert "tool traces" in service.env.tool_planner_system_prompt
    assert planner_contract["sha256"] == service.env.tool_planner_contract_sha
    assert planner_contract["prompt_length"] == len(service.env.tool_planner_system_prompt)
    assert "_tool_planner_contract" not in result.display
    assert "tool_planner_system_prompt" not in result.display
    assert turn.diagnostics["agent_tool_trace"]
    assert {
        "get_user_context",
        "retrieve_candidates",
        "rank_candidates",
        "build_recommendation_slate",
    } <= tool_names
    assert "query_rag" not in tool_names
    assert "get_item_evidence" not in tool_names
    assert "record_user_feedback" not in tool_names
    _assert_no_blocked_keys(result.display)
    _assert_no_blocked_public_terms(result.display)


def test_semantic_live_retrieval_feeds_serving_main_route_without_public_leakage(tmp_path: Path):
    config_path = _write_serving_fixture(tmp_path)
    semantic_inputs = tmp_path / "semantic_recall_inputs.jsonl"
    inverted_index = tmp_path / "semantic_inverted_index.jsonl"
    sqlite_index = tmp_path / "semantic_description.sqlite"
    manifest_path = tmp_path / "semantic_description.sqlite.manifest.json"
    write_jsonl(semantic_inputs, [
        {
            "parent_asin": "semantic_speaker_1",
            "title_clean": "Portable Bluetooth Commute Speaker",
            "main_category": "Audio",
            "description_text": "compact wireless speaker for commute travel",
        },
        {
            "parent_asin": "semantic_charger_1",
            "title_clean": "USB Phone Charger",
            "main_category": "Accessories",
            "description_text": "wall charger adapter",
        },
    ])
    write_jsonl(inverted_index, [
        {"token": "bluetooth", "parent_asins": ["semantic_speaker_1"]},
        {"token": "commute", "parent_asins": ["semantic_speaker_1"]},
        {"token": "speaker", "parent_asins": ["semantic_speaker_1"]},
        {"token": "charger", "parent_asins": ["semantic_charger_1"]},
    ])
    build_sqlite_semantic_description_index(
        semantic_inputs_path=semantic_inputs,
        inverted_index_path=inverted_index,
        index_path=sqlite_index,
        manifest_path=manifest_path,
        overwrite=True,
    )
    service = RecommendationService(
        str(config_path),
        limit_users=1,
        config_overrides={
            "semantic_description_live": {
                "enabled": True,
                "semantic_inputs_path": str(semantic_inputs),
                "inverted_index_path": str(inverted_index),
                "sqlite_index_path": str(sqlite_index),
                "candidate_limit": 1000,
                "per_token_limit": 2000,
            },
            "rank_weights": {"semantic_live": 10.0, "itemcf_weak": 1.0, "category": 1.0, "popular": 1.0},
        },
    )
    session_id = service.start_session("u1")

    result = service.chat(session_id, "For commute, prefer bluetooth speaker and Audio")
    turn = service.get_agent_session(session_id).turns[-1]

    assert "semantic_speaker_1" in _display_item_ids(result.display)
    retrieval = turn.diagnostics["retrieve_candidates"]
    assert retrieval["candidate_count"] == 1
    assert retrieval["diagnostics"]["semantic_mode"] == "hybrid_query_history"
    assert retrieval["diagnostics"]["governance"] == {
        "label_inputs_role": "not_used",
        "oracle_label_injection": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    }
    assert any(
        candidate["item_id"] == "semantic_speaker_1" and "semantic_live" in candidate["sources"]
        for candidate in turn.candidates
    )
    _assert_no_blocked_keys(result.display)
    _assert_no_blocked_public_terms(result.display)


def test_service_smoke_completes_clarification_feedback_and_explanation_loop(tmp_path: Path):
    config_path = _write_serving_fixture(tmp_path)
    service = RecommendationService(str(config_path), limit_users=1)
    session_id = service.start_session("u1")

    vague = service.chat(session_id, "I want something")
    assert vague.display["items"] == []
    assert service.get_agent_session(session_id).turns[-1].recommendation.trigger_reason == "clarification_needed"

    recommendation = service.chat(session_id, "For commute, prefer bluetooth and Audio")
    recommended_item_ids = _display_item_ids(recommendation.display)
    assert recommended_item_ids

    changed = service.feedback(session_id, "show_different", recommended_item_ids[0])
    changed_item_ids = _display_item_ids(changed.display)
    assert changed_item_ids != recommended_item_ids

    stale = service.feedback(session_id, "why", recommended_item_ids[0])
    assert stale.display["assistant_message"] == "我只能解释最近一次推荐列表里的商品。"
    assert stale.display["items"] == []

    recent = service.feedback(session_id, "why", changed_item_ids[0])
    assert changed_item_ids[0] in recent.display["assistant_message"]
    assert recent.display["items"] == []
    exported = service.export_session(session_id)
    exported.pop("agent_thoughts", None)
    _assert_no_blocked_keys(exported)
    _assert_no_blocked_public_terms(exported)


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


def test_session_end_endpoint_defaults_to_disabled_summary_and_preserves_export(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"})

    response = client.post(
        "/session/end",
        json={"session_id": session_id, "reason": "manual", "client_event": "manual", "write_summary": True},
    )
    export = client.get(f"/session/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "session_id": session_id,
        "status": "ended",
        "turn_count": 1,
        "summary_document": {
            "relative_path": None,
            "created": False,
            "error": "LLM_SESSION_SUMMARY_DISABLED",
        },
    }
    assert export.status_code == 200
    assert export.json()["turn_count"] == 1


def test_session_end_normalizes_unknown_reason_and_can_skip_summary(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]

    response = client.post(
        "/session/end",
        json={"session_id": session_id, "reason": "unexpected", "client_event": "surprise", "write_summary": False},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session_id,
        "status": "ended",
        "turn_count": 0,
        "summary_document": None,
    }


def test_session_end_unknown_session_returns_stable_404_error(client: TestClient):
    response = client.post("/session/end", json={"session_id": "missing-session", "write_summary": False})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "SESSION_NOT_FOUND", "message": "Unknown session_id"}}


def test_session_end_makes_chat_and_feedback_read_only(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    client.post("/chat", json={"session_id": session_id, "message": "For commute, prefer bluetooth and Audio"})
    client.post("/session/end", json={"session_id": session_id, "write_summary": False})

    chat = client.post("/chat", json={"session_id": session_id, "message": "more please"})
    feedback = client.post("/feedback", json={"session_id": session_id, "action_type": "why", "item_id": "speaker_1"})
    export = client.get(f"/session/{session_id}")

    assert chat.status_code == 409
    assert chat.json() == {"error": {"code": "SESSION_ENDED", "message": "Session has already ended"}}
    assert feedback.status_code == 409
    assert feedback.json() == {"error": {"code": "SESSION_ENDED", "message": "Session has already ended"}}
    assert export.status_code == 200
    assert export.json()["turn_count"] == 1


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
    assert "agent_thoughts" not in payload
    _assert_no_blocked_keys(payload)
    _assert_no_blocked_public_terms(payload)


def test_session_export_allows_user_message_with_internal_tool_terms(client: TestClient):
    session_id = client.post("/session/start", json={"user_id": "u1"}).json()["session_id"]
    message = "please use catalog_constraint_search for bluetooth"
    chat = client.post("/chat", json={"session_id": session_id, "message": message}).json()

    response = client.get(f"/session/{session_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["public_timeline"]["events"][0]["user_message"] == message
    assert payload["display_responses"] == [chat["display"]]
    _assert_no_blocked_keys(payload["display_responses"])
    _assert_no_blocked_public_terms(payload["display_responses"])


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


def _assert_ready_no_internal_details(value):
    serialized = json.dumps(value).lower()
    blocked_terms = {
        "manifest_path",
        "source_index_manifest",
        "candidates_path",
        "config_path",
        "source_counts",
        "itemcf_weak",
        "itemcf_strong",
        "two_tower",
        "usercf_recall",
        "co_visit_fallback_repair",
        "/",
        "\\\\",
    }
    for term in blocked_terms:
        assert term not in serialized


def _display_item_ids(display: dict[str, Any]) -> list[str]:
    return [str(item["parent_asin"]) for item in display["items"]]


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _empty_sequence(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "recent_item_sequence": [],
        "recent_positive_item_sequence": [],
        "recent_strong_positive_item_sequence": [],
    }


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
    pool500 = root / "pool500_candidates.jsonl"
    write_jsonl(pool500, [
        {
            "user_id": "u1",
            "item_id": "speaker_1",
            "source": "semantic",
            "sources": ["semantic"],
            "score": 9.0,
            "rank": 1,
            "metadata": {"category": "Audio", "title_clean": "Bluetooth speaker for commute"},
        },
        {
            "user_id": "u1",
            "item_id": "neighbor_online_1",
            "source": "itemcf_weak",
            "sources": ["itemcf_weak"],
            "score": 8.0,
            "rank": 2,
            "metadata": {"category": "Audio", "title_clean": "Neighbor speaker for commute"},
        },
        {
            "user_id": "u1",
            "item_id": "embedding_online_1",
            "source": "two_tower",
            "sources": ["two_tower"],
            "score": 7.0,
            "rank": 3,
            "metadata": {"category": "Audio", "title_clean": "Embedding headphones for commute"},
        },
        {
            "user_id": "u1",
            "item_id": "community_online_1",
            "source": "usercf_recall",
            "sources": ["usercf_recall"],
            "score": 6.0,
            "rank": 4,
            "metadata": {"category": "Audio", "title_clean": "User neighbor headphones for commute"},
        },
        {
            "user_id": "u1",
            "item_id": "cohort_online_1",
            "source": "co_visit_fallback_repair",
            "sources": ["co_visit_fallback_repair"],
            "score": 5.0,
            "rank": 5,
            "metadata": {"category": "Audio", "title_clean": "Co visit repair speaker accessory"},
        },
        {
            "user_id": "u1",
            "item_id": "legacy_semantic_title_1",
            "source": "semantic_title_category_expansion",
            "sources": ["semantic_title_category_expansion"],
            "score": 99.0,
            "rank": 1,
            "metadata": {"category": "Audio", "title_clean": "Legacy semantic title source"},
        },
    ])
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
            "two_tower": 1.0,
            "usercf_recall": 1.0,
            "co_visit_fallback_repair": 1.0,
            "category": 1.0,
            "feedback_category": 10.0,
            "feedback_keyword": 10.0,
        },
        "feedback_category_boost": 1.0,
        "feedback_keyword_boost": 1.0,
        "online_route": {
            "pool500_candidates_path": str(pool500),
            "allowed_sources": ["semantic", "popular", "itemcf_weak", "two_tower", "usercf_recall", "co_visit_fallback_repair"],
            "governance": SERVING_GOVERNANCE,
        },
    }), encoding="utf-8")
    return config
