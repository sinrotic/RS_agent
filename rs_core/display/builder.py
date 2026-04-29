from __future__ import annotations

from typing import Any

from rs_core.rsagent.schema import AgentSession, AgentTurn, DisplayResponse, ItemDisplayCard

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
    return build_display_response(turn, session).to_dict()


def session_to_display_records(session: AgentSession) -> list[dict[str, Any]]:
    return [build_display_record(turn, session) for turn in session.turns]


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
        badges.append("multi_source")
    if _has_feedback_match(sources):
        badges.append("matches_feedback")
    if not image_url:
        badges.append("missing_image")
    return badges


def _has_feedback_match(sources: Any) -> bool:
    if not isinstance(sources, list):
        return False
    return any(str(source).startswith("feedback_") for source in sources)
