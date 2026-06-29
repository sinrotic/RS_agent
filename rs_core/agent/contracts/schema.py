from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from rs_core.common.recsys_types import AgentDecision


INTENT_RECOMMEND_REQUEST = "recommend_request"
INTENT_PREFERENCE_FEEDBACK = "preference_feedback"
INTENT_ASK_EXPLANATION = "ask_explanation"
INTENT_CLARIFICATION_ANSWER = "clarification_answer"
INTENT_UNSUPPORTED = "unsupported"

ACTION_RECOMMEND_ITEMS = "recommend_items"
ACTION_ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
ACTION_EXPLAIN_RECOMMENDATION = "explain_recommendation"
ACTION_REVISE_RECOMMENDATION = "revise_recommendation"

DIALOGUE_PLAN_INTENTS = frozenset({
    INTENT_RECOMMEND_REQUEST,
    INTENT_PREFERENCE_FEEDBACK,
    INTENT_ASK_EXPLANATION,
    INTENT_CLARIFICATION_ANSWER,
    INTENT_UNSUPPORTED,
})
DIALOGUE_PLAN_ACTIONS = frozenset({
    ACTION_RECOMMEND_ITEMS,
    ACTION_ASK_CLARIFYING_QUESTION,
    ACTION_EXPLAIN_RECOMMENDATION,
    ACTION_REVISE_RECOMMENDATION,
})


def _jsonable(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


@dataclass
class FeedbackConstraints:
    liked_item_ids: set[str] = field(default_factory=set)
    disliked_item_ids: set[str] = field(default_factory=set)
    disliked_categories: set[str] = field(default_factory=set)
    preferred_categories: dict[str, float] = field(default_factory=dict)
    preferred_sources: dict[str, float] = field(default_factory=dict)
    preferred_keywords: dict[str, float] = field(default_factory=dict)
    disliked_keywords: dict[str, float] = field(default_factory=dict)
    max_price: float | None = None
    use_cases: dict[str, float] = field(default_factory=dict)
    filter_prior_turn_items: bool = False
    item_feedback_events: list[dict[str, Any]] = field(default_factory=list)
    unsupported_free_text: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class RewardEvidence:
    holdout_hits: list[str] = field(default_factory=list)
    feedback_constraints_satisfied: dict[str, bool] = field(default_factory=dict)
    item_sources: dict[str, list[str]] = field(default_factory=dict)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    unsupported_explanation_claims: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class AgentReward:
    total: float
    recommendation_quality: float
    feedback_alignment: float
    explanation_faithfulness: float
    risk_penalty: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DISPLAY_SCHEMA_VERSION = "rs_agent_display_v1"


@dataclass
class ConversationState:
    last_intent: str = ""
    last_agent_action: str = ""
    pending_clarification: str = ""
    clarification_history: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class UserPreferenceProfile:
    liked_item_ids: list[str] = field(default_factory=list)
    disliked_item_ids: list[str] = field(default_factory=list)
    disliked_categories: list[str] = field(default_factory=list)
    preferred_categories: dict[str, float] = field(default_factory=dict)
    preferred_sources: dict[str, float] = field(default_factory=dict)
    preferred_keywords: dict[str, float] = field(default_factory=dict)
    disliked_keywords: dict[str, float] = field(default_factory=dict)
    max_price: float | None = None
    use_cases: dict[str, float] = field(default_factory=dict)
    updated_turn_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class ArchivedTurnSummary:
    turn_index: int
    user_input: str = ""
    assistant_response: str = ""
    intent: str | None = None
    agent_action: str | None = None
    item_ids: list[str] = field(default_factory=list)
    fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class ItemDisplayCard:
    parent_asin: str
    title: str | None = None
    category: str | None = None
    price: float | str | None = None
    rating: float | str | None = None
    store: str | None = None
    features: list[str] = field(default_factory=list)
    description: str | None = None
    image_url: str | None = None
    badges: list[str] = field(default_factory=list)
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass
class DisplayResponse:
    session_id: str
    user_id: str
    turn_index: int
    assistant_message: str
    items: list[ItemDisplayCard]
    feedback_actions: list[dict[str, str]] = field(default_factory=list)
    ui_state: dict[str, Any] = field(default_factory=dict)
    schema_version: str = DISPLAY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "turn_index": self.turn_index,
            "assistant_message": self.assistant_message,
            "items": [item.to_dict() for item in self.items],
            "feedback_actions": _jsonable(self.feedback_actions),
            "ui_state": _jsonable(self.ui_state),
        }


@dataclass
class AgentTurn:
    turn_index: int
    user_input: str
    feedback_constraints: FeedbackConstraints
    recommendation: AgentDecision
    candidates: list[dict[str, Any]]
    ranking: list[dict[str, Any]]
    fallback_used: bool
    diagnostics: dict[str, Any]
    rag_context: dict[str, Any] | None = None
    assistant_response: str = ""
    reward_evidence: RewardEvidence = field(default_factory=RewardEvidence)
    reward: AgentReward | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("rag_context", None)
        payload["feedback_constraints"] = self.feedback_constraints.to_dict()
        payload["recommendation"] = self.recommendation.to_dict()
        payload["reward_evidence"] = self.reward_evidence.to_dict()
        payload["reward"] = self.reward.to_dict() if self.reward else None
        return _jsonable(payload)


@dataclass
class AgentSession:
    session_id: str
    user_id: str
    active_constraints: FeedbackConstraints = field(default_factory=FeedbackConstraints)
    conversation_state: ConversationState = field(default_factory=ConversationState)
    turns: list[AgentTurn] = field(default_factory=list)
    runtime_trace: list[dict[str, Any]] = field(default_factory=list)
    session_summary: dict[str, Any] = field(default_factory=dict)
    user_profile: UserPreferenceProfile = field(default_factory=UserPreferenceProfile)
    archived_turn_summaries: list[ArchivedTurnSummary] = field(default_factory=list)

    def prior_turn_items(self) -> set[str]:
        items: set[str] = set()
        for summary in self.archived_turn_summaries:
            items.update(str(item_id) for item_id in summary.item_ids if item_id)
        for turn in self.turns:
            if not turn.recommendation.final_items:
                continue
            items.update(str(item.get("parent_asin")) for item in turn.recommendation.final_items if item.get("parent_asin"))
        return items

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "active_constraints": self.active_constraints.to_dict(),
            "conversation_state": self.conversation_state.to_dict(),
            "runtime_trace": _jsonable(self.runtime_trace),
            "session_summary": _jsonable(self.session_summary),
            "user_profile": self.user_profile.to_dict(),
            "archived_turn_summaries": [summary.to_dict() for summary in self.archived_turn_summaries],
            "turns": [turn.to_dict() for turn in self.turns],
        }


@dataclass
class RecommendationTurnResult:
    candidates: list[Any]
    ranking: Any
    decision: AgentDecision
    fallback_used: bool
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [_jsonable(asdict(candidate)) for candidate in self.candidates],
            "ranking": self.ranking.to_dict() if hasattr(self.ranking, "to_dict") else asdict(self.ranking),
            "decision": self.decision.to_dict(),
            "fallback_used": self.fallback_used,
            "diagnostics": _jsonable(self.diagnostics),
        }
