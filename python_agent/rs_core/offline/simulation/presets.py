from __future__ import annotations

from rs_core.offline.simulation.schema import SimulatedCustomerRole


COMMUTER_PRACTICAL = SimulatedCustomerRole(
    role_id="commuter_practical",
    persona="A practical commuter who values reliability and simple explanations.",
    shopping_goal="I need audio gear for daily commute.",
    budget_sensitivity="medium",
    category_preferences=("Audio",),
    keyword_preferences=("bluetooth", "wireless", "commute"),
    negative_preferences=("bulky", "wired"),
    decision_style="cautious",
    feedback_style="direct",
    memory=("Often asks why before accepting a recommendation.",),
)

GIFT_BUYER = SimulatedCustomerRole(
    role_id="gift_buyer",
    persona="A gift buyer who explores alternatives before choosing.",
    shopping_goal="I need a gift that feels useful and easy to like.",
    budget_sensitivity="medium",
    category_preferences=("Audio", "Accessories"),
    keyword_preferences=("popular", "gift", "easy"),
    negative_preferences=("complicated",),
    decision_style="balanced",
    feedback_style="exploratory",
    memory=("Compares several directions before deciding.",),
)

PRICE_SENSITIVE = SimulatedCustomerRole(
    role_id="price_sensitive",
    persona="A budget-conscious shopper who rejects expensive mismatches quickly.",
    shopping_goal="I want a useful product with a low price.",
    budget_sensitivity="high",
    category_preferences=("Accessories", "Audio"),
    keyword_preferences=("deal", "budget", "affordable"),
    negative_preferences=("premium", "expensive"),
    decision_style="fast",
    feedback_style="critical",
    memory=("Strongly dislikes expensive options unless clearly justified.",),
)

PRESET_ROLES = {
    role.role_id: role
    for role in [COMMUTER_PRACTICAL, GIFT_BUYER, PRICE_SENSITIVE]
}


def get_preset_role(role_id: str) -> SimulatedCustomerRole:
    return PRESET_ROLES[role_id]
