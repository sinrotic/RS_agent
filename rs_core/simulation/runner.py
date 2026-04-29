from __future__ import annotations

from dataclasses import asdict
from typing import Any
from uuid import uuid4

from rs_core.simulation.policy import DEFAULT_ROLE_POLICY, RolePolicy
from rs_core.simulation.presets import get_preset_role
from rs_core.simulation.schema import RoleAction, RoleActionType, RoleState, SimulatedCustomerRole


TERMINAL_ACTIONS = {RoleActionType.ACCEPT, RoleActionType.STOP}


def run_simulation_scene(
    service: Any,
    role: SimulatedCustomerRole | str,
    max_turns: int = 4,
    user_id: str | None = None,
    policy: RolePolicy = DEFAULT_ROLE_POLICY,
    scene_id: str | None = None,
) -> dict[str, Any]:
    selected_role = get_preset_role(role) if isinstance(role, str) else role
    state = RoleState()
    session_id = service.start_session(user_id=user_id)
    actions: list[dict[str, Any]] = []

    first = RoleAction.chat(selected_role.initial_prompt())
    result = service.chat(session_id, first.message)
    actions.append(_action_record(first, result.display["turn_index"]))
    final_action = first

    for _ in range(max(0, max_turns - 1)):
        next_action = policy.next_action(selected_role, state, result.display)
        final_action = next_action
        if next_action.type in TERMINAL_ACTIONS:
            actions.append(_action_record(next_action, result.display["turn_index"]))
            break
        if next_action.type == RoleActionType.CHAT:
            result = service.chat(session_id, next_action.message)
        else:
            result = service.feedback(session_id, next_action.action_type or next_action.type.value, next_action.item_id, next_action.comment)
        actions.append(_action_record(next_action, result.display["turn_index"]))

    session_export = service.export_session(session_id)
    return {
        "scene_id": scene_id or f"scene-{selected_role.role_id}-{uuid4()}",
        "role": _role_record(selected_role),
        "state": _state_record(state, final_action),
        "actions": actions,
        "session": session_export,
    }


def _role_record(role: SimulatedCustomerRole) -> dict[str, Any]:
    return {
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
    }


def _state_record(state: RoleState, final_action: RoleAction) -> dict[str, Any]:
    return {
        "expressed_preferences": list(state.expressed_preferences),
        "seen_item_ids": sorted(state.seen_item_ids),
        "satisfaction": state.satisfaction,
        "current_question": state.current_question,
        "ready_to_accept": state.ready_to_accept,
        "turns_observed": state.turns_observed,
        "final_action": final_action.type.value,
        "accepted_item_id": final_action.item_id if final_action.type == RoleActionType.ACCEPT else None,
    }


def _action_record(action: RoleAction, turn_index: int) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            **asdict(action),
            "type": action.type.value,
            "turn_index": turn_index,
        }.items()
        if value not in (None, "")
    }
