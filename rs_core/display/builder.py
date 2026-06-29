from __future__ import annotations

import re
from typing import Any

from rs_core.display.public_safety import sanitize_public_text
from rs_core.agent.contracts.schema import AgentSession, AgentTurn, DisplayResponse, ItemDisplayCard

DISPLAY_RECORD_ALLOWED_KEYS = {
    "schema_version",
    "session_id",
    "user_id",
    "turn_index",
    "assistant_message",
    "items",
    "feedback_actions",
    "ui_state",
}
DISPLAY_ITEM_ALLOWED_KEYS = {
    "parent_asin",
    "title",
    "category",
    "price",
    "rating",
    "store",
    "features",
    "description",
    "image_url",
    "badges",
    "summary",
}
PUBLIC_TIMELINE_ALLOWED_KEYS = {
    "schema_version",
    "session_id",
    "user_id",
    "events",
}
PUBLIC_TIMELINE_EVENT_ALLOWED_KEYS = {
    "public_event_id",
    "event_type",
    "turn_index",
    "user_message",
    "assistant_message",
    "display_response_index",
}
PUBLIC_FORBIDDEN_KEYS = {
    "agent_boost",
    "agent_runtime_trace",
    "base_score",
    "coarse_score",
    "deepfm_score",
    "deepfm_shadow_score",
    "feature_contract",
    "feedback_source",
    "final_score",
    "fine_score",
    "model_path",
    "rank_movement",
    "rerank_score",
    "score_trace",
    "ranking_replacement_allowed",
    "agent_tool_events",
    "agent_tool_summary",
    "agent_tool_trace",
    "archived_turn_summaries",
    "context_budget",
    "context_bundle",
    "diagnostics",
    "diagnostics_path",
    "long_memory",
    "long_memory_profile",
    "long_memory_snapshot",
    "memory_agent_shadow",
    "memory_agent_summary",
    "memory_agent_support",
    "memory_agent_trace",
    "memory_entries",
    "memory_recall",
    "memory_snapshot",
    "memory_store",
    "private_memory_recall",
    "typed_memory_entries",
    "typed_memory_recall",
    "feedback_source",
    "internal",
    "rag",
    "rag_context",
    "rag_evidence",
    "raw_evidence",
    "raw_export_trace_path",
    "ranking_evidence_path",
    "recall_source",
    "reward",
    "reward_evidence",
    "score",
    "session_summary",
    "snippet",
    "snippets",
    "supporting_snippets",
    "source",
    "sources",
    "tool",
    "tool_call",
    "tool_result",
    "trace_ref",
    "training",
    "training_samples",
    "user_profile",
}
PUBLIC_FORBIDDEN_TERMS = {
    "agent_runtime_trace",
    "deepfm_shadow_score",
    "deepfm_score",
    "feature_contract",
    "model_path",
    "ranking_replacement_allowed",
    "agent_tool_trace",
    "agentic_recall_candidates",
    "build_recommendation_slate",
    "catalog_constraint_search",
    "context bundle",
    "context_budget",
    "deepfm_rank_candidates",
    "feature_rows",
    "feedback_source",
    "final_score",
    "get_item_evidence",
    "internal",
    "itemcf",
    "bm25",
    "hybrid_milvus",
    "hybrid_bm25",
    "milvus",
    "retriever",
    "sqlite_bm25",
    "vector backend",
    "rag tool",
    "get_user_context",
    "diagnostic",
    "long memory",
    "long_memory",
    "memory agent",
    "memory agent shadow",
    "memory agent support",
    "memory_agent",
    "memory entry",
    "memory recall",
    "memory snapshot",
    "memory store",
    "raw export trace",
    "base_score",
    "coarse_score",
    "fine_score",
    "match_specific_need_in_pool",
    "rag context",
    "rag evidence",
    "raw evidence",
    "raw snippet",
    "raw snippets",
    "supporting snippets",
    "supporting-snippets",
    "rag output",
    "rag result",
    "rag value",
    "raw_export_trace",
    "rank_candidates",
    "recall source",
    "ranking evidence",
    "ranking_evidence",
    "raw score_trace",
    "record_user_feedback",
    "rerank_for_browsing",
    "retrieve_candidates",
    "reward",
    "score",
    "reward_evidence",
    "session summary",
    "snippet",
    "snippets",
    "source",
    "tool output",
    "tool result",
    "tool value",
    "training",
    "training_samples",
    "trace_ref",
    "typed memory",
    "user_profile",
}
DISPLAY_ITEM_TEXT_KEYS = {
    "title",
    "category",
    "store",
    "features",
    "description",
    "summary",
}
GENERIC_PUBLIC_TEXT_TERMS = {"source", "training", "reward"}

DEFAULT_FEEDBACK_ACTIONS = [
    {"type": "like", "label": "喜欢"},
    {"type": "dislike", "label": "不喜欢"},
    {"type": "show_different", "label": "换一批"},
    {"type": "why", "label": "为什么推荐"},
]

