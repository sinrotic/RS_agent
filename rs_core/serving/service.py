from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from rs_core.display import build_display_record
from rs_core.rsagent.schema import AgentSession
from rs_core.workflow.hybrid_environment import HybridRecommendationEnvironment

DEFAULT_CONFIG = "configs/hybrid_demo_electronics_1000_lopo_semantic_title.yaml"
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
    ) -> None:
        self.env = HybridRecommendationEnvironment.from_config(config, limit_users=limit_users, config_overrides=config_overrides)
        self.sessions: dict[str, AgentSession] = {}
        self.session_events: dict[str, list[dict[str, Any]]] = {}

    def start_session(self, user_id: str | None = None) -> str:
        session_id = str(uuid4())
        session = self.env.start_session(user_id=user_id, session_id=session_id)
        self.sessions[session_id] = session
        self.session_events[session_id] = []
        return session_id

    def chat(self, session_id: str, message: str) -> ChatResult:
        session = self._session(session_id)
        turn = self.env.converse(session, message)
        self.session_events[session_id].append({"type": "chat"})
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
        return ChatResult(session_id=session_id, display=build_display_record(turn, session))

    def get_agent_session(self, session_id: str) -> AgentSession:
        return self._session(session_id)

    def export_session(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        display_responses = [build_display_record(turn, session) for turn in session.turns]
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "turn_count": len(session.turns),
            "events": [
                {
                    **self.session_events[session_id][index],
                    "turn_index": turn.turn_index,
                    "user_input": turn.user_input,
                    "assistant_message": turn.assistant_response or turn.recommendation.agent_explanation,
                    "display_response_index": index,
                }
                for index, turn in enumerate(session.turns)
            ],
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
