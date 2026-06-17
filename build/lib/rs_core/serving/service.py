from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from rs_core.common.config import load_config
from rs_core.display import build_display_record, build_public_timeline
from rs_core.rsagent.context import ensure_session_context_state
from rs_core.rsagent.long_memory import (
    LongMemoryConfig,
    LongMemoryStore,
    build_long_memory_store,
    hydrate_session_from_long_memory,
    snapshot_session_long_memory,
)
from rs_core.rsagent.schema import AgentSession
from rs_core.serving.schema import RecommendFromSequenceRequest
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment
from rs_core.workflow.online_recommendation import OnlinePool500Recommender

DEFAULT_CONFIG = "configs/demo/hybrid_demo/hybrid_demo_electronics_10000_lopo_semantic_title.yaml"
SERVING_CONFIG_ENV = "RS_SERVING_CONFIG"
FEEDBACK_PROMPTS = {
    "like": "I like this item, show me more like this.",
    "dislike": "I don't like this item, try a different direction.",
    "show_different": "show me something different",
    "why": "why?",
}


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
        self.sessions: dict[str, AgentSession] = {}
        self.session_events: dict[str, list[dict[str, Any]]] = {}

    def start_session(self, user_id: str | None = None) -> str:
        session_id = str(uuid4())
        session = self.env.start_session(user_id=user_id, session_id=session_id)
        self._hydrate_long_memory(session)
        self.sessions[session_id] = session
        self.session_events[session_id] = []
        return session_id

    def chat(self, session_id: str, message: str) -> ChatResult:
        session = self._session(session_id)
        turn = self.env.converse(session, message)
        self.session_events[session_id].append({"type": "chat"})
        self._persist_long_memory(session)
        return ChatResult(session_id=session_id, display=build_display_record(turn, session))

    def feedback(self, session_id: str, action_type: str, item_id: str | None = None, comment: str | None = None) -> ChatResult:
        session = self._session(session_id)
        prompt = feedback_prompt(action_type, item_id, comment)
        turn = self.env.converse(session, prompt, explanation_item_id=item_id if action_type.strip().lower() == "why" else None)
        self.session_events[session_id].append({
            "type": "feedback",
            "action_type": action_type.strip().lower(),
            "item_id": item_id,
            "comment": comment,
        })
        self._persist_long_memory(session)
        return ChatResult(session_id=session_id, display=build_display_record(turn, session))

    def get_agent_session(self, session_id: str) -> AgentSession:
        return self._session(session_id)

    def readiness(self) -> dict[str, Any]:
        online = self.online_recommender.readiness()
        return {
            "status": "ready" if online.get("complete_pool500_available") else "degraded",
            "service": "rs-agent-serving",
            "mode": online.get("mode", "demo-compatible"),
            "session_state": "single_process_in_memory",
            "online_route": online,
        }

    def recommend_from_sequence(self, request: RecommendFromSequenceRequest) -> dict[str, Any]:
        result = self.online_recommender.recommend(
            request.user_sequence,
            user_id=request.user_id,
            feedback_text=request.feedback_text,
            top_k=request.top_k,
            candidate_pool_size=request.candidate_pool_size,
            complete_pool500=request.complete_pool500,
        )
        return {
            "request_id": result.request_id,
            "display": result.display,
            "items": result.items,
            "item_count": len(result.items),
            "candidate_count": result.candidate_count,
            "fallback_used": result.fallback_used,
        }

    def export_session(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        display_responses = [build_display_record(turn, session) for turn in session.turns]
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "turn_count": len(session.turns),
            "public_timeline": build_public_timeline(session, self.session_events[session_id]),
            "display_responses": display_responses,
        }

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
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def _hydrate_long_memory(self, session: AgentSession) -> None:
        if not self.long_memory_config.enabled or self.long_memory_store is None:
            ensure_session_context_state(session)
            return
        memory = self.long_memory_store.load_user_memory(session.user_id)
        hydrate_session_from_long_memory(session, memory)

    def _persist_long_memory(self, session: AgentSession) -> None:
        if not self.long_memory_config.enabled or self.long_memory_store is None:
            ensure_session_context_state(session)
            return
        self.long_memory_store.save_user_memory(snapshot_session_long_memory(session, self.long_memory_config))


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
    registry_path = Path("configs/governance/current_route_registry.yaml")
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
        return str(config_paths[0])
    return None


def _validate_serving_config(config: dict[str, Any]) -> None:
    evaluation_mode = config.get("evaluation_mode")
    if evaluation_mode not in (None, "", "none", "public_serving"):
        raise ValueError(f"Serving runtime requires evaluation_mode public_serving or omitted, got: {evaluation_mode}")
    if str(config.get("role", "")).strip().lower() == "evaluation_only":
        raise ValueError("Serving runtime rejects role:evaluation_only")
    if config.get("serving_allowed") is False:
        raise ValueError("Serving runtime rejects serving_allowed:false")


def _merge_nested(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_nested(merged[key], value)
        else:
            merged[key] = value
    return merged


def feedback_prompt(action_type: str, item_id: str | None = None, comment: str | None = None) -> str:
    action = action_type.strip().lower()
    if action not in FEEDBACK_PROMPTS:
        raise ValueError(f"Unsupported feedback action_type: {action_type}")
    parts = [FEEDBACK_PROMPTS[action]]
    if item_id:
        parts.append(f"item_id={item_id}")
    if comment:
        parts.append(comment.strip())
    return " ".join(part for part in parts if part)


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