def build_display_response(turn: AgentTurn, session: AgentSession) -> DisplayResponse:
    return DisplayResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        turn_index=turn.turn_index,
        assistant_message=turn.assistant_response or turn.recommendation.agent_explanation,
        items=[card for item in turn.recommendation.final_items if (card := item_to_display_card(item))],
        feedback_actions=list(DEFAULT_FEEDBACK_ACTIONS),
        ui_state={
            "image_fallback_enabled": True,
            "can_request_more": True,
        },
    )


def build_display_record(turn: AgentTurn, session: AgentSession) -> dict[str, Any]:
    return validate_public_display_payload(build_display_response(turn, session).to_dict())


def session_to_display_records(session: AgentSession) -> list[dict[str, Any]]:
    return [build_display_record(turn, session) for turn in session.turns]


def build_public_timeline(session: AgentSession, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source_events = events or []
    timeline_events: list[dict[str, Any]] = []
    for index, turn in enumerate(session.turns):
        source_event = source_events[index] if index < len(source_events) and isinstance(source_events[index], dict) else {}
        timeline_events.append(
            {
                "public_event_id": f"{session.session_id}:turn:{turn.turn_index}",
                "event_type": _public_event_type(source_event.get("type")),
                "turn_index": turn.turn_index,
                "user_message": sanitize_public_text(turn.user_input).text,
                "assistant_message": sanitize_public_text(turn.assistant_response or turn.recommendation.agent_explanation).text,
                "display_response_index": index,
            }
        )
    return validate_public_timeline_payload(
        {
            "schema_version": "rs_agent_public_timeline_v1",
            "session_id": session.session_id,
            "user_id": session.user_id,
            "events": timeline_events,
        }
    )


def validate_public_display_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _reject_forbidden_public_payload(payload)
    _require_allowed_keys(payload, DISPLAY_RECORD_ALLOWED_KEYS, "display")
    _validate_display_scalar_fields(payload)
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("display.items must be a list")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("display.items entries must be objects")
        _require_allowed_keys(item, DISPLAY_ITEM_ALLOWED_KEYS, "display.items")
        _validate_display_item_shape(item)
    _validate_feedback_actions(payload.get("feedback_actions", []))
    _validate_ui_state(payload.get("ui_state", {}))
    return payload


def validate_public_timeline_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _reject_forbidden_public_payload(payload)
    _require_allowed_keys(payload, PUBLIC_TIMELINE_ALLOWED_KEYS, "timeline")
    events = payload.get("events", [])
    if not isinstance(events, list):
        raise ValueError("timeline.events must be a list")
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("timeline.events entries must be objects")
        _require_allowed_keys(event, PUBLIC_TIMELINE_EVENT_ALLOWED_KEYS, "timeline.events")
        _validate_timeline_event_shape(event)
        if "public_event_id" not in event or "trace_ref" in event:
            raise ValueError("timeline events must use public_event_id and must not expose trace_ref")
    return payload


def item_to_display_card(item: dict[str, Any]) -> ItemDisplayCard | None:
    parent_asin = _string_value(_first_value(item, "parent_asin", "item_id"))
    if not parent_asin:
        return None
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    title = _string_value(_first_value(item, "title_clean", "title", metadata=metadata))
    category = _string_value(_first_value(item, "main_category", "category", metadata=metadata))
    image_url = _string_value(_first_value(item, "image_url", "image", "img_url", metadata=metadata))
    features = _list_value(_first_value(item, "features", "feature", "bullets", metadata=metadata))
    return ItemDisplayCard(
        parent_asin=parent_asin,
        title=title,
        category=category,
        price=_first_value(item, "price", "price_display", metadata=metadata),
        rating=_first_value(item, "rating", "average_rating", "stars", metadata=metadata),
        store=_string_value(_first_value(item, "store", "brand", metadata=metadata)),
        features=features,
        description=_string_value(_first_value(item, "description", "product_description", metadata=metadata)),
        image_url=image_url,
        badges=_badges(item, image_url),
        summary=_string_value(_first_value(item, "summary", "short_description", metadata=metadata)),
    )


def _public_event_type(value: Any) -> str:
    event_type = str(value).strip().lower() if value not in (None, "") else "turn"
    return event_type if event_type in {"chat", "feedback", "turn"} else "turn"


def _require_allowed_keys(payload: dict[str, Any], allowed_keys: set[str], label: str) -> None:
    extra_keys = sorted(set(payload) - allowed_keys)
    if extra_keys:
        raise ValueError(f"{label} contains non-public fields: {extra_keys}")


def _validate_display_scalar_fields(payload: dict[str, Any]) -> None:
    string_fields = ("schema_version", "session_id", "user_id", "assistant_message")
    for field in string_fields:
        if not isinstance(payload.get(field), str):
            raise ValueError(f"display.{field} must be a string")
    if not isinstance(payload.get("turn_index"), int) or isinstance(payload.get("turn_index"), bool):
        raise ValueError("display.turn_index must be an integer")


def _validate_timeline_event_shape(event: dict[str, Any]) -> None:
    string_fields = ("public_event_id", "event_type", "user_message", "assistant_message")
    for field in string_fields:
        if not isinstance(event.get(field), str):
            raise ValueError(f"timeline.events {field} must be a string")
    for field in ("turn_index", "display_response_index"):
        if not isinstance(event.get(field), int) or isinstance(event.get(field), bool):
            raise ValueError(f"timeline.events {field} must be an integer")


def _validate_display_item_shape(item: dict[str, Any]) -> None:
    if not isinstance(item.get("parent_asin"), str) or not item["parent_asin"]:
        raise ValueError("display.items parent_asin must be a non-empty string")
    for key in (DISPLAY_ITEM_TEXT_KEYS - {"features"}) | {"image_url"}:
        if item.get(key) is not None and not isinstance(item.get(key), str):
            raise ValueError(f"display.items {key} must be a string or null")
    for key in {"price", "rating"}:
        if item.get(key) is not None and not isinstance(item.get(key), (int, float, str)):
            raise ValueError(f"display.items {key} must be scalar or null")
    for key in {"features", "badges"}:
        value = item.get(key, [])
        if not isinstance(value, list) or any(not isinstance(child, str) for child in value):
            raise ValueError(f"display.items {key} must be a list of strings")


def _validate_feedback_actions(actions: Any) -> None:
    if not isinstance(actions, list):
        raise ValueError("display.feedback_actions must be a list")
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("display.feedback_actions entries must be objects")
        _require_allowed_keys(action, {"type", "label"}, "display.feedback_actions")
        if not isinstance(action.get("type"), str) or not isinstance(action.get("label"), str):
            raise ValueError("display.feedback_actions type and label must be strings")


def _validate_ui_state(ui_state: Any) -> None:
    if not isinstance(ui_state, dict):
        raise ValueError("display.ui_state must be an object")
    allowed_keys = {"image_fallback_enabled", "can_request_more"}
    for key, value in ui_state.items():
        raw_key = str(key).strip()
        normalized_key = _normalize_public_key(raw_key)
        if raw_key not in allowed_keys or normalized_key in PUBLIC_FORBIDDEN_KEYS:
            raise ValueError(f"display.ui_state contains non-public field: {key}")
        if isinstance(value, (dict, list)):
            raise ValueError("display.ui_state values must be scalar")


def _normalize_public_key(key: Any) -> str:
    raw_key = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key).strip())
    return re.sub(r"[\s\-]+", "_", raw_key.lower())


