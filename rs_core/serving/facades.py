from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from rs_core.display import build_display_record, build_public_timeline
from rs_core.rsagent.context import ensure_session_context_state
from rs_core.rsagent.long_memory import (
    LongMemoryConfig,
    LongMemoryStore,
    hydrate_session_from_long_memory,
    snapshot_session_long_memory,
)
from rs_core.rsagent.schema import AgentSession
from rs_core.serving.schema import RecallRequest, RecommendFromSequenceRequest

PUBLIC_RESPONSE_FORBIDDEN_FIELDS = frozenset({
    "diagnostics",
    "source_scores",
    "tool_traces",
})

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
    ) -> None:
        self.env = env
        self.sessions = sessions
        self.session_events = session_events
        self.long_memory_config = long_memory_config
        self.long_memory_store = long_memory_store
        self.not_found_error = not_found_error

    def start_session(self, user_id: str | None = None) -> str:
        session_id = str(uuid4())
        session_user_id = _session_user_id(user_id, session_id)
        session = self.env.start_session(user_id=session_user_id, session_id=session_id)
        self._hydrate_long_memory(session)
        self.sessions[session_id] = session
        self.session_events[session_id] = []
        return session_id

    def chat(self, session_id: str, message: str) -> FacadeChatResult:
        session = self.session(session_id)
        turn = self.env.converse(session, message)
        self.session_events[session_id].append({"type": "chat"})
        self._persist_long_memory(session)
        return FacadeChatResult(session_id=session_id, display=build_display_record(turn, session))

    def feedback(self, session_id: str, action_type: str, item_id: str | None = None, comment: str | None = None) -> FacadeChatResult:
        session = self.session(session_id)
        prompt = feedback_prompt(action_type, item_id, comment)
        turn = self.env.converse(session, prompt, explanation_item_id=item_id if action_type.strip().lower() == "why" else None)
        self.session_events[session_id].append({
            "type": "feedback",
            "action_type": action_type.strip().lower(),
            "item_id": item_id,
            "comment": comment,
        })
        self._persist_long_memory(session)
        return FacadeChatResult(session_id=session_id, display=build_display_record(turn, session))

    def session(self, session_id: str) -> AgentSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise self.not_found_error(session_id)
        return session

    def export_session(self, session_id: str) -> dict[str, Any]:
        session = self.session(session_id)
        display_responses = [build_display_record(turn, session) for turn in session.turns]
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "turn_count": len(session.turns),
            "public_timeline": build_public_timeline(session, self.session_events[session_id]),
            "display_responses": display_responses,
        }

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
