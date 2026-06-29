from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rs_core.agent.contracts.schema import AgentSession
from rs_core.agent.rollout import session_to_rollout_records
from rs_core.agent.tools import collect_rollout_tool_events
from rs_core.offline.evaluation.agent_scorecard import build_agent_scorecard

SCHEMA_VERSION = "rs_agent_eval_artifact_v1"


def build_agent_eval_artifact(
    session: AgentSession,
    scene: dict[str, Any] | None = None,
    agent_variant: str = "baseline",
    run_id: str | None = None,
    user_sequence: dict[str, Any] | None = None,
    offline_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rollouts = session_to_rollout_records(session, user_sequence)
    scorecard = build_agent_scorecard(session, scene, offline_metrics)
    tool_events = collect_rollout_tool_events(rollouts)
    training_signals = build_training_signals(rollouts, scorecard)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "agent_variant": agent_variant,
        "scene_id": scene.get("scene_id") if scene else None,
        "role_id": scene.get("role", {}).get("role_id") if scene else None,
        "session_id": session.session_id,
        "user_id": session.user_id,
        "scorecard": scorecard,
        "tool_events": tool_events,
        "training_signals": training_signals,
        "diagnostics": {
            "turn_count": len(session.turns),
            "tool_event_count": len(tool_events),
            "public_export_boundary": "internal_artifact_only",
        },
        "rollouts": rollouts,
    }


def build_training_signals(rollouts: list[dict[str, Any]], scorecard: dict[str, Any] | None = None) -> dict[str, Any]:
    sft_records = []
    reward_records = []
    trajectory_records = []
    preference_records = []
    for rollout in rollouts:
        training_samples = rollout.get("training_samples", {})
        sample_context = _sample_context(rollout)
        if training_samples.get("sft_sample"):
            sft_records.append({**sample_context, "schema_version": "rs_agent_sft_sample_v1", "sample": training_samples["sft_sample"]})
        if training_samples.get("reward_sample"):
            reward_records.append({**sample_context, "schema_version": "rs_agent_reward_sample_v1", "sample": training_samples["reward_sample"]})
        trajectory_records.append({
            **sample_context,
            "schema_version": "rs_agent_trajectory_turn_v1",
            "agent_decision": rollout.get("agent_decision", {}),
            "display_response": rollout.get("display_response", {}),
            "tool_events": collect_rollout_tool_events([rollout]),
            "reward_evidence": rollout.get("reward_evidence", {}),
        })
    preference_records.extend(_feedback_preference_records(rollouts))
    return {
        "schema_version": "rs_agent_training_signals_v1",
        "training_status": "deferred_environment_reward_only",
        "sft": sft_records,
        "reward": reward_records,
        "preference": preference_records,
        "trajectory": trajectory_records,
        "metrics": {
            "sft_count": len(sft_records),
            "reward_count": len(reward_records),
            "preference_count": len(preference_records),
            "trajectory_turn_count": len(trajectory_records),
            "overall_score": scorecard.get("overall_score") if scorecard else None,
        },
    }


def write_agent_eval_artifact(artifact: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / f"{artifact['agent_variant']}_artifact.json"
    signals_path = root / f"{artifact['agent_variant']}_training_signals.json"
    scorecard_path = root / f"{artifact['agent_variant']}_scorecard.json"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    signals_path.write_text(json.dumps(artifact["training_signals"], ensure_ascii=False, indent=2), encoding="utf-8")
    scorecard_path.write_text(json.dumps(artifact["scorecard"], ensure_ascii=False, indent=2), encoding="utf-8")
    return {"artifact_path": artifact_path, "training_signals_path": signals_path, "scorecard_path": scorecard_path}


def _sample_context(rollout: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": rollout.get("session_id"),
        "user_id": rollout.get("user_id"),
        "turn_index": rollout.get("turn_index"),
        "policy_type": rollout.get("policy_type"),
    }


def _feedback_preference_records(rollouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for previous, current in zip(rollouts, rollouts[1:]):
        current_events = collect_rollout_tool_events([current])
        if not current_events:
            continue
        current_items = _selected_item_ids(current)
        previous_items = _selected_item_ids(previous)
        if current_items == previous_items:
            continue
        records.append({
            "schema_version": "rs_agent_preference_sample_v1",
            "session_id": current.get("session_id"),
            "user_id": current.get("user_id"),
            "turn_index": current.get("turn_index"),
            "prompt_context": current.get("prompt_context", {}),
            "chosen": current.get("display_response", {}),
            "rejected": previous.get("display_response", {}),
            "preference_reason": "tool_events_changed_display",
            "evidence": {"tool_events": current_events, "previous_item_ids": previous_items, "current_item_ids": current_items},
        })
    return records


def _selected_item_ids(rollout: dict[str, Any]) -> list[str]:
    display = rollout.get("display_response", {})
    return [str(item.get("parent_asin")) for item in display.get("items", []) if item.get("parent_asin")]