def _reject_forbidden_public_payload(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = _normalize_public_key(key)
            if normalized_key in PUBLIC_FORBIDDEN_KEYS:
                raise ValueError(f"public payload contains forbidden field: {key}")
            _reject_forbidden_public_payload(child, (*path, normalized_key))
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden_public_payload(child, (*path, "[]"))
    elif isinstance(value, str):
        if _is_user_message_path(path):
            return
        normalized_value = value.lower()
        for term in PUBLIC_FORBIDDEN_TERMS:
            if term in normalized_value and not _is_allowed_public_text_term(term, path):
                raise ValueError(f"public payload contains forbidden term: {term}")



def _is_public_free_text_path(path: tuple[str, ...]) -> bool:
    return path == ("assistant_message",) or (
        len(path) >= 3 and path[-3] == "events" and path[-2] == "[]" and path[-1] == "assistant_message"
    ) or (
        len(path) >= 3 and path[-3] == "items" and path[-2] == "[]" and path[-1] in DISPLAY_ITEM_TEXT_KEYS
    ) or (
        len(path) >= 4 and path[-4] == "items" and path[-3] == "[]" and path[-2] in DISPLAY_ITEM_TEXT_KEYS and path[-1] == "[]"
    )


def _is_user_message_path(path: tuple[str, ...]) -> bool:
    return len(path) >= 3 and path[-3] == "events" and path[-2] == "[]" and path[-1] == "user_message"


def _is_allowed_public_text_term(term: str, path: tuple[str, ...]) -> bool:
    return term in GENERIC_PUBLIC_TEXT_TERMS and _is_public_free_text_path(path)


def _first_value(item: dict[str, Any], *keys: str, metadata: dict[str, Any] | None = None) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    metadata = metadata or {}
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _string_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _list_value(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _badges(item: dict[str, Any], image_url: str | None) -> list[str]:
    badges: list[str] = []
    sources = item.get("sources", [])
    if isinstance(sources, list) and len(sources) > 1:
        badges.append("blended_signal")
    if _has_feedback_match(sources):
        badges.append("matches_feedback")
    if not image_url:
        badges.append("missing_image")
    return badges


def _has_feedback_match(sources: Any) -> bool:
    if not isinstance(sources, list):
        return False
    return any(str(source).startswith("feedback_") for source in sources)
