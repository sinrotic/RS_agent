from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from rs_core.simulation.policy import DEFAULT_ROLE_POLICY, RolePolicy
from rs_core.simulation.presets import PRESET_ROLES, get_preset_role
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


def run_simulation_batch(
    service: Any,
    role_ids: list[str] | tuple[str, ...] | None = None,
    max_turns: int = 4,
    user_id: str | None = None,
    repeats: int = 1,
    policy: RolePolicy = DEFAULT_ROLE_POLICY,
    batch_id: str | None = None,
) -> dict[str, Any]:
    selected_role_ids = list(role_ids) if role_ids is not None else list(PRESET_ROLES)
    current_batch_id = batch_id or f"simulation-batch-{uuid4()}"
    scenes: list[dict[str, Any]] = []

    for role_id in selected_role_ids:
        get_preset_role(role_id)
        for repeat_index in range(max(1, repeats)):
            scene = run_simulation_scene(
                service,
                role_id,
                max_turns=max_turns,
                user_id=user_id,
                policy=policy,
                scene_id=f"{current_batch_id}-{role_id}-{repeat_index + 1}",
            )
            scene["metrics"] = _scene_metrics(scene)
            scenes.append(scene)

    return {
        "batch_id": current_batch_id,
        "summary": _batch_summary(scenes),
        "scenes": scenes,
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


def _scene_metrics(scene: dict[str, Any]) -> dict[str, Any]:
    actions = scene.get("actions", [])
    state = scene.get("state", {})
    session = scene.get("session", {})
    action_counts = Counter(action.get("type") for action in actions if action.get("type"))
    feedback_count = sum(1 for event in session.get("events", []) if event.get("type") == "feedback")
    seen_item_ids = state.get("seen_item_ids", [])
    return {
        "turn_count": session.get("turn_count", 0),
        "action_count": len(actions),
        "final_action": state.get("final_action"),
        "accepted_item_id": state.get("accepted_item_id"),
        "accepted": state.get("accepted_item_id") is not None,
        "feedback_count": feedback_count,
        "why_count": action_counts.get(RoleActionType.WHY.value, 0),
        "show_different_count": action_counts.get(RoleActionType.SHOW_DIFFERENT.value, 0),
        "unique_seen_items": len(set(seen_item_ids)),
        "satisfaction": state.get("satisfaction", 0.0),
        "action_counts": dict(sorted(action_counts.items())),
    }


def _batch_summary(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [scene["metrics"] for scene in scenes]
    role_ids = [scene["role"]["role_id"] for scene in scenes]
    role_summaries = {
        role_id: _summary_for_scenes([scene for scene in scenes if scene["role"]["role_id"] == role_id])
        for role_id in sorted(set(role_ids))
    }
    return {
        **_summary_from_metrics(metrics),
        "role_count": len(set(role_ids)),
        "roles": role_summaries,
    }


def _summary_for_scenes(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    return _summary_from_metrics([scene["metrics"] for scene in scenes])


def _summary_from_metrics(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    scene_count = len(metrics)
    action_counts: Counter[str] = Counter()
    for metric in metrics:
        action_counts.update(metric.get("action_counts", {}))
    return {
        "scene_count": scene_count,
        "avg_turn_count": _average(metric.get("turn_count", 0) for metric in metrics),
        "accept_rate": _average(1.0 if metric.get("accepted") else 0.0 for metric in metrics),
        "avg_satisfaction": _average(metric.get("satisfaction", 0.0) for metric in metrics),
        "avg_unique_seen_items": _average(metric.get("unique_seen_items", 0) for metric in metrics),
        "feedback_count": sum(metric.get("feedback_count", 0) for metric in metrics),
        "why_count": sum(metric.get("why_count", 0) for metric in metrics),
        "show_different_count": sum(metric.get("show_different_count", 0) for metric in metrics),
        "action_counts": dict(sorted(action_counts.items())),
    }


def _average(values: Any) -> float:
    items = list(values)
    if not items:
        return 0.0
    return round(sum(items) / len(items), 6)
