from __future__ import annotations

import json
from typing import Any

from rs_core.simulation.model_client import SimulationModelUnavailableError
from rs_core.simulation.schema import RoleAction, RoleActionType, RoleState, SimulatedCustomerRole


class RolePolicy:
    def next_action(self, role: SimulatedCustomerRole, state: RoleState, display_response: dict[str, Any]) -> RoleAction:
        state.remember_display(display_response)
        items = display_response.get("items", [])
        assistant_message = str(display_response.get("assistant_message") or "")
        if not items:
            state.current_question = "Need more concrete options."
            return RoleAction.chat("Can you suggest a few concrete options for what I described? I do not have a specific product in mind yet.")

        best_item, best_score = self._best_item(role, items)
        best_id = str(best_item.get("parent_asin", "")) or None
        if not _assistant_explains_display_items(assistant_message, items):
            state.current_question = "Need item-specific reasons before accepting."
            return RoleAction.why(best_id)
        state.satisfaction = best_score

        if best_score >= 2.0:
            state.ready_to_accept = True
            return RoleAction.accept(best_id, "This matches my current goal.")

        if best_score >= 1.0 and role.decision_style in {"cautious", "explanation_first"}:
            state.current_question = "Need explanation before accepting."
            return RoleAction.why(best_id)

        if role.feedback_style == "exploratory":
            return RoleAction.feedback("show_different", best_id, "I want to compare a different direction.")

        if role.feedback_style == "critical":
            return RoleAction.feedback("dislike", best_id, "This does not match my constraints.")

        return RoleAction.feedback("show_different", best_id, "Please try a closer match.")

    def _best_item(self, role: SimulatedCustomerRole, items: list[dict[str, Any]]) -> tuple[dict[str, Any], float]:
        scored = [(item, self._score_item(role, item)) for item in items]
        return max(scored, key=lambda pair: pair[1])

    def _score_item(self, role: SimulatedCustomerRole, item: dict[str, Any]) -> float:
        text = " ".join(
            str(value or "")
            for value in [
                item.get("title"),
                item.get("category"),
                item.get("summary"),
                item.get("description"),
                " ".join(str(feature) for feature in item.get("features", [])),
            ]
        ).lower()
        score = 0.0
        for category in role.category_preferences:
            if category.lower() in text:
                score += 1.0
        for keyword in role.keyword_preferences:
            if keyword.lower() in text:
                score += 1.0
        for negative in role.negative_preferences:
            if negative.lower() in text:
                score -= 1.5
        if role.budget_sensitivity == "high" and _price_number(item.get("price")) is not None:
            price = _price_number(item.get("price")) or 0.0
            if price <= 50:
                score += 0.5
            elif price >= 150:
                score -= 0.75
        return score


class ModelDrivenRolePolicy:
    def __init__(self, client: Any, fallback_policy: RolePolicy | None = None, strict: bool = False) -> None:
        self.client = client
        self.fallback_policy = fallback_policy or RolePolicy()
        self.strict = strict

    def next_action(self, role: SimulatedCustomerRole, state: RoleState, display_response: dict[str, Any]) -> RoleAction:
        try:
            return self._next_model_action(role, state, display_response)
        except (SimulationModelUnavailableError, ValueError, json.JSONDecodeError, KeyError, TypeError) as exc:
            if self.strict:
                raise exc
            return self.fallback_policy.next_action(role, state, display_response)

    def _next_model_action(self, role: SimulatedCustomerRole, state: RoleState, display_response: dict[str, Any]) -> RoleAction:
        state.remember_display(display_response)
        items = display_response.get("items", [])
        allowed_item_ids = {
            str(item.get("parent_asin"))
            for item in items
            if isinstance(item, dict) and item.get("parent_asin")
        }
        content = self.client.complete(_simulation_messages(role, state, display_response))
        payload = _parse_model_json(content)
        action_type = str(payload.get("action_type") or "").strip().lower()
        item_id = str(payload.get("item_id") or "").strip() or None
        message = str(payload.get("message") or payload.get("intent") or "").strip()
        comment = str(payload.get("comment") or "").strip()
        if item_id is not None and item_id not in allowed_item_ids:
            raise ValueError(f"Model selected item outside display: {item_id}")
        if action_type == RoleActionType.CHAT.value:
            if not message:
                raise ValueError("Model chat action requires message")
            return RoleAction.chat(message)
        if action_type == RoleActionType.WHY.value:
            return RoleAction.why(item_id)
        if action_type in {RoleActionType.SHOW_DIFFERENT.value, "dislike"}:
            return RoleAction.feedback(action_type, item_id, comment)
        if action_type == RoleActionType.ACCEPT.value:
            state.ready_to_accept = True
            return RoleAction.accept(item_id, comment or "This matches my current goal.")
        raise ValueError(f"Unsupported model action_type: {action_type}")


