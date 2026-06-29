from __future__ import annotations

import re
from typing import Any

from rs_core.common.recsys_types import MergedCandidate
from rs_core.agent.feedback import constraint_filter_tool
from rs_core.agent.contracts.schema import FeedbackConstraints

_KEYWORD_ALIASES = {
    "cheap": ["cheap", "budget", "affordable", "low cost", "inexpensive"],
    "commute": ["commute", "commuter", "travel", "portable", "通勤"],
    "gift": ["gift", "present", "gifting", "礼物", "送礼"],
    "wired": ["wired", "cable", "corded"],
    "headphones": ["headphones", "headphone", "earbuds", "earphones", "耳机"],
}
_NEGATIVE_PATTERNS = ("not ", "avoid ", "exclude ", "don't want ", "do not want ", "不要", "不想要", "排除")


def parse_constraint_filter_input(text: str) -> FeedbackConstraints:
    constraints = FeedbackConstraints()
    normalized = text.strip()
    lowered = normalized.lower()
    for keyword, aliases in _KEYWORD_ALIASES.items():
        if not any(_contains_alias(lowered, alias) for alias in aliases):
            continue
        if _is_negative_context(lowered, aliases):
            if keyword in {"wired"}:
                constraints.disliked_keywords[keyword] = 1.0
            else:
                constraints.disliked_categories.add(keyword)
        else:
            constraints.preferred_keywords[keyword] = 1.0
            if keyword in {"commute", "gift"}:
                constraints.use_cases[keyword] = 1.0
    price = _max_price(lowered)
    if price is not None:
        constraints.max_price = price
    return constraints


def apply_constraint_filter_tool(
    candidates: list[MergedCandidate],
    constraints: FeedbackConstraints | None,
    config: dict[str, Any] | None = None,
) -> tuple[list[MergedCandidate], dict[str, Any]]:
    policy = dict((config or {}).get("constraint_filter", {}) or {})
    if policy.get("enabled") is False:
        return candidates, {"constraint_filter_events": [], "constraint_filter_summary": _summary(0, 0, 0, False)}

    adapted_config = dict(config or {})
    if "min_candidates" in policy:
        adapted_config["constraint_filter_min_candidates"] = policy["min_candidates"]
    if "keyword_boost" in policy:
        adapted_config["feedback_keyword_boost"] = policy["keyword_boost"]
    if "keyword_penalty" in policy:
        adapted_config["feedback_keyword_penalty"] = policy["keyword_penalty"]

    filtered, diagnostics = constraint_filter_tool(candidates, constraints, adapted_config)
    events = _tool_events(diagnostics)
    diagnostics = dict(diagnostics)
    diagnostics["constraint_filter_events"] = events
    diagnostics["constraint_filter_summary"] = _summary(
        sum(1 for event in events if event["action"] == "filter"),
        sum(1 for event in events if event["action"] == "penalize"),
        sum(1 for event in events if event["action"] == "boost"),
        bool(diagnostics["constraint_filter_summary"]["over_filter_protection_applied"]),
    )
    return filtered, diagnostics


def _tool_events(diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    events = list(diagnostics.get("constraint_filter_events", []))
    for item_id, boost_events in diagnostics.get("boost_events", {}).items():
        for event in boost_events:
            if event.get("type") not in {"preferred_keyword", "disliked_keyword"}:
                continue
            action = "penalize" if event["type"] == "disliked_keyword" else "boost"
            events.append({
                "type": "constraint_filter",
                "action": action,
                "target_item_id": item_id,
                "reason": event["type"],
                "matched_value": event["matched_value"],
                "configured_value": event["configured_value"],
                "delta": event["boost"],
            })
    return events


def _summary(filtered_count: int, penalized_count: int, boosted_count: int, protected: bool) -> dict[str, Any]:
    return {
        "filtered_item_count": filtered_count,
        "penalized_item_count": penalized_count,
        "boosted_item_count": boosted_count,
        "over_filter_protected": protected,
    }



def _contains_alias(text: str, alias: str) -> bool:
    if re.search(r"[一-鿿]", alias):
        return alias in text
    return re.search(rf"(?<!\w){re.escape(alias.lower())}(?!\w)", text) is not None


def _is_negative_context(text: str, aliases: list[str]) -> bool:
    for alias in aliases:
        index = text.find(alias.lower())
        if index < 0 and re.search(r"[一-鿿]", alias):
            index = text.find(alias)
        if index < 0:
            continue
        prefix = text[max(0, index - 16):index]
        prefix = re.split(r"[,.;，。；]", prefix)[-1]
        if any(pattern in prefix for pattern in _NEGATIVE_PATTERNS):
            return True
    return False


def _max_price(text: str) -> float | None:
    match = re.search(r"(?:under|below|less than|低于|不超过|以内)\s*[$¥￥]?\s*(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return None

