from __future__ import annotations

from typing import Any

from rs_core.rsagent.schema import AgentSession, AgentTurn, DisplayResponse, ItemDisplayCard

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
    "agent_runtime_trace",
    "diagnostics",
    "diagnostics_path",
    "raw_export_trace_path",
    "ranking_evidence_path",
    "trace_ref",
    "reward_evidence",
    "training_samples",
}
PUBLIC_FORBIDDEN_TERMS = {
    "agent_runtime_trace",
    "diagnostic",
    "raw export trace",
    "raw_export_trace",
    "ranking evidence",
    "ranking_evidence",
    "reward",
    "source",
    "training",
    "trace_ref",
}

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
                "user_message": turn.user_input,
                "assistant_message": turn.assistant_response or turn.recommendation.agent_explanation,
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
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("display.items must be a list")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("display.items entries must be objects")
        _require_allowed_keys(item, DISPLAY_ITEM_ALLOWED_KEYS, "display.items")
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


def _reject_forbidden_public_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized_key = str(key).lower()
            if normalized_key in PUBLIC_FORBIDDEN_KEYS:
                raise ValueError(f"public payload contains forbidden field: {key}")
            _reject_forbidden_public_payload(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden_public_payload(child)
    elif isinstance(value, str):
        normalized_value = value.lower()
        for term in PUBLIC_FORBIDDEN_TERMS:
            if term in normalized_value:
                raise ValueError(f"public payload contains forbidden term: {term}")


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