def _simulation_messages(role: SimulatedCustomerRole, state: RoleState, display_response: dict[str, Any]) -> list[dict[str, str]]:
    items = [
        {
            "parent_asin": item.get("parent_asin"),
            "title": item.get("title"),
            "category": item.get("category"),
            "summary": item.get("summary"),
            "price": item.get("price"),
        }
        for item in display_response.get("items", [])
        if isinstance(item, dict)
    ]
    role_context = {
        "role_id": role.role_id,
        "persona": role.persona,
        "shopping_goal": role.shopping_goal,
        "budget_sensitivity": role.budget_sensitivity,
        "category_preferences": list(role.category_preferences),
        "keyword_preferences": list(role.keyword_preferences),
        "negative_preferences": list(role.negative_preferences),
        "decision_style": role.decision_style,
        "feedback_style": role.feedback_style,
        "memory": list(role.memory),
        "private_context": role.private_context,
    }
    state_context = {
        "expressed_preferences": list(state.expressed_preferences),
        "seen_item_ids": sorted(state.seen_item_ids),
        "satisfaction": state.satisfaction,
        "turns_observed": state.turns_observed,
    }
    return [
        {
            "role": "system",
            "content": (
                "You simulate a shopping customer in a recommender-system evaluation. "
                "You know only your persona, your past interaction summary, and the currently displayed items. "
                "You do not know the recommender's catalog or hidden candidate pool. "
                "Choose exactly one next action as JSON. Allowed action_type values are "
                "chat, why, show_different, dislike, accept. item_id must be one of the displayed parent_asin values when provided. "
                "For chat actions, write a natural customer message about your need, question, or constraint; do not recite category/keyword lists. "
                "Only accept after the assistant has given concrete, item-specific public reasons that would satisfy a real customer. "
                "If the recommendation is generic, too short, or does not explain why displayed products fit your need, ask why or request a clearer/different set instead. "
                "Do not invent specific products unless they appear in displayed items or your past interaction summary."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"role": role_context, "state": state_context, "display_items": items}, ensure_ascii=False),
        },
    ]


def _parse_model_json(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").removeprefix("json").strip()
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("Model output must be a JSON object")
    return payload


def _assistant_explains_display_items(message: str, items: list[dict[str, Any]]) -> bool:
    normalized = message.lower()
    if len(message.strip()) < 80:
        return False
    mentioned = 0
    for item in items[:3]:
        item_id = str(item.get("parent_asin") or "").lower()
        title = str(item.get("title") or "").strip().lower()
        title_token = title[:24] if len(title) >= 6 else title
        if (item_id and item_id in normalized) or (title_token and title_token in normalized):
            mentioned += 1
    has_reason_word = any(token in normalized for token in ("because", "reason", "适合", "因为", "理由", "类目", "特点", "需求"))
    return mentioned >= 1 and has_reason_word


def _price_number(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("$", "").replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


DEFAULT_ROLE_POLICY = RolePolicy()

__all__ = [
    "DEFAULT_ROLE_POLICY",
    "ModelDrivenRolePolicy",
    "RoleAction",
    "RoleActionType",
    "RolePolicy",
    "RoleState",
    "SimulatedCustomerRole",
]
