from __future__ import annotations

import re
from typing import Any

from rs_core.display.builder import item_to_display_card
from rs_core.rsagent.schema import AgentSession, AgentTurn

NO_PRIOR_RECOMMENDATION_TEXT = "我现在还没有可以解释的最近推荐。你可以先让我推荐一些商品，然后再问为什么推荐其中某一件。"
STALE_RECOMMENDATION_TEXT = "我只能解释最近一次推荐列表里的商品。"
RAG_EXPLANATION_MAX_EVIDENCE = 2
RAG_EXPLANATION_MAX_TEXT_CHARS = 120


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
    item_label = _public_item_label(item, title)
    rag_reason = _rag_reason(turn, item["parent_asin"], item)
    if rag_reason:
        return f"我推荐{item_label}，主要是因为{rag_reason}。"
    reasons = _public_reasons(item)
    if reasons:
        return f"我推荐{item_label}，主要是因为{'；'.join(reasons)}。"
    return f"我推荐{item_label}，主要是因为它适合作为当前需求下的一个稳妥备选。"


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


def _rag_reason(turn: AgentTurn, item_id: str, display_item: dict[str, Any]) -> str | None:
    context = turn.rag_context or {}
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    if metadata.get("evidence_mode") != "explain":
        return None
    evidence = context.get("evidence") if isinstance(context.get("evidence"), list) else []
    evidence_fields = {
        str(row.get("field") or "")
        for row in evidence
        if isinstance(row, dict) and row.get("item_id") == item_id and row.get("field") in {"title", "category", "category_path", "description", "summary"}
    }
    if not evidence_fields:
        return None
    public_reasons = _public_reasons_for_fields(display_item, evidence_fields)
    if not public_reasons:
        return None
    return "商品信息显示" + "，".join(public_reasons[:RAG_EXPLANATION_MAX_EVIDENCE])


def _public_reasons_for_fields(item: dict[str, Any], evidence_fields: set[str]) -> list[str]:
    reasons: list[str] = []
    title = _clean_text(item.get("title")) or ""
    category = _clean_text(item.get("category")) or ""
    if "summary" in evidence_fields or "description" in evidence_fields:
        summary = _clean_text(item.get("summary")) or _clean_text(item.get("description"))
        if summary:
            reasons.append(_truncate_text(summary, RAG_EXPLANATION_MAX_TEXT_CHARS))
    if ("title" in evidence_fields or "category" in evidence_fields or "category_path" in evidence_fields) and title:
        reasons.append(_infer_public_use_case(title, category))
    elif category:
        reasons.append(f"它偏{category}场景，适合作为当前需求下的实用备选")
    return reasons


def _public_reasons(item: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    category = _clean_text(item.get("category"))
    summary = _clean_text(item.get("summary"))
    features = [_clean_text(feature) for feature in item.get("features", [])]
    features = [feature for feature in features if feature]
    price = _clean_text(item.get("price"))

    if summary:
        reasons.append(summary)
    elif title := _clean_text(item.get("title")):
        reasons.append(_infer_public_use_case(title, category or ""))
    elif category:
        reasons.append(f"它偏{category}场景，适合作为当前需求下的实用备选")
    if features:
        reasons.append("有" + "、".join(features[:2]) + "这些实用点")
    if price:
        reasons.append(f"价格是{price}，方便一起衡量预算")
    return reasons[:3]


def _public_item_label(item: dict[str, Any], title: str | None) -> str:
    parent_asin = _clean_text(item.get("parent_asin"))
    if not parent_asin:
        return _short_title(title) if title else "这件商品"
    short_title = _short_title(title) if title else "这件商品"
    if short_title == "这件商品":
        return parent_asin
    return f"{parent_asin}（{short_title}）"


def _short_title(title: str | None) -> str:
    if not title:
        return "这件商品"
    cleaned = re.sub(r"\s*\([^)]*\)", " ", title)
    cleaned = re.sub(r"\b\d+\s*(?:pack|pcs?|pieces|count|ct)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:white|black|clear|charcoal|latest release)\b", " ", cleaned, flags=re.IGNORECASE)
    parts = [part.strip(" -|,;:/") for part in re.split(r"\s[-|]\s|,\s*", cleaned) if part.strip(" -|,;:/")]
    candidates: list[str] = []
    for part in parts or [cleaned]:
        part = re.sub(r"\s+", " ", part).strip()
        part = re.sub(r"\s+with\s+.*$", "", part, flags=re.IGNORECASE).strip()
        part = re.sub(r"\s+for\s+.*$", "", part, flags=re.IGNORECASE).strip()
        part = re.sub(r"\s+by\s+.*$", "", part, flags=re.IGNORECASE).strip()
        if len(part) >= 4 and re.search(r"[A-Za-z一-鿿]", part):
            candidates.append(part)
    label = min(candidates, key=len) if candidates else cleaned.strip()
    return _truncate_text(label or title, 32)


def _infer_public_use_case(title: str, category: str) -> str:
    label = _short_title(title)
    context = _public_title_context(title, label)
    if context:
        return f"从名称看，{context}，适合作为当前需求下的具体备选"
    if label and label != "这件商品":
        return f"它对应{label}这类用途，可以作为当前需求下的具体备选"
    return "它适合作为当前需求下的实用备选"


def _public_title_context(title: str, label: str) -> str:
    if not title:
        return ""
    cleaned = re.sub(r"\s*\([^)]*\)", " ", title)
    cleaned = re.sub(r"\b\d+\s*(?:pack|pcs?|pieces|count|ct)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:white|black|clear|charcoal|latest release|made in)\b", " ", cleaned, flags=re.IGNORECASE)
    phrases = [part.strip(" -|,;:/") for part in re.split(r"\s[-|]\s|,\s*", cleaned) if part.strip(" -|,;:/")]
    useful_phrases = []
    for phrase in phrases:
        phrase = re.sub(r"\s+", " ", phrase).strip()
        if label and phrase.lower() == label.lower():
            continue
        if len(phrase) < 6 or not re.search(r"[A-Za-z一-鿿]", phrase):
            continue
        useful_phrases.append(_truncate_text(phrase, 42))
    if useful_phrases:
        return "、".join(useful_phrases[:2])
    if label and label != "这件商品":
        return f"它主要对应{label}"
    return ""


def _clean_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _truncate_text(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[:max_chars] + "..."
