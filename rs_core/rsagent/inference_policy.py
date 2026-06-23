from __future__ import annotations

import os
from dataclasses import dataclass, field
from dataclasses import replace
from typing import Any, Protocol

from rs_core.recsys.types import MergedCandidate
from rs_core.rsagent.schema import FeedbackConstraints

DEFAULT_POLICY_TYPE = "deterministic_baseline"
QWEN_POLICY_TYPE = "qwen4b_rerank_signals"
DEFAULT_SCORE_KEY = "feedback_model_rerank"


class InferencePolicyError(RuntimeError):
    pass


class ModelUnavailableError(InferencePolicyError):
    pass


class ModelOutputParseError(InferencePolicyError):
    pass


@dataclass
class RerankSignal:
    item_id: str
    delta: float
    confidence: float = 1.0
    reason: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class RerankPolicyResult:
    policy_type: str
    signals: list[RerankSignal]
    diagnostics: dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False


class RerankPolicyClient(Protocol):
    def rerank(
        self,
        *,
        user_sequence: dict[str, Any],
        feedback_constraints: FeedbackConstraints | None,
        candidates: list[MergedCandidate],
        config: dict[str, Any],
    ) -> RerankPolicyResult:
        ...


def apply_optional_inference_policy(
    *,
    user_sequence: dict[str, Any],
    candidates: list[MergedCandidate],
    feedback_constraints: FeedbackConstraints | None,
    config: dict[str, Any],
    client: RerankPolicyClient | None = None,
    turn_index: int | None = None,
) -> tuple[list[MergedCandidate], dict[str, Any]]:
    policy = resolve_inference_policy_config(config)
    if not policy.get("enabled"):
        return candidates, {"inference_policy": _disabled_diagnostics(policy)}
    gate_reason = _inference_gate_reason(policy, feedback_constraints, turn_index)
    if gate_reason:
        return candidates, {"inference_policy": _gated_diagnostics(policy, gate_reason)}
    try:
        active_client = client or _build_inference_policy_client(policy)
        result = active_client.rerank(
            user_sequence=user_sequence,
            feedback_constraints=feedback_constraints,
            candidates=candidates,
            config=config,
        )
        updated, diagnostics = _apply_policy_result(candidates, result, policy)
        return updated, {"inference_policy": diagnostics}
    except InferencePolicyError as exc:
        if policy.get("strict"):
            raise
        return candidates, {"inference_policy": _fallback_diagnostics(policy, exc)}


