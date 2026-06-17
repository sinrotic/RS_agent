from __future__ import annotations

from typing import Any

from rs_core.recsys.types import AgentDecision, RankingResult


def make_agent_decision(user_id: str, ranking: RankingResult, config: dict, diagnostics: dict[str, Any] | None = None) -> AgentDecision:
    inference_policy = (diagnostics or {}).get("inference_policy", {})
    inference_enabled = bool(inference_policy.get("enabled"))
    fallback_used = bool(inference_policy.get("fallback_used"))
    inference_route = str(inference_policy.get("route", ""))
    gate_reason = str(inference_policy.get("gate_reason", ""))
    limitations: list[str] = []
    if inference_enabled and fallback_used:
        limitations.append("Qwen inference was requested but unavailable or invalid, so deterministic ranking continued without model signals.")
        explanation = "Applies hybrid recall and deterministic feedback constraints; requested Qwen rerank inference fell back to the deterministic path."
    elif inference_enabled and inference_route == "gated":
        reason_suffix = f" ({gate_reason})" if gate_reason else ""
        limitations.append(f"Qwen inference was gated for this turn{reason_suffix}, so no model rerank signals were applied.")
        explanation = "Applies hybrid recall and deterministic feedback constraints; Qwen rerank inference is configured but skipped by the inference gate for this turn."
    elif inference_enabled:
        limitations.append("Qwen inference is constrained to bounded rerank signals over existing candidates; it cannot create products.")
        explanation = "Applies hybrid recall and deterministic feedback constraints, then uses Qwen-generated bounded rerank signals over existing candidates before final ranking."
    else:
        limitations.append("Deterministic policy stub only; no autonomous model planning is used.")
        explanation = "Applies fixed weights to available candidate providers and your feedback constraints; this is a transparent deterministic baseline."
    limitations.append("Small-sample demo quality depends on available recall-clean smoke artifacts.")
    risk_flags: list[str] = []
    if ranking.fallback_used:
        risk_flags.append("popular_fallback_used")
    if fallback_used:
        risk_flags.append("inference_policy_fallback_used")
    if not ranking.items:
        risk_flags.append("empty_recommendation_list")
    return AgentDecision(
        user_id=user_id,
        strategy_name=str(config.get("strategy_name", "phase_1_5_deterministic_hybrid_demo")),
        trigger_reason="ranked_hybrid_candidates_available" if ranking.items else "no_candidates_available",
        agent_explanation=explanation,
        risk_flags=risk_flags,
        limitations=limitations,
        final_items=ranking.items,
    )
