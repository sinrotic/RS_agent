from __future__ import annotations

from statistics import mean
from typing import Any

from rs_core.rsagent.schema import AgentSession
from rs_core.rsagent.tools import collect_diagnostic_tool_events, collect_turn_tool_events

DIMENSIONS = (
    "recommendation_effectiveness",
    "interaction_quality",
    "feedback_responsiveness",
    "memory_consistency",
    "training_data_quality",
)


def build_agent_scorecard(
    session: AgentSession,
    scene: dict[str, Any] | None = None,
    offline_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dimensions = {
        "recommendation_effectiveness": _recommendation_effectiveness(session, offline_metrics or {}),
        "interaction_quality": _interaction_quality(session, scene or {}),
        "feedback_responsiveness": _feedback_responsiveness(session),
        "memory_consistency": _memory_consistency(session),
        "training_data_quality": _training_data_quality(session),
    }
    overall = mean(dimension["score"] for dimension in dimensions.values()) if dimensions else 0.0
    return {
        "schema_version": "rs_agent_scorecard_v1",
        "overall_score": round(overall, 6),
        "dimensions": dimensions,
        "weights": {name: round(1.0 / len(DIMENSIONS), 6) for name in DIMENSIONS},
    }


def _recommendation_effectiveness(session: AgentSession, offline_metrics: dict[str, Any]) -> dict[str, Any]:
    if offline_metrics:
        values = [
            _metric(offline_metrics, "hit_rate_at_k"),
            _metric(offline_metrics, "recall_at_k"),
            _metric(offline_metrics, "ndcg_at_k"),
            _metric(offline_metrics, "mrr_at_k"),
            _metric(offline_metrics, "map_at_k"),
        ]
        score = mean(values)
        subscores = {
            "hit_rate_at_k": values[0],
            "recall_at_k": values[1],
            "ndcg_at_k": values[2],
            "mrr_at_k": values[3],
            "map_at_k": values[4],
        }
    else:
        turns_with_items = sum(1 for turn in session.turns if turn.recommendation.final_items)
        score = turns_with_items / max(1, len(session.turns))
        subscores = {"turns_with_items_rate": round(score, 6)}
    return _dimension(score, subscores, {"turn_count": len(session.turns)}, [] if offline_metrics else ["No offline holdout metrics were supplied."])


def _interaction_quality(session: AgentSession, scene: dict[str, Any]) -> dict[str, Any]:
    metrics = scene.get("metrics", {}) if isinstance(scene, dict) else {}
    responses = [turn.assistant_response or turn.recommendation.agent_explanation for turn in session.turns]
    non_empty = sum(1 for response in responses if str(response).strip()) / max(1, len(responses))
    satisfaction = _clamp(float(metrics.get("satisfaction", 0.0) or 0.0)) if metrics else 0.0
    accept = 1.0 if metrics.get("accepted") else 0.0
    score = mean([non_empty, satisfaction, accept]) if metrics else non_empty
    return _dimension(
        score,
        {"non_empty_response_rate": round(non_empty, 6), "satisfaction": round(satisfaction, 6), "accepted": accept},
        {"final_action": metrics.get("final_action")},
        [] if metrics else ["No simulated user satisfaction metrics were supplied."],
    )


def _feedback_responsiveness(session: AgentSession) -> dict[str, Any]:
    events = collect_turn_tool_events(session.turns)
    filter_count = sum(1 for event in events if event.get("action") == "filter")
    boost_count = sum(1 for event in events if event.get("action") == "boost")
    demote_count = sum(1 for event in events if event.get("action") == "demote")
    feedback_turns = [turn for turn in session.turns if turn.feedback_constraints.item_feedback_events or turn.feedback_constraints.disliked_item_ids]
    rejected_reappeared = _rejected_reappeared(session)
    explicit_filter_score = 1.0 if not rejected_reappeared else 0.0
    evidence_score = min(1.0, (filter_count + boost_count + demote_count) / max(1, len(feedback_turns))) if feedback_turns else 1.0
    score = mean([explicit_filter_score, evidence_score])
    return _dimension(
        score,
        {
            "explicit_rejection_filter_score": explicit_filter_score,
            "tool_event_coverage": round(evidence_score, 6),
            "filter_count": filter_count,
            "boost_count": boost_count,
            "demote_count": demote_count,
        },
        {"tool_events": events, "rejected_reappeared": rejected_reappeared},
        [],
    )


def _memory_consistency(session: AgentSession) -> dict[str, Any]:
    liked = set(session.active_constraints.liked_item_ids)
    disliked = set(session.active_constraints.disliked_item_ids)
    repeated_rejections = _rejected_reappeared(session)
    liked_persisted = 1.0 if not liked or liked <= set(session.active_constraints.liked_item_ids) else 0.0
    disliked_persisted = 1.0 if not disliked or disliked <= set(session.active_constraints.disliked_item_ids) else 0.0
    rejected_not_repeated = 1.0 if not repeated_rejections else 0.0
    score = mean([liked_persisted, disliked_persisted, rejected_not_repeated])
    return _dimension(
        score,
        {
            "liked_anchor_persistence": liked_persisted,
            "disliked_item_persistence": disliked_persisted,
            "rejected_not_repeated": rejected_not_repeated,
        },
        {"liked_item_ids": sorted(liked), "disliked_item_ids": sorted(disliked), "repeated_rejections": repeated_rejections},
        [],
    )


def _training_data_quality(session: AgentSession) -> dict[str, Any]:
    turn_count = len(session.turns)
    sft_ready = sum(1 for turn in session.turns if turn.user_input is not None and turn.recommendation.final_items is not None)
    reward_ready = sum(1 for turn in session.turns if turn.reward_evidence is not None)
    tool_event_turns = sum(1 for turn in session.turns if collect_diagnostic_tool_events(turn.diagnostics))
    sft_score = sft_ready / max(1, turn_count)
    reward_score = reward_ready / max(1, turn_count)
    tool_score = 1.0 if not _has_item_feedback(session) else min(1.0, tool_event_turns / max(1, turn_count))
    score = mean([sft_score, reward_score, tool_score])
    return _dimension(
        score,
        {
            "sft_sample_coverage": round(sft_score, 6),
            "reward_sample_coverage": round(reward_score, 6),
            "tool_evidence_coverage": round(tool_score, 6),
        },
        {"turn_count": turn_count, "tool_event_turns": tool_event_turns},
        ["Scores describe data coverage, not completed model training."],
    )


def _dimension(score: float, subscores: dict[str, Any], evidence: dict[str, Any], limitations: list[str]) -> dict[str, Any]:
    return {"score": round(_clamp(score), 6), "subscores": subscores, "evidence": evidence, "limitations": limitations}


def _rejected_reappeared(session: AgentSession) -> list[dict[str, Any]]:
    rejected: set[str] = set()
    violations: list[dict[str, Any]] = []
    for turn in session.turns:
        rejected.update(turn.feedback_constraints.disliked_item_ids)
        item_ids = {str(item.get("parent_asin")) for item in turn.ranking if item.get("parent_asin")}
        for item_id in sorted(rejected & item_ids):
            violations.append({"turn_index": turn.turn_index, "item_id": item_id})
    return violations


def _has_item_feedback(session: AgentSession) -> bool:
    return bool(session.active_constraints.liked_item_ids or session.active_constraints.disliked_item_ids or session.active_constraints.item_feedback_events)


def _metric(metrics: dict[str, Any], key: str) -> float:
    return _clamp(float(metrics.get(key, 0.0) or 0.0))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