def resolve_inference_policy_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = dict(config.get("inference_policy", {}) or {})
    env_policy = os.getenv("RS_AGENT_INFERENCE_POLICY")
    if env_policy:
        normalized_env_policy = env_policy.lower()
        raw["enabled"] = normalized_env_policy in {"qwen", "qwen_local", "local_transformers", "openai_compatible", "openai", "vllm", "on", "true", "1"}
        if normalized_env_policy in {"openai_compatible", "openai", "vllm"}:
            raw["provider"] = "openai_compatible"
        elif normalized_env_policy in {"qwen", "qwen_local", "local_transformers", "on", "true", "1"}:
            raw.setdefault("provider", "local_transformers")
        if normalized_env_policy in {"off", "false", "0"}:
            raw["enabled"] = False
    raw.setdefault("enabled", False)
    raw.setdefault("provider", "local_transformers" if raw.get("enabled") else "disabled")
    if raw.get("provider") == "qwen_local":
        raw["provider"] = "local_transformers"
    raw.setdefault("available_providers", ["disabled", "openai_compatible", "local_transformers"])
    raw.setdefault("policy_type", QWEN_POLICY_TYPE if raw.get("enabled") else DEFAULT_POLICY_TYPE)
    raw.setdefault("strict", False)
    openai_compatible = dict(raw.get("openai_compatible", {}) or {})
    openai_compatible.setdefault("enabled", raw.get("provider") == "openai_compatible" and bool(raw.get("enabled")))
    openai_compatible.setdefault("api_base_env", "RS_AGENT_OPENAI_COMPATIBLE_BASE_URL")
    openai_compatible.setdefault("api_key_env", "RS_AGENT_OPENAI_COMPATIBLE_API_KEY")
    openai_compatible.setdefault("model_env", "RS_AGENT_OPENAI_COMPATIBLE_MODEL")
    if os.getenv(str(openai_compatible.get("api_base_env"))):
        openai_compatible["base_url"] = os.getenv(str(openai_compatible.get("api_base_env")))
    if os.getenv(str(openai_compatible.get("model_env"))):
        openai_compatible["model"] = os.getenv(str(openai_compatible.get("model_env")))
    openai_compatible.setdefault("timeout_seconds", 30.0)
    openai_compatible["timeout_seconds"] = min(float(openai_compatible.get("timeout_seconds", 30.0)), 60.0)
    openai_compatible.setdefault("allow_insecure_local_api_base", False)
    openai_compatible.setdefault("temperature", 0.0)
    openai_compatible.setdefault("max_tokens", 512)
    openai_compatible["max_tokens"] = min(int(openai_compatible.get("max_tokens", 512)), 2048)
    openai_compatible.setdefault("response_format", {"type": "json_object"})
    raw["openai_compatible"] = openai_compatible
    model = dict(raw.get("model", {}) or {})
    if os.getenv("RS_AGENT_QWEN_MODEL_ID"):
        model["model_id"] = os.getenv("RS_AGENT_QWEN_MODEL_ID")
    if raw.get("provider") == "openai_compatible" and openai_compatible.get("model"):
        model["model_id"] = openai_compatible.get("model")
    model.setdefault("model_id", "Qwen/Qwen3.5-4B")
    local_files_only = os.getenv("RS_AGENT_QWEN_LOCAL_FILES_ONLY")
    if local_files_only is not None:
        model["local_files_only"] = local_files_only.lower() in {"1", "true", "yes", "on"}
    else:
        model.setdefault("local_files_only", True)
    raw["model"] = model
    trigger = dict(raw.get("trigger", {}) or {})
    trigger.setdefault("only_after_feedback", False)
    raw["trigger"] = trigger
    signals = dict(raw.get("signals", {}) or {})
    signals.setdefault("score_key", DEFAULT_SCORE_KEY)
    signals.setdefault("min_delta", -1.0)
    signals.setdefault("max_delta", 1.0)
    signals.setdefault("max_signals", 50)
    signals.setdefault("reason_max_chars", 240)
    signals.setdefault("apply_confidence", True)
    raw["signals"] = signals
    prompt = dict(raw.get("prompt", {}) or {})
    prompt.setdefault("max_candidates", 50)
    prompt["max_candidates"] = min(int(prompt.get("max_candidates", 50)), 100)
    prompt.setdefault("metadata_fields", ["title_clean", "main_category", "category", "description_text", "features_text"])
    prompt.setdefault("max_metadata_chars_per_field", 300)
    prompt["max_metadata_chars_per_field"] = min(int(prompt.get("max_metadata_chars_per_field", 300)), 1000)
    prompt.setdefault("max_user_sequence_items", 20)
    prompt["max_user_sequence_items"] = min(int(prompt.get("max_user_sequence_items", 20)), 50)
    raw["prompt"] = prompt
    if os.getenv("RS_AGENT_INFERENCE_STRICT"):
        raw["strict"] = os.getenv("RS_AGENT_INFERENCE_STRICT", "").lower() in {"1", "true", "yes", "on"}
    return raw


