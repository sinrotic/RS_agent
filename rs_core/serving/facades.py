from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from rs_core.agent.context import ensure_session_context_state
from rs_core.agent.contracts import AgentSession
from rs_core.agent.memory import (
    LongMemoryConfig,
    LongMemoryStore,
    hydrate_session_from_long_memory,
    snapshot_session_long_memory,
)
from rs_core.display import build_display_record, build_public_timeline, validate_public_display_payload
from rs_core.serving.persistence import NoopServingPersistenceStore, ServingPersistenceStore
from rs_core.serving.schemas import HomeFeedEventRequest, RecallRequest, RecommendFromSequenceRequest
from rs_core.serving.session_summary import DisabledSessionSummaryService, SessionSummaryServiceProtocol

PUBLIC_RESPONSE_FORBIDDEN_FIELDS = frozenset({
    "diagnostics",
    "source_scores",
    "tool_traces",
})


class SessionEndedError(RuntimeError):
    pass


SERVING_GOVERNANCE_GUARDRAILS = {
    "ranking_input_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
}

FEEDBACK_PROMPTS = {
    "like": "I like this item, show me more like this.",
    "dislike": "I don't like this item, try a different direction.",
    "show_different": "show me something different",
    "why": "why?",
    "accept": "I will take this recommendation.",
}


def _session_user_id(user_id: str | None, session_id: str) -> str:
    normalized = str(user_id).strip() if user_id else ""
    return normalized or f"guest-{session_id}"


@dataclass
class FacadeChatResult:
    session_id: str
    display: dict[str, Any]


