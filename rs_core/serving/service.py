from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rs_core.common.config import load_config
from rs_core.rsagent.long_memory import LongMemoryConfig, LongMemoryStore, build_long_memory_store
from rs_core.rsagent.schema import AgentSession
from rs_core.serving.persistence import ServingPersistenceStore, ensure_safe_persistence_store
from rs_core.serving.session_summary import SessionSummaryServiceProtocol, build_session_summary_service
from rs_core.serving.facades import (
    SERVING_GOVERNANCE_GUARDRAILS,
    FeedbackSessionFacade,
    FeedRefreshFacade,
    RecommendationFacade,
    RecallFacade,
    SessionEndedError,
    feedback_prompt as _facade_feedback_prompt,
)
from rs_core.serving.schema import HomeFeedEventRequest, RecallRequest, RecommendFromSequenceRequest
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment
from rs_core.workflow.online_recommendation import OnlinePool500Recommender

DEFAULT_CONFIG = "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml"
SERVING_CONFIG_ENV = "RS_SERVING_CONFIG"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

__all__ = ["DEFAULT_CONFIG", "RecommendationService", "SessionEndedError", "SessionNotFoundError"]


@dataclass
class ChatResult:
    session_id: str
    display: dict


@dataclass
class DemoRoundtripResult:
    session_id: str
    first_display: dict
    feedback_display: dict
    change_summary: dict[str, Any]


class SessionNotFoundError(KeyError):
    pass


