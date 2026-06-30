from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rs_core.agent.contracts import AgentSession
from rs_core.agent.memory import LongMemoryConfig, LongMemoryStore, build_long_memory_store
from rs_core.common.config import load_config
from rs_core.serving.facades import (
    FeedbackSessionFacade,
    FeedRefreshFacade,
    RecommendationFacade,
    RecallFacade,
    feedback_prompt as _facade_feedback_prompt,
)
from rs_core.serving.infrastructure.stores.structured_dataset import (
    StructuredDatasetStore,
    build_structured_dataset_store_from_env,
    ensure_safe_structured_dataset_store,
)
from rs_core.serving.persistence import ServingPersistenceStore, ensure_safe_persistence_store
from rs_core.serving.runtime.config import DEFAULT_CONFIG, _merge_nested, _serving_env_overrides, _validate_serving_config, resolve_serving_config
from rs_core.serving.runtime.readiness import (
    _public_agent_provider_readiness,
    _public_artifact_manifest_readiness,
    _public_candidate_retrieval_readiness,
    _public_deepfm_shadow_readiness,
    _public_online_route_readiness,
    _public_rag_readiness,
)
from rs_core.serving.schemas import HomeFeedEventRequest, RecallRequest, RecommendFromSequenceRequest
from rs_core.serving.session_summary import SessionSummaryServiceProtocol, build_session_summary_service
from rs_core.online.runtime import build_online_pool500_recommender
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment


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
        structured_dataset_store: StructuredDatasetStore | None = None,
    ) -> None:
        resolved_config = resolve_serving_config(config)
        effective_config = load_config(resolved_config)
        if config_overrides:
            effective_config = _merge_nested(effective_config, config_overrides)
        env_overrides = _serving_env_overrides(effective_config)
        if env_overrides:
            effective_config = _merge_nested(effective_config, env_overrides)
        effective_overrides = _merge_nested(config_overrides or {}, env_overrides) if env_overrides else config_overrides
        _validate_serving_config(effective_config)
        self.env = HybridRecommendationEnvironment.from_config(resolved_config, limit_users=limit_users, config_overrides=effective_overrides)
        self.online_recommender = build_online_pool500_recommender(self.env)
        self.env.online_recommender = self.online_recommender
        self.long_memory_config = long_memory_config or LongMemoryConfig(enabled=False)
        self.long_memory_store = long_memory_store or build_long_memory_store(self.long_memory_config)
        self.persistence_store = ensure_safe_persistence_store(persistence_store)
        self.session_summary_service = session_summary_service or build_session_summary_service(effective_config)
        self.structured_dataset_store = ensure_safe_structured_dataset_store(structured_dataset_store or build_structured_dataset_store_from_env())
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
        candidate_retrieval = _public_candidate_retrieval_readiness(online)
        route_available = candidate_retrieval.get("available") or public_route.get("complete_pool500_available") or public_route.get("online_source_indexes_available")
        return {
            "status": "ready" if route_available else "degraded",
            "service": "rs-agent-serving",
            "mode": public_route.get("mode", "demo-compatible"),
            "session_state": "single_process_in_memory",
            "online_route": public_route,
            "candidate_retrieval": candidate_retrieval,
            "rag": _public_rag_readiness(self.env.config),
            "artifact_manifests": _public_artifact_manifest_readiness(self.env.config),
            "deepfm_shadow": _public_deepfm_shadow_readiness(self.env.config),
            "agent_provider": _public_agent_provider_readiness(self.env.config),
            "structured_dataset": self.structured_dataset_store.health(),
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