class FeedbackSessionFacade:
    """Session and feedback seam that preserves the single-process service contract."""

    def __init__(
        self,
        env: Any,
        sessions: dict[str, AgentSession],
        session_events: dict[str, list[dict[str, Any]]],
        long_memory_config: LongMemoryConfig,
        long_memory_store: LongMemoryStore | None,
        not_found_error: type[KeyError] = KeyError,
        persistence_store: ServingPersistenceStore | None = None,
        session_summary_service: SessionSummaryServiceProtocol | None = None,
    ) -> None:
        self.env = env
        self.sessions = sessions
        self.session_events = session_events
        self.long_memory_config = long_memory_config
        self.long_memory_store = long_memory_store
        self.not_found_error = not_found_error
        self.persistence_store = persistence_store or NoopServingPersistenceStore()
        self.session_summary_service = session_summary_service or DisabledSessionSummaryService()
        self.ended_session_ids: set[str] = set()

    def start_session(self, user_id: str | None = None, request_id: str | None = None) -> str:
        session_id = str(uuid4())
        session_user_id = _session_user_id(user_id, session_id)
        session = self.env.start_session(user_id=session_user_id, session_id=session_id)
        self._hydrate_long_memory(session)
        self.sessions[session_id] = session
        self.session_events[session_id] = []
        self.persistence_store.record_session_started(session_id=session_id, user_id=session.user_id, request_id=request_id)
        return session_id

    def chat(self, session_id: str, message: str, request_id: str | None = None) -> FacadeChatResult:
        self._ensure_mutable_session(session_id)
        session = self.session(session_id)
        turn = self.env.converse(session, message)
        self.session_events[session_id].append({"type": "chat"})
        self._persist_long_memory(session)
        display = build_display_record(turn, session)
        self.persistence_store.record_turn_committed(
            session_id=session_id,
            user_id=session.user_id,
            turn_index=turn.turn_index,
            event_type="chat",
            user_message=turn.user_input,
            assistant_message=display["assistant_message"],
            display=display,
            request_id=request_id,
        )
        return FacadeChatResult(session_id=session_id, display=display)

    def feedback(self, session_id: str, action_type: str, item_id: str | None = None, comment: str | None = None, request_id: str | None = None) -> FacadeChatResult:
        self._ensure_mutable_session(session_id)
        session = self.session(session_id)
        normalized_action = action_type.strip().lower()
        prompt = feedback_prompt(action_type, item_id, comment)
        turn = self.env.converse(session, prompt, explanation_item_id=item_id if normalized_action == "why" else None)
        self.session_events[session_id].append({
            "type": "feedback",
            "action_type": normalized_action,
            "item_id": item_id,
            "comment": comment,
        })
        self._persist_long_memory(session)
        display = build_display_record(turn, session)
        self.persistence_store.record_feedback_event(
            session_id=session_id,
            turn_index=turn.turn_index,
            action_type=normalized_action,
            item_id=item_id,
            comment=comment,
            request_id=request_id,
        )
        self.persistence_store.record_turn_committed(
            session_id=session_id,
            user_id=session.user_id,
            turn_index=turn.turn_index,
            event_type="feedback",
            user_message=turn.user_input,
            assistant_message=display["assistant_message"],
            display=display,
            request_id=request_id,
        )
        return FacadeChatResult(session_id=session_id, display=display)

    def session(self, session_id: str) -> AgentSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise self.not_found_error(session_id)
        return session

    def export_session(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            persisted = self.persistence_store.load_public_session_export(session_id)
            if persisted is not None:
                return persisted
            raise self.not_found_error(session_id)
        display_responses = [build_display_record(turn, session) for turn in session.turns]
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "turn_count": len(session.turns),
            "public_timeline": build_public_timeline(session, self.session_events[session_id]),
            "display_responses": display_responses,
        }

    def end_session(
        self,
        session_id: str,
        *,
        reason: str = "unknown",
        client_event: str | None = None,
        write_summary: bool = True,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        public_export = self.export_session(session_id)
        summary_document = None
        if write_summary:
            result = self.session_summary_service.summarize_and_write(
                public_export,
                reason=reason,
                client_event=client_event,
                request_id=request_id,
            )
            summary_document = {
                "relative_path": result.relative_path,
                "created": result.created,
                "error": result.error,
            }
        response = {
            "session_id": public_export["session_id"],
            "status": "ended",
            "turn_count": int(public_export.get("turn_count") or 0),
            "summary_document": summary_document,
        }
        self.ended_session_ids.add(session_id)
        self.persistence_store.record_session_ended(
            session_id=session_id,
            reason=reason,
            client_event=client_event,
            request_id=request_id,
            public_summary={
                "turn_count": response["turn_count"],
                "summary_document": summary_document,
            },
        )
        return response

    def _ensure_mutable_session(self, session_id: str) -> None:
        if session_id in self.ended_session_ids:
            raise SessionEndedError(session_id)

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


class RecallFacade:
    """Recall seam for public candidate retrieval responses."""

    def __init__(self, online_recommender: Any) -> None:
        self.online_recommender = online_recommender

    def recall(self, request: RecallRequest) -> dict[str, Any]:
        user_sequence = dict(request.user_sequence)
        if request.user_id is not None:
            user_sequence["user_id"] = request.user_id
        result = self.online_recommender.tool_retrieve_candidates(
            user_sequence,
            prior_turn_items=set(request.prior_turn_items),
            candidate_pool_size=request.candidate_pool_size,
        )
        retrieval_summary = result.get("retrieval_summary") if isinstance(result.get("retrieval_summary"), dict) else {}
        return {
            "request_id": str(uuid4()),
            "candidate_item_ids": result["candidate_item_ids"],
            "candidate_count": result["candidate_count"],
            "retrieval_summary": {
                "target_pool_size": retrieval_summary.get("target_pool_size"),
                "path_count": retrieval_summary.get("path_count"),
            },
        }


@dataclass
class FeedSessionState:
    session_id: str
    user_id: str
    display: dict[str, Any]
    display_revision: int = 1
    seen_item_ids: set[str] | None = None
    liked_item_ids: set[str] | None = None
    disliked_item_ids: set[str] | None = None
    show_different_count: int = 0

    def __post_init__(self) -> None:
        self.seen_item_ids = set(self.seen_item_ids or _display_item_ids(self.display))
        self.liked_item_ids = set(self.liked_item_ids or set())
        self.disliked_item_ids = set(self.disliked_item_ids or set())


class FeedRefreshPolicy:
    """Low-latency policy for structured homepage behavior events."""

    def decide(self, state: FeedSessionState, request: HomeFeedEventRequest) -> dict[str, Any]:
        if request.event_type == "search":
            return _feed_decision("rerecall_pool500", "search_new_intent")
        if request.event_type == "show_different":
            current_count = len(state.display.get("items", []))
            if state.show_different_count >= 2 or current_count <= request.top_k:
                return _feed_decision("rerecall_pool500", "repeated_show_different_or_underfill")
            return _feed_decision("rerank_existing", "show_different_diversity_rerank")
        if request.event_type == "dislike":
            return _feed_decision("rerank_existing", "explicit_negative_feedback")
        if request.event_type == "like":
            return _feed_decision("rerank_existing", "explicit_positive_feedback")
        if request.event_type == "dwell" and (request.dwell_ms or 0) >= 3000:
            return _feed_decision("rerank_existing", "positive_dwell_signal")
        return _feed_decision("no_refresh", "observe_only")


class FeedRefreshFacade:
    """Structured homepage behavior seam; keeps feed refresh out of the chat prompt loop."""

    def __init__(self, online_recommender: Any, sessions: dict[str, AgentSession], not_found_error: type[KeyError] = KeyError, policy: FeedRefreshPolicy | None = None) -> None:
        self.online_recommender = online_recommender
        self.sessions = sessions
        self.not_found_error = not_found_error
        self.policy = policy or FeedRefreshPolicy()
        self.feed_states: dict[str, FeedSessionState] = {}
        self.decision_traces: list[dict[str, Any]] = []

    def refresh(self, request: HomeFeedEventRequest) -> dict[str, Any]:
        state = self._state_for_session(request.session_id)
        if request.display_revision != state.display_revision:
            decision = _feed_decision("no_refresh", "idempotency_conflict", fallback_reason="idempotency_conflict")
            return self._response(request, state, decision, candidate_count=len(state.display.get("items", [])), fallback_used=True)

        self._apply_event_to_state(state, request)
        decision = self.policy.decide(state, request)
        if decision["action"] == "no_refresh":
            return self._response(request, state, decision, candidate_count=len(state.display.get("items", [])), fallback_used=False)

        try:
            result = self.online_recommender.recommend(
                _feed_user_sequence(state),
                user_id=state.user_id,
                feedback_text=_feed_feedback_text(request),
                top_k=request.top_k,
                candidate_pool_size=request.candidate_pool_size,
                complete_pool500=decision["action"] == "rerecall_pool500",
            )
        except Exception:
            decision = _feed_decision("fallback_cached_or_cold", "feed_refresh_unavailable", fallback_reason="feed_refresh_unavailable")
            return self._response(request, state, decision, candidate_count=len(state.display.get("items", [])), fallback_used=True)

        display = dict(result.display)
        display["session_id"] = state.session_id
        display["user_id"] = state.user_id
        state.display = validate_public_display_payload(display)
        state.display_revision += 1
        state.seen_item_ids = set(state.seen_item_ids or set()) | set(_display_item_ids(state.display))
        return self._response(request, state, decision, candidate_count=result.candidate_count, fallback_used=result.fallback_used)

    def _state_for_session(self, session_id: str) -> FeedSessionState:
        state = self.feed_states.get(session_id)
        if state is not None:
            return state
        session = self.sessions.get(session_id)
        if session is None:
            raise self.not_found_error(session_id)
        if not session.turns:
            raise ValueError("Feed refresh requires an initial display before structured behavior events")
        display = build_display_record(session.turns[-1], session)
        state = FeedSessionState(session_id=session_id, user_id=session.user_id, display=display)
        self.feed_states[session_id] = state
        return state

    def _apply_event_to_state(self, state: FeedSessionState, request: HomeFeedEventRequest) -> None:
        if request.item_id:
            state.seen_item_ids = set(state.seen_item_ids or set()) | {request.item_id}
        if request.event_type == "like" and request.item_id:
            state.liked_item_ids = set(state.liked_item_ids or set()) | {request.item_id}
        if request.event_type == "dislike" and request.item_id:
            state.disliked_item_ids = set(state.disliked_item_ids or set()) | {request.item_id}
        if request.event_type == "show_different":
            state.show_different_count += 1
        elif request.event_type in {"like", "dislike", "search"}:
            state.show_different_count = 0

    def _response(
        self,
        request: HomeFeedEventRequest,
        state: FeedSessionState,
        decision: dict[str, Any],
        *,
        candidate_count: int,
        fallback_used: bool,
    ) -> dict[str, Any]:
        trace_id = request.event_id or str(uuid4())
        self.decision_traces.append({
            "trace_id": trace_id,
            "session_id": request.session_id,
            "event_type": request.event_type,
            "action": decision["action"],
            "reason_code": decision["reason_code"],
            "fallback_reason": decision.get("fallback_reason"),
            "display_revision": state.display_revision,
            "candidate_count": candidate_count,
        })
        return {
            "session_id": request.session_id,
            "request_id": trace_id,
            "display_revision": state.display_revision,
            "decision": decision,
            "display": state.display,
            "items": list(state.display.get("items", [])),
            "item_count": len(state.display.get("items", [])),
            "candidate_count": candidate_count,
            "fallback_used": bool(fallback_used or decision.get("fallback_reason")),
            "public_message": _feed_public_message(decision),
        }


class RecommendationFacade:
    """Recommendation seam for public sequence-based recommendation responses."""

    def __init__(self, online_recommender: Any) -> None:
        self.online_recommender = online_recommender

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


def _feed_decision(action: str, reason_code: str, *, fallback_reason: str | None = None) -> dict[str, Any]:
    return {
        "action": action,
        "decision_source": "feed_refresh_policy",
        "reason_code": reason_code,
        "fallback_reason": fallback_reason,
    }


def _display_item_ids(display: dict[str, Any]) -> list[str]:
    item_ids: list[str] = []
    for item in display.get("items", []) if isinstance(display.get("items"), list) else []:
        if not isinstance(item, dict):
            continue
        item_id = item.get("parent_asin") or item.get("item_id")
        if item_id:
            item_ids.append(str(item_id))
    return item_ids


def _feed_user_sequence(state: FeedSessionState) -> dict[str, Any]:
    liked = sorted(state.liked_item_ids or set())
    seen = sorted(state.seen_item_ids or set())
    return {
        "user_id": state.user_id,
        "recent_item_sequence": seen[-50:],
        "recent_positive_item_sequence": liked[-20:],
    }


def _feed_feedback_text(request: HomeFeedEventRequest) -> str | None:
    if request.event_type == "search" and request.query:
        return request.query
    if request.event_type == "like":
        return "show more similar items"
    if request.event_type == "dislike":
        return "avoid this item and show a different direction"
    if request.event_type == "show_different":
        return "show me something different"
    if request.event_type == "dwell" and (request.dwell_ms or 0) >= 3000:
        return "slightly prefer similar items"
    return None


def _feed_public_message(decision: dict[str, Any]) -> str:
    action = decision.get("action")
    if action == "rerecall_pool500":
        return "已根据新的行为意图从候选池刷新推荐。"
    if action == "rerank_existing":
        return "已根据你的行为反馈调整当前推荐顺序。"
    if action == "fallback_cached_or_cold":
        return "当前推荐已保持稳定展示，稍后可继续刷新。"
    return "已记录行为信号，当前推荐保持不变。"


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
