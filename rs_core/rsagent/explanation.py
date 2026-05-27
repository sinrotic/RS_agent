from __future__ import annotations

import re
from typing import Any

from rs_core.display.builder import item_to_display_card
from rs_core.rsagent.schema import AgentSession, AgentTurn

NO_PRIOR_RECOMMENDATION_TEXT = "我现在还没有可以解释的最近推荐。你可以先让我推荐一些商品，然后再问为什么推荐其中某一件。"
STALE_RECOMMENDATION_TEXT = "我只能解释最近一次推荐列表里的商品。"


def build_recommendation_explanation(session: AgentSession, item_id: str | None = None) -> str:
    turn = latest_recommendation_turn(session)
    if turn is None:
        return NO_PRIOR_RECOMMENDATION_TEXT

    items = _display_safe_items(turn)
    target_id = item_id or _first_item_id(items)
    item = _item_by_id(items, target_id)
    if item is None:
        return STALE_RECOMMENDATION_TEXT

    title = _clean_text(item.get("title"))
    item_label = f"{title}（{item['parent_asin']}）" if title else f"商品 {item['parent_asin']}"
    rag_reason = _rag_reason(turn, item["parent_asin"])
    if rag_reason:
        return f"最近一次推荐列表里推荐{item_label}，主要因为{rag_reason}。"
    reasons = _public_reasons(item)
    if reasons:
        return f"最近一次推荐列表里推荐{item_label}，主要因为{'；'.join(reasons)}。"
    return f"推荐{item_label}，因为它仍在最近一次推荐列表中，并且商品信息可以安全展示给你。"


def latest_recommendation_turn(session: AgentSession) -> AgentTurn | None:
    for turn in reversed(session.turns):
        if _display_safe_items(turn):
            return turn
    return None


def requested_item_id(text: str) -> str | None:
    match = re.search(r"\bitem_id\s*=\s*([^\s,，。；;]+)", text)
    if match:
        return match.group(1).strip()
    return None


def _display_safe_items(turn: AgentTurn) -> list[dict[str, Any]]:
    safe_items: list[dict[str, Any]] = []
    for item in turn.recommendation.final_items:
        card = item_to_display_card(item)
        if card:
            safe_items.append(card.to_dict())
    return safe_items


def _item_by_id(items: list[dict[str, Any]], item_id: str | None) -> dict[str, Any] | None:
    if not item_id:
        return None
    for item in items:
        if item.get("parent_asin") == item_id:
            return item
    return None


def _first_item_id(items: list[dict[str, Any]]) -> str | None:
    if not items:
        return None
    parent_asin = items[0].get("parent_asin")
    return str(parent_asin) if parent_asin else None


def _rag_reason(turn: AgentTurn, item_id: str) -> str | None:
    context = turn.rag_context or {}
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    if metadata.get("evidence_mode") != "explain":
        return None
    evidence = context.get("evidence") if isinstance(context.get("evidence"), list) else []
    texts = [
        _clean_text(row.get("text"))
        for row in evidence
        if isinstance(row, dict) and row.get("item_id") == item_id and row.get("field") in {"title", "category", "description", "summary"}
    ]
    texts = [text for text in texts if text]
    if not texts:
        return None
    metadata["consumed_by_explanation"] = True
    turn.diagnostics.setdefault("rag", {})["consumed_by_explanation"] = True
    return "商品信息显示" + "，".join(texts[:2])


def _public_reasons(item: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    category = _clean_text(item.get("category"))
    summary = _clean_text(item.get("summary"))
    features = [_clean_text(feature) for feature in item.get("features", [])]
    features = [feature for feature in features if feature]
    store = _clean_text(item.get("store"))
    rating = _clean_text(item.get("rating"))
    price = _clean_text(item.get("price"))

    if category:
        reasons.append(f"它属于你正在浏览的{category}类目")
    if summary:
        reasons.append(summary)
    if features:
        reasons.append("包含" + "、".join(features[:3]) + "等商品特点")
    if store:
        reasons.append(f"来自{store}")
    if rating:
        reasons.append(f"展示评分为{rating}")
    if price:
        reasons.append(f"价格信息为{price}")
    return reasons[:4]


def _clean_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None
