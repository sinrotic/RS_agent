from __future__ import annotations

import json
from typing import Any

from rs_core.recsys.types import MergedCandidate
from rs_core.rsagent.inference_policy import (
    ModelOutputParseError,
    ModelUnavailableError,
    QWEN_POLICY_TYPE,
    RerankPolicyResult,
    RerankSignal,
    build_rerank_prompt_payload,
)
from rs_core.rsagent.schema import FeedbackConstraints


class QwenLocalClient:
    def __init__(self, policy_config: dict[str, Any]) -> None:
        self.policy_config = policy_config
        self._tokenizer = None
        self._model = None

    def rerank(
        self,
        *,
        user_sequence: dict[str, Any],
        feedback_constraints: FeedbackConstraints | None,
        candidates: list[MergedCandidate],
        config: dict[str, Any],
    ) -> RerankPolicyResult:
        self._ensure_loaded()
        payload = build_rerank_prompt_payload(
            user_sequence=user_sequence,
            feedback_constraints=feedback_constraints,
            candidates=candidates,
            policy=self.policy_config,
        )
        output_text = self._generate(_format_rerank_prompt(payload))
        try:
            parsed = extract_first_json_object(output_text)
        except ModelOutputParseError as exc:
            raise ModelOutputParseError(f"{exc} Raw output preview: {output_text[:500]!r}") from exc
        return RerankPolicyResult(
            policy_type=str(self.policy_config.get("policy_type", QWEN_POLICY_TYPE)),
            signals=_signals_from_payload(parsed),
            diagnostics={"raw_policy_notes": str(parsed.get("policy_notes", ""))[:500]},
        )

    def _ensure_loaded(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise ModelUnavailableError("Qwen inference requested but torch/transformers are not installed.") from exc
        model_config = dict(self.policy_config.get("model", {}) or {})
        model_id = str(model_config.get("model_id", "Qwen/Qwen3.5-4B"))
        local_files_only = bool(model_config.get("local_files_only", True))
        trust_remote_code = bool(model_config.get("trust_remote_code", False))
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=local_files_only, trust_remote_code=trust_remote_code)
            self._model = AutoModelForCausalLM.from_pretrained(
                model_id,
                local_files_only=local_files_only,
                trust_remote_code=trust_remote_code,
                device_map=model_config.get("device_map", "auto"),
                torch_dtype=model_config.get("torch_dtype", "auto"),
            )
        except Exception as exc:
            raise ModelUnavailableError(f"Qwen model could not be loaded: {exc}") from exc

    def _generate(self, prompt: str) -> str:
        model_config = dict(self.policy_config.get("model", {}) or {})
        if hasattr(self._tokenizer, "apply_chat_template"):
            messages = [
                {"role": "system", "content": "You are a rerank-signal generator. Return exactly one JSON object and no prose."},
                {"role": "user", "content": prompt},
            ]
            prompt = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = self._tokenizer(prompt, return_tensors="pt")
        if hasattr(self._model, "device"):
            inputs = {key: value.to(self._model.device) for key, value in inputs.items()}
        generation_kwargs = {
            "max_new_tokens": int(model_config.get("max_new_tokens", 512)),
            "do_sample": bool(model_config.get("do_sample", False)),
        }
        if generation_kwargs["do_sample"]:
            generation_kwargs["temperature"] = float(model_config.get("temperature", 0.7))
        if getattr(self._tokenizer, "eos_token_id", None) is not None:
            generation_kwargs["pad_token_id"] = self._tokenizer.eos_token_id
        output = self._model.generate(
            **inputs,
            **generation_kwargs,
        )
        generated = output[0][inputs["input_ids"].shape[-1]:]
        return str(self._tokenizer.decode(generated, skip_special_tokens=True))


def _format_rerank_prompt(payload: dict[str, Any]) -> str:
    candidates = [candidate for candidate in payload.get("candidates", []) if isinstance(candidate, dict)]
    candidate_ids = [str(candidate.get("item_id", "")) for candidate in candidates]
    return "\n".join([
        "Return exactly one minified JSON object and no markdown.",
        "Use this exact shape: {\"signals\":[{\"item_id\":\"VALID_ID\",\"delta\":0.2,\"confidence\":0.8,\"reason\":\"short\"}],\"policy_notes\":\"short\"}",
        "If no candidate clearly matches, return {\"signals\":[],\"policy_notes\":\"no clear match\"}.",
        "Only use item_id values from this list: " + json.dumps(candidate_ids, ensure_ascii=False),
        "Return at most 1 signal. Keep delta between -1.0 and 1.0. Keep confidence between 0.0 and 1.0.",
        "Feedback constraints: " + json.dumps(payload.get("feedback_constraints", {}), ensure_ascii=False, separators=(",", ":")),
        "User recent positives: " + json.dumps(payload.get("user", {}).get("recent_positive_item_sequence", []), ensure_ascii=False),
        "Candidates: " + json.dumps(_candidate_prompt_rows(candidates), ensure_ascii=False, separators=(",", ":")),
    ])


def _candidate_prompt_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        metadata = candidate.get("metadata", {}) if isinstance(candidate.get("metadata"), dict) else {}
        rows.append({
            "item_id": str(candidate.get("item_id", "")),
            "category": str(candidate.get("category", "")),
            "sources": candidate.get("sources", []),
            "title": str(metadata.get("title_clean") or metadata.get("title") or "")[:120],
        })
    return rows


def extract_first_json_object(text: str) -> dict[str, Any]:
    think_end = text.rfind("</think>")
    if think_end >= 0:
        text = text[think_end + len("</think>"):]
    start = text.find("{")
    if start < 0:
        raise ModelOutputParseError("Model output did not contain a JSON object.")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    payload = json.loads(text[start:index + 1])
                except json.JSONDecodeError as exc:
                    raise ModelOutputParseError(f"Model output JSON could not be parsed: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ModelOutputParseError("Model output JSON root must be an object.")
                return payload
    repaired = _repair_incomplete_rerank_json(text[start:])
    if repaired is not None:
        return repaired
    raise ModelOutputParseError("Model output JSON object was incomplete.")


def _repair_incomplete_rerank_json(text: str) -> dict[str, Any] | None:
    compact = text.strip()
    if not compact.startswith('{"signals":[{"') or '"policy_notes"' not in compact:
        return None
    repairs = [
        compact.replace('],"policy_notes"', '}],"policy_notes"', 1),
        compact.replace('], "policy_notes"', '}], "policy_notes"', 1),
    ]
    for repaired in repairs:
        if repaired == compact:
            continue
        try:
            payload = json.loads(repaired)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _signals_from_payload(payload: dict[str, Any]) -> list[RerankSignal]:
    raw_signals = payload.get("signals", [])
    if not isinstance(raw_signals, list):
        raise ModelOutputParseError("Model output field 'signals' must be a list.")
    signals: list[RerankSignal] = []
    for raw in raw_signals:
        if not isinstance(raw, dict):
            continue
        tags = raw.get("tags", [])
        try:
            delta = float(raw.get("delta", 0.0))
            confidence = float(raw.get("confidence", 1.0))
        except (TypeError, ValueError) as exc:
            raise ModelOutputParseError("Model output signal delta/confidence must be numeric.") from exc
        signals.append(RerankSignal(
            item_id=str(raw.get("item_id", "")),
            delta=delta,
            confidence=confidence,
            reason=str(raw.get("reason", "")),
            tags=[str(tag) for tag in tags] if isinstance(tags, list) else [],
        ))
    return signals
