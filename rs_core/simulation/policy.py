from __future__ import annotations

from typing import Any

from rs_core.simulation.schema import RoleAction, RoleActionType, RoleState, SimulatedCustomerRole


class RolePolicy:
    def next_action(self, role: SimulatedCustomerRole, state: RoleState, display_response: dict[str, Any]) -> RoleAction:
        state.remember_display(display_response)
        items = display_response.get("items", [])
        if not items:
            state.current_question = "Need more concrete options."
            return RoleAction.chat(f"Can you suggest concrete items for this goal: {role.shopping_goal}?")

        best_item, best_score = self._best_item(role, items)
        best_id = str(best_item.get("parent_asin", "")) or None
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

__all__ = ["DEFAULT_ROLE_POLICY", "RoleAction", "RoleActionType", "RolePolicy", "RoleState", "SimulatedCustomerRole"]
