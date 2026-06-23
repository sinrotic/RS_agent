from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RoleActionType(str, Enum):
    CHAT = "chat"
    FEEDBACK = "feedback"
    WHY = "why"
    SHOW_DIFFERENT = "show_different"
    ACCEPT = "accept"
    STOP = "stop"


@dataclass(frozen=True)
class SimulatedCustomerRole:
    role_id: str
    persona: str
    shopping_goal: str
    budget_sensitivity: str = "medium"
    category_preferences: tuple[str, ...] = ()
    keyword_preferences: tuple[str, ...] = ()
    negative_preferences: tuple[str, ...] = ()
    decision_style: str = "balanced"
    feedback_style: str = "direct"
    memory: tuple[str, ...] = ()
    initial_request: str = ""
    private_context: dict[str, Any] = field(default_factory=dict)

    def initial_prompt(self) -> str:
        if self.initial_request.strip():
            return self.initial_request.strip()
        parts = [self.shopping_goal]
        if self.category_preferences:
            parts.append(f"Prefer categories: {', '.join(self.category_preferences)}.")
        if self.keyword_preferences:
            parts.append(f"Prefer features: {', '.join(self.keyword_preferences)}.")
        if self.negative_preferences:
            parts.append(f"Avoid: {', '.join(self.negative_preferences)}.")
        return " ".join(parts)


@dataclass
class RoleState:
    expressed_preferences: list[str] = field(default_factory=list)
    seen_item_ids: set[str] = field(default_factory=set)
    satisfaction: float = 0.0
    current_question: str | None = None
    ready_to_accept: bool = False
    turns_observed: int = 0

    def remember_display(self, display_response: dict[str, Any]) -> None:
        self.turns_observed += 1
        for item in display_response.get("items", []):
            item_id = item.get("parent_asin")
            if item_id:
                self.seen_item_ids.add(str(item_id))


@dataclass(frozen=True)
class RoleAction:
    type: RoleActionType
    message: str = ""
    action_type: str | None = None
    item_id: str | None = None
    comment: str | None = None

    @classmethod
    def chat(cls, message: str) -> "RoleAction":
        return cls(type=RoleActionType.CHAT, message=message)

    @classmethod
    def feedback(cls, action_type: str, item_id: str | None = None, comment: str | None = None) -> "RoleAction":
        mapped_type = RoleActionType.SHOW_DIFFERENT if action_type == "show_different" else RoleActionType.FEEDBACK
        return cls(type=mapped_type, action_type=action_type, item_id=item_id, comment=comment)

    @classmethod
    def why(cls, item_id: str | None = None) -> "RoleAction":
        return cls(type=RoleActionType.WHY, action_type="why", item_id=item_id)

    @classmethod
    def accept(cls, item_id: str | None = None, comment: str | None = None) -> "RoleAction":
        return cls(type=RoleActionType.ACCEPT, item_id=item_id, comment=comment)