def build_rerank_prompt_payload(
    *,
    user_sequence: dict[str, Any],
    feedback_constraints: FeedbackConstraints | None,
    candidates: list[MergedCandidate],
    policy: dict[str, Any],
) -> dict[str, Any]:
    prompt = policy.get("prompt", {})
    metadata_fields = list(prompt.get("metadata_fields", []))
    max_candidates = int(prompt.get("max_candidates", 50))
    max_chars = int(prompt.get("max_metadata_chars_per_field", 300))
    max_sequence_items = int(prompt.get("max_user_sequence_items", 20))
    return {
        "task": "rerank_existing_candidates_only",
        "rules": [
            "Return JSON only.",
            "Do not invent item IDs.",
            "Only use item_id values present in candidates.",
            "Do not recommend products directly.",
            "Produce rerank signals, not final recommendations.",
            "Use small bounded deltas.",
        ],
        "user": {
            "user_id": user_sequence.get("user_id", ""),
            "recent_item_sequence": list(user_sequence.get("recent_item_sequence", []))[-max_sequence_items:],
            "recent_positive_item_sequence": list(user_sequence.get("recent_positive_item_sequence", []))[-max_sequence_items:],
            "recent_strong_positive_item_sequence": list(user_sequence.get("recent_strong_positive_item_sequence", []))[-max_sequence_items:],
        },
        "feedback_constraints": feedback_constraints.to_dict() if feedback_constraints else FeedbackConstraints().to_dict(),
        "candidates": [_candidate_payload(candidate, metadata_fields, max_chars) for candidate in candidates[:max_candidates]],
        "output_schema": {
            "signals": [{"item_id": "existing candidate item_id only", "delta": "float", "confidence": "float", "reason": "short grounded reason", "tags": ["optional"]}],
            "policy_notes": "optional short string",
        },
    }


def _apply_policy_result(candidates: list[MergedCandidate], result: RerankPolicyResult, policy: dict[str, Any]) -> tuple[list[MergedCandidate], dict[str, Any]]:
    signals_config = policy.get("signals", {})
    score_key = str(signals_config.get("score_key", DEFAULT_SCORE_KEY))
    accepted_by_item, rejected = _validate_signals(result.signals, {candidate.item_id for candidate in candidates}, signals_config)
    updated: list[MergedCandidate] = []
    for candidate in candidates:
        signals = accepted_by_item.get(candidate.item_id, [])
        if not signals:
            updated.append(candidate)
            continue
        total_delta = _clamp(sum(signal["applied_delta"] for signal in signals), float(signals_config.get("min_delta", -1.0)), float(signals_config.get("max_delta", 1.0)))
        source_scores = dict(candidate.source_scores)
        source_scores[score_key] = total_delta
        sources = list(candidate.sources)
        if score_key not in sources:
            sources.append(score_key)
        metadata = dict(candidate.metadata)
        events = list(metadata.get("model_rerank_events", []))
        events.extend({**signal, "score_key": score_key, "type": "qwen_rerank_signal"} for signal in signals)
        metadata["model_rerank_events"] = events
        updated.append(replace(candidate, sources=sources, source_scores=source_scores, metadata=metadata))
    diagnostics = {
        "enabled": True,
        "policy_type": result.policy_type or policy.get("policy_type", QWEN_POLICY_TYPE),
        "route": policy.get("provider", "local_transformers"),
        "fallback_used": bool(result.fallback_used),
        "accepted_signal_count": sum(len(signals) for signals in accepted_by_item.values()),
        "rejected_signal_count": len(rejected),
        "rejected_signals": rejected,
        "score_key": score_key,
        "model_id": policy.get("model", {}).get("model_id"),
        **dict(result.diagnostics or {}),
    }
    return updated, diagnostics


