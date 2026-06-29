from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from rs_core.common.openai_compatible_client import OpenAICompatibleClient, first_message_content, safe_response_metadata
from rs_core.offline.training.data_contracts import SFT_SAMPLE_SCHEMA_VERSION, validate_sft_sample

DEFAULT_SYSTEM_PROMPT = (
    "你是推荐系统 SFT 数据生成助手。只返回一个 JSON object，不要输出 markdown。"
    "必须从候选商品中选择，不得发明 item_id；selected_item_ids 必须同时属于 allowed_item_ids 和 candidate_summary。"
)


def build_gpt_sft_messages(record: dict[str, Any], *, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> list[dict[str, str]]:
    validate_sft_sample(record)
    sample = record["sample"]
    allowed_item_ids = list(sample["target_action"].get("allowed_item_ids", []))
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "generate_rs_agent_sft_sample",
                    "rules": [
                        "Return exactly one JSON object and no markdown.",
                        "Do not invent item IDs.",
                        "selected_item_ids must be selected from allowed_item_ids.",
                        "selected_item_ids must also exist in candidate_summary.item_id.",
                        "Keep candidate_summary and feedback_constraints grounded in the input.",
                    ],
                    "allowed_item_ids": allowed_item_ids,
                    "input_seed": {
                        "user_input": sample["user_input"],
                        "assistant_response": sample["assistant_response"],
                        "feedback_constraints": sample["feedback_constraints"],
                        "candidate_summary": sample["candidate_summary"],
                        "target_action": sample["target_action"],
                        "target_explanation": sample["target_explanation"],
                    },
                    "output_schema": {
                        "user_input": "string",
                        "assistant_response": "string",
                        "feedback_constraints": "object",
                        "candidate_summary": [{"item_id": "existing candidate item_id", "sources": ["string"], "category": "string"}],
                        "target_action": {
                            "strategy_name": "string",
                            "trigger_reason": "string",
                            "selected_item_ids": ["item_id from allowed_item_ids"],
                            "allowed_item_ids": allowed_item_ids,
                            "must_select_from_candidates": True,
                        },
                        "target_explanation": "string",
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


def generate_gpt_sft_sample(
    record: dict[str, Any],
    *,
    client: OpenAICompatibleClient,
    model: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    messages = build_gpt_sft_messages(record, system_prompt=system_prompt)
    response = client.chat_completion(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format or {"type": "json_object"},
    )
    parsed = extract_first_json_object(first_message_content(response))
    generated = _wrap_generated_sample(record, parsed)
    generated["metadata"] = {
        "generator": "gpt_sft",
        "provider": "openai_compatible",
        "model": model,
        "source_session_id": record.get("session_id"),
        "source_turn_index": record.get("turn_index"),
        "response": safe_response_metadata(response),
    }
    _validate_generated_fields(generated)
    _validate_seed_constraints(record, generated)
    validate_sft_sample(generated)
    return generated


def extract_first_json_object(text: str) -> dict[str, Any]:
    compact = _strip_markdown_fence(text.strip())
    start = compact.find("{")
    if start < 0:
        raise ValueError("GPT SFT response did not contain a JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(compact)):
        char = compact[index]
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
                payload = json.loads(compact[start:index + 1])
                if not isinstance(payload, dict):
                    raise ValueError("GPT SFT response JSON root must be an object")
                return payload
    raise ValueError("GPT SFT response JSON object was incomplete")


def _wrap_generated_sample(seed_record: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    if parsed.get("schema_version") == SFT_SAMPLE_SCHEMA_VERSION and isinstance(parsed.get("sample"), dict):
        sample = deepcopy(parsed["sample"])
    else:
        sample = deepcopy(parsed)
    seed_sample = seed_record.get("sample") if isinstance(seed_record.get("sample"), dict) else {}
    seed_action = seed_sample.get("target_action") if isinstance(seed_sample.get("target_action"), dict) else {}
    action = sample.get("target_action") if isinstance(sample.get("target_action"), dict) else {}
    action["allowed_item_ids"] = deepcopy(seed_action.get("allowed_item_ids", []))
    action["must_select_from_candidates"] = True
    sample["target_action"] = action
    sample["candidate_summary"] = deepcopy(seed_sample.get("candidate_summary", []))
    generated = {key: deepcopy(seed_record.get(key)) for key in ["session_id", "user_id", "turn_index", "policy_type"] if key in seed_record}
    generated["schema_version"] = SFT_SAMPLE_SCHEMA_VERSION
    generated["sample"] = sample
    return generated


def _validate_generated_fields(record: dict[str, Any]) -> None:
    sample = record.get("sample") if isinstance(record.get("sample"), dict) else {}
    if not str(sample.get("assistant_response", "")).strip():
        raise ValueError("GPT SFT sample assistant_response is required")
    if not str(sample.get("target_explanation", "")).strip():
        raise ValueError("GPT SFT sample target_explanation is required")


def _validate_seed_constraints(seed_record: dict[str, Any], generated_record: dict[str, Any]) -> None:
    seed_sample = seed_record.get("sample") if isinstance(seed_record.get("sample"), dict) else {}
    generated_sample = generated_record.get("sample") if isinstance(generated_record.get("sample"), dict) else {}
    seed_candidate_ids = _candidate_ids(seed_sample.get("candidate_summary"))
    seed_allowed_ids = _as_str_set(seed_sample.get("target_action", {}).get("allowed_item_ids") if isinstance(seed_sample.get("target_action"), dict) else [])
    generated_candidate_ids = _candidate_ids(generated_sample.get("candidate_summary"))
    generated_action = generated_sample.get("target_action") if isinstance(generated_sample.get("target_action"), dict) else {}
    generated_allowed_ids = _as_str_set(generated_action.get("allowed_item_ids"))
    generated_selected_ids = _as_str_set(generated_action.get("selected_item_ids"))

    if not generated_candidate_ids <= seed_candidate_ids:
        raise ValueError("GPT SFT candidate_summary contains item IDs outside the seed candidate pool")
    if not generated_allowed_ids <= seed_allowed_ids:
        raise ValueError("GPT SFT allowed_item_ids contains item IDs outside the seed allowed item set")
    if generated_action.get("must_select_from_candidates") is not True:
        raise ValueError("GPT SFT target_action.must_select_from_candidates must remain true")
    if not generated_selected_ids <= seed_candidate_ids:
        raise ValueError("GPT SFT selected_item_ids must come from the seed candidate pool")
    if not generated_selected_ids <= seed_allowed_ids:
        raise ValueError("GPT SFT selected_item_ids must come from the seed allowed item set")
    if not generated_selected_ids <= generated_candidate_ids:
        raise ValueError("GPT SFT selected_item_ids must be present in generated candidate_summary")
    if not generated_selected_ids <= generated_allowed_ids:
        raise ValueError("GPT SFT selected_item_ids must be present in generated allowed_item_ids")


def _candidate_ids(candidates: Any) -> set[str]:
    if not isinstance(candidates, list):
        return set()
    return {str(candidate.get("item_id")) for candidate in candidates if isinstance(candidate, dict) and candidate.get("item_id")}


def _as_str_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if str(value)}


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text