class RecommendationService:
    """Single-process demo service; session state is in memory and not production-safe."""

    def __init__(
        self,
        config: str | Path = DEFAULT_CONFIG,
        limit_users: int | None = None,
        config_overrides: dict[str, Any] | None = None,
        long_memory_config: LongMemoryConfig | None = None,
        long_memory_store: LongMemoryStore | None = None,
        persistence_store: ServingPersistenceStore | None = None,
        session_summary_service: SessionSummaryServiceProtocol | None = None,
    ) -> None:
        resolved_config = resolve_serving_config(config)
        effective_config = load_config(resolved_config)
        if config_overrides:
            effective_config = _merge_nested(effective_config, config_overrides)
        _validate_serving_config(effective_config)
        self.env = HybridRecommendationEnvironment.from_config(resolved_config, limit_users=limit_users, config_overrides=config_overrides)
        self.online_recommender = OnlinePool500Recommender.from_environment(self.env)
        self.env.online_recommender = self.online_recommender
        self.long_memory_config = long_memory_config or LongMemoryConfig(enabled=False)
        self.long_memory_store = long_memory_store or build_long_memory_store(self.long_memory_config)
        self.persistence_store = ensure_safe_persistence_store(persistence_store)
        self.session_summary_service = session_summary_service or build_session_summary_service(effective_config)
        self.sessions: dict[str, AgentSession] = {}
        self.session_events: dict[str, list[dict[str, Any]]] = {}
        self.feedback_session_facade = FeedbackSessionFacade(
            self.env,
            self.sessions,
            self.session_events,
            self.long_memory_config,
            self.long_memory_store,
            not_found_error=SessionNotFoundError,
            persistence_store=self.persistence_store,
            session_summary_service=self.session_summary_service,
        )
        self.recall_facade = RecallFacade(self.online_recommender)
        self.recommendation_facade = RecommendationFacade(self.online_recommender)
        self.feed_refresh_facade = FeedRefreshFacade(
            self.online_recommender,
            self.sessions,
            not_found_error=SessionNotFoundError,
        )

    def start_session(self, user_id: str | None = None, request_id: str | None = None) -> str:
        if request_id is None:
            return self.feedback_session_facade.start_session(user_id)
        return self.feedback_session_facade.start_session(user_id, request_id=request_id)

    def chat(self, session_id: str, message: str, request_id: str | None = None) -> ChatResult:
        result = self.feedback_session_facade.chat(session_id, message) if request_id is None else self.feedback_session_facade.chat(session_id, message, request_id=request_id)
        return ChatResult(session_id=result.session_id, display=result.display)

    def feedback(self, session_id: str, action_type: str, item_id: str | None = None, comment: str | None = None, request_id: str | None = None) -> ChatResult:
        result = (
            self.feedback_session_facade.feedback(session_id, action_type, item_id, comment)
            if request_id is None
            else self.feedback_session_facade.feedback(session_id, action_type, item_id, comment, request_id=request_id)
        )
        return ChatResult(session_id=result.session_id, display=result.display)

    def end_session(
        self,
        session_id: str,
        reason: str = "unknown",
        client_event: str | None = None,
        write_summary: bool = True,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self.feedback_session_facade.end_session(
            session_id,
            reason=reason,
            client_event=client_event,
            write_summary=write_summary,
            request_id=request_id,
        )

    def get_agent_session(self, session_id: str) -> AgentSession:
        return self._session(session_id)

    def readiness(self) -> dict[str, Any]:
        online = self.online_recommender.readiness()
        public_route = _public_online_route_readiness(online)
        route_available = public_route.get("complete_pool500_available") or public_route.get("online_source_indexes_available")
        return {
            "status": "ready" if route_available else "degraded",
            "service": "rs-agent-serving",
            "mode": public_route.get("mode", "demo-compatible"),
            "session_state": "single_process_in_memory",
            "online_route": public_route,
        }

    def recommend_from_sequence(self, request: RecommendFromSequenceRequest, request_id: str | None = None) -> dict[str, Any]:
        result = self.recommendation_facade.recommend_from_sequence(request)
        if {"request_id", "item_count", "candidate_count", "fallback_used"}.issubset(result):
            self.persistence_store.record_request_summary(
                request_id=result["request_id"],
                endpoint="recommend",
                user_id=request.user_id or _request_user_id(request.user_sequence),
                item_count=result["item_count"],
                candidate_count=result["candidate_count"],
                fallback_used=result["fallback_used"],
                public_summary={"http_request_id": request_id} if request_id else {},
            )
        return result

    def recall(self, request: RecallRequest, request_id: str | None = None) -> dict[str, Any]:
        result = self.recall_facade.recall(request)
        if {"request_id", "candidate_count", "retrieval_summary"}.issubset(result):
            self.persistence_store.record_request_summary(
                request_id=result["request_id"],
                endpoint="recall",
                user_id=request.user_id or _request_user_id(request.user_sequence),
                candidate_count=result["candidate_count"],
                public_summary={
                    "http_request_id": request_id,
                    "retrieval_summary": result["retrieval_summary"],
                } if request_id else {"retrieval_summary": result["retrieval_summary"]},
            )
        return result

    def feed_refresh(self, request: HomeFeedEventRequest, request_id: str | None = None) -> dict[str, Any]:
        result = self.feed_refresh_facade.refresh(request)
        self.persistence_store.record_request_summary(
            request_id=result["request_id"],
            endpoint="feed_refresh",
            user_id=self._session(request.session_id).user_id,
            item_count=result["item_count"],
            candidate_count=result["candidate_count"],
            fallback_used=result["fallback_used"],
            public_summary={
                "http_request_id": request_id,
                "decision": result["decision"],
                "display_revision": result["display_revision"],
            } if request_id else {
                "decision": result["decision"],
                "display_revision": result["display_revision"],
            },
        )
        return result

    def export_session(self, session_id: str) -> dict[str, Any]:
        return self.feedback_session_facade.export_session(session_id)

    def run_demo_roundtrip(
        self,
        message: str,
        feedback_action: str = "show_different",
        user_id: str | None = None,
        item_id: str | None = None,
        comment: str | None = None,
    ) -> DemoRoundtripResult:
        session_id = self.start_session(user_id)
        first = self.chat(session_id, message).display
        selected_item_id = item_id or first_item_id(first)
        feedback = self.feedback(session_id, feedback_action, selected_item_id, comment).display
        return DemoRoundtripResult(
            session_id=session_id,
            first_display=first,
            feedback_display=feedback,
            change_summary=display_change_summary(first, feedback),
        )

    def _session(self, session_id: str) -> AgentSession:
        return self.feedback_session_facade.session(session_id)


def resolve_serving_config(config: str | Path = DEFAULT_CONFIG) -> str | Path:
    env_config = os.environ.get(SERVING_CONFIG_ENV)
    if env_config:
        return env_config
    if str(config) == DEFAULT_CONFIG:
        registry_config = _current_online_service_config()
        if registry_config:
            return registry_config
    return config


def _current_online_service_config() -> str | None:
    registry_path = PROJECT_ROOT / "configs/governance/current_route_registry.yaml"
    if not registry_path.exists():
        return None
    try:
        registry = load_config(registry_path)
    except Exception:
        return None
    routes = registry.get("routes") if isinstance(registry.get("routes"), dict) else {}
    route = routes.get("current_online_service_route") if isinstance(routes.get("current_online_service_route"), dict) else {}
    config_paths = route.get("config_paths")
    if isinstance(config_paths, list) and config_paths:
        path = Path(str(config_paths[0]))
        return str(path if path.is_absolute() else PROJECT_ROOT / path)
    return None


def _validate_serving_config(config: dict[str, Any]) -> None:
    evaluation_mode = config.get("evaluation_mode")
    if evaluation_mode not in (None, "", "none", "public_serving"):
        raise ValueError(f"Serving runtime requires evaluation_mode public_serving or omitted, got: {evaluation_mode}")
    if str(config.get("role", "")).strip().lower() == "evaluation_only":
        raise ValueError("Serving runtime rejects role:evaluation_only")
    if config.get("serving_allowed") is False:
        raise ValueError("Serving runtime rejects serving_allowed:false")
    _validate_serving_governance_guardrails(config)


def _validate_serving_governance_guardrails(config: dict[str, Any]) -> None:
    online_route = config.get("online_route")
    if not isinstance(online_route, dict):
        return
    governance = online_route.get("governance")
    if _online_route_has_candidate_inputs(online_route) and not isinstance(governance, dict):
        raise ValueError("Serving runtime requires online_route.governance for online candidate routes")
    if not isinstance(governance, dict):
        return
    for field, expected in SERVING_GOVERNANCE_GUARDRAILS.items():
        if governance.get(field) is not expected:
            raise ValueError(f"Serving runtime requires online_route.governance.{field}:{str(expected).lower()}")


def _online_route_has_candidate_inputs(online_route: dict[str, Any]) -> bool:
    return any(
        online_route.get(field)
        for field in (
            "pool500_candidates_path",
            "source_indexes",
            "online_source_indexes",
            "source_manifests",
        )
    )


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def _public_online_route_readiness(online: dict[str, Any]) -> dict[str, Any]:
    source_indexes = online.get("online_source_indexes") if isinstance(online.get("online_source_indexes"), dict) else {}
    artifact = online.get("pool500_artifact") if isinstance(online.get("pool500_artifact"), dict) else {}
    return {
        "mode": online.get("mode", "demo-compatible"),
        "session_state": "single_process_in_memory",
        "complete_pool500_available": bool(online.get("complete_pool500_available")),
        "online_source_indexes_available": bool(online.get("online_source_indexes_available")),
        "source_index_available_count": sum(1 for status in source_indexes.values() if isinstance(status, dict) and status.get("available")),
        "source_index_configured_count": len(source_indexes),
        "pool500_artifact": {
            "enabled": bool(artifact.get("enabled")),
            "status": str(artifact.get("status", "not_configured")),
        },
    }


def feedback_prompt(action_type: str, item_id: str | None = None, comment: str | None = None) -> str:
    return _facade_feedback_prompt(action_type, item_id, comment)


def first_item_id(display: dict[str, Any]) -> str | None:
    items = display.get("items")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    parent_asin = first.get("parent_asin")
    return str(parent_asin) if parent_asin else None


def display_change_summary(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    first_ids = display_item_ids(first)
    second_ids = display_item_ids(second)
    return {
        "first_item_ids": first_ids,
        "feedback_item_ids": second_ids,
        "added_item_ids": [item_id for item_id in second_ids if item_id not in first_ids],
        "removed_item_ids": [item_id for item_id in first_ids if item_id not in second_ids],
        "changed": first_ids != second_ids,
    }


def display_item_ids(display: dict[str, Any]) -> list[str]:
    items = display.get("items")
    if not isinstance(items, list):
        return []
    item_ids: list[str] = []
    for item in items:
        if isinstance(item, dict) and item.get("parent_asin"):
            item_ids.append(str(item["parent_asin"]))
    return item_ids


def _request_user_id(user_sequence: dict[str, Any]) -> str | None:
    user_id = user_sequence.get("user_id") if isinstance(user_sequence, dict) else None
    return str(user_id) if user_id not in (None, "") else None