def _validate_signals(signals: list[RerankSignal], valid_item_ids: set[str], config: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    min_delta = float(config.get("min_delta", -1.0))
    max_delta = float(config.get("max_delta", 1.0))
    max_signals = int(config.get("max_signals", 50))
    reason_max_chars = int(config.get("reason_max_chars", 240))
    apply_confidence = bool(config.get("apply_confidence", True))
    accepted: dict[str, list[dict[str, Any]]] = {}
    rejected: list[dict[str, Any]] = []
    for signal in signals[:max_signals]:
        item_id = str(signal.item_id)
        if item_id not in valid_item_ids:
            rejected.append({"item_id": item_id, "reason": "unknown_candidate_item_id"})
            continue
        delta = _clamp(float(signal.delta), min_delta, max_delta)
        confidence = _clamp(float(signal.confidence), 0.0, 1.0)
        applied_delta = delta * confidence if apply_confidence else delta
        accepted.setdefault(item_id, []).append({
            "item_id": item_id,
            "delta": delta,
            "confidence": confidence,
            "applied_delta": applied_delta,
            "reason": str(signal.reason)[:reason_max_chars],
            "tags": [str(tag) for tag in signal.tags],
        })
    return accepted, rejected


def _build_inference_policy_client(policy: dict[str, Any]) -> RerankPolicyClient:
    provider = str(policy.get("provider", "disabled"))
    if provider == "local_transformers":
        from rs_core.rsagent.qwen_client import QwenLocalClient

        return QwenLocalClient(policy)
    if provider == "openai_compatible":
        from rs_core.rsagent.openai_rerank_client import OpenAICompatibleRerankClient

        return OpenAICompatibleRerankClient(policy)
    raise ModelUnavailableError(f"inference provider {provider!r} is not available")


def _build_qwen_client(policy: dict[str, Any]) -> RerankPolicyClient:
    return _build_inference_policy_client(policy)


def _disabled_diagnostics(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": False,
        "policy_type": DEFAULT_POLICY_TYPE,
        "route": "disabled",
        "provider": "disabled",
        "fallback_used": False,
        "accepted_signal_count": 0,
        "rejected_signal_count": 0,
        "model_id": policy.get("model", {}).get("model_id"),
    }


def _fallback_diagnostics(policy: dict[str, Any], error: Exception) -> dict[str, Any]:
    return {
        "enabled": True,
        "policy_type": policy.get("policy_type", QWEN_POLICY_TYPE),
        "route": policy.get("provider", "local_transformers"),
        "fallback_used": True,
        "fallback_reason": error.__class__.__name__,
        "error": str(error),
        "accepted_signal_count": 0,
        "rejected_signal_count": 0,
        "model_id": policy.get("model", {}).get("model_id"),
    }


def _inference_gate_reason(
    policy: dict[str, Any],
    feedback_constraints: FeedbackConstraints | None,
    turn_index: int | None,
) -> str | None:
    trigger = policy.get("trigger", {}) or {}
    min_turn_index = trigger.get("min_turn_index")
    if min_turn_index is not None and turn_index is not None and turn_index < int(min_turn_index):
        return "min_turn_index"
    if trigger.get("only_after_feedback") and not _has_feedback_constraints(feedback_constraints):
        return "no_feedback"
    return None


def _has_feedback_constraints(feedback_constraints: FeedbackConstraints | None) -> bool:
    if feedback_constraints is None:
        return False
    payload = feedback_constraints.to_dict()
    return any(bool(value) for value in payload.values())


def _gated_diagnostics(policy: dict[str, Any], gate_reason: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "policy_type": policy.get("policy_type", QWEN_POLICY_TYPE),
        "route": "gated",
        "fallback_used": False,
        "accepted_signal_count": 0,
        "rejected_signal_count": 0,
        "gate_reason": gate_reason,
        "model_id": policy.get("model", {}).get("model_id"),
    }


def _candidate_payload(candidate: MergedCandidate, metadata_fields: list[str], max_chars: int) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for metadata_field in metadata_fields:
        value = candidate.metadata.get(metadata_field)
        if value is None and metadata_field == "category":
            value = candidate.category
        if value is not None:
            metadata[metadata_field] = str(value)[:max_chars]
    return {
        "item_id": candidate.item_id,
        "sources": list(candidate.sources),
        "source_scores": dict(candidate.source_scores),
        "category": candidate.category,
        "metadata": metadata,
    }


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
