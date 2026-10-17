#!/usr/bin/env python3
"""Probe vLLM JSON-schema responses and strict tool calls without extra packages."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
import urllib.request
from typing import Any


BLOCK_FIELDS = {"type", "content", "card_set_id", "item_ids", "layout"}
BLOCK_TYPES = {"text", "product_cards", "comparison_table", "followup_question"}

FINAL_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "blocks": {
            "type": "array",
            "minItems": 1,
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "text",
                            "product_cards",
                            "comparison_table",
                            "followup_question",
                        ],
                    },
                    "content": {"type": ["string", "null"], "maxLength": 4000},
                    "card_set_id": {"type": ["string", "null"], "maxLength": 128},
                    "item_ids": {
                        "type": ["array", "null"],
                        "items": {"type": "string", "maxLength": 128},
                        "maxItems": 20,
                    },
                    "layout": {"type": ["string", "null"], "maxLength": 64},
                },
                "required": ["type", "content", "card_set_id", "item_ids", "layout"],
            },
        }
    },
    "required": ["blocks"],
}


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def chat_completions_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/chat/completions"


def headers(api_key: str | None) -> dict[str, str]:
    result = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        result["Authorization"] = f"Bearer {api_key}"
    return result


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers(api_key),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_sse_tool_arguments(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout: float,
) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**headers(api_key), "Accept": "text/event-stream"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return collect_tool_stream(response)


def collect_tool_stream(lines: Iterable[bytes]) -> tuple[str, str]:
    tool_name = ""
    tool_id = None
    argument_chunks: list[str] = []
    finished = False
    done = False
    for raw_line in lines:
        line = raw_line.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data:
            continue
        if data == "[DONE]":
            done = True
            break
        event = json.loads(data)
        if event.get("error"):
            raise ValueError("upstream returned a stream error")
        choices = event.get("choices") or []
        if not choices:
            continue
        if len(choices) != 1 or choices[0].get("index", 0) != 0:
            raise ValueError("probe expects exactly one completion choice")
        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            if finish_reason not in {"stop", "tool_calls"}:
                raise ValueError(f"tool generation did not complete: {finish_reason}")
            finished = True
        delta = choice.get("delta") or {}
        if delta.get("refusal"):
            raise ValueError("tool generation was refused")
        for call in delta.get("tool_calls") or []:
            if call.get("index", 0) != 0:
                raise ValueError("parallel tool call received despite being disabled")
            if call.get("id"):
                if tool_id is not None and tool_id != call["id"]:
                    raise ValueError("multiple tool calls received")
                tool_id = call["id"]
            function = call.get("function") or {}
            if function.get("name"):
                name = function["name"]
                if tool_name and name != tool_name:
                    raise ValueError("tool name changed within one call")
                tool_name = name
            if function.get("arguments") is not None:
                fragment = function["arguments"]
                if not isinstance(fragment, str):
                    raise ValueError("tool argument fragment must be a string")
                argument_chunks.append(fragment)
    if not done or not finished or not tool_name or not tool_id:
        raise ValueError("tool stream ended without a complete call and terminal marker")
    return tool_name, "".join(argument_chunks)


def response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "rs_agent_final_answer",
            "strict": True,
            "schema": FINAL_ANSWER_SCHEMA,
        },
    }


def final_answer_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "emit_final_answer",
            "description": "Emit ordered user-visible final answer blocks.",
            "strict": True,
            "parameters": FINAL_ANSWER_SCHEMA,
        },
    }


def direct_output_payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Return one Chinese text block saying the structured-output probe passed. "
                    "Set card_set_id, item_ids, and layout to null."
                ),
            }
        ],
        "temperature": 0,
        "max_tokens": 256,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": response_format(),
    }


def tool_output_payload(model: str, *, stream: bool, choice: str = "named") -> dict[str, Any]:
    if choice not in {"named", "required", "auto"}:
        raise ValueError("unsupported probe tool choice")
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Call emit_final_answer with one Chinese text block saying the strict tool probe passed. "
                    "Set card_set_id, item_ids, and layout to null."
                ),
            }
        ],
        "temperature": 0,
        "max_tokens": 256,
        "chat_template_kwargs": {"enable_thinking": False},
        "tools": [final_answer_tool()],
        "tool_choice": {
            "type": "function",
            "function": {"name": "emit_final_answer"},
        } if choice == "named" else choice,
        "parallel_tool_calls": False,
        "stream": stream,
    }


def validate_final_answer(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {"blocks"}:
        raise ValueError("final answer root does not match the strict schema")
    blocks = payload.get("blocks")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 12:
        raise ValueError("final answer blocks are missing or out of bounds")
    for block in blocks:
        if not isinstance(block, dict) or set(block) != BLOCK_FIELDS:
            raise ValueError("final answer block fields do not match the strict schema")
        block_type = block.get("type")
        if block_type not in BLOCK_TYPES:
            raise ValueError("final answer block type is invalid")
        content = block.get("content")
        card_set_id = block.get("card_set_id")
        item_ids = block.get("item_ids")
        layout = block.get("layout")
        if content is not None and (not isinstance(content, str) or len(content) > 4000):
            raise ValueError("content is invalid")
        if card_set_id is not None and (not isinstance(card_set_id, str) or len(card_set_id) > 128):
            raise ValueError("card_set_id is invalid")
        if item_ids is not None and (
            not isinstance(item_ids, list)
            or len(item_ids) > 20
            or any(not isinstance(item_id, str) or not item_id or len(item_id) > 128 for item_id in item_ids)
        ):
            raise ValueError("item_ids is invalid")
        if layout is not None and (not isinstance(layout, str) or len(layout) > 64):
            raise ValueError("layout is invalid")
        if block_type in {"text", "comparison_table", "followup_question"} and not content:
            raise ValueError(f"{block_type} requires content")
        if block_type == "product_cards" and not card_set_id and not item_ids:
            raise ValueError("product_cards requires card_set_id or item_ids")
    return payload


def first_message(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if len(choices) != 1 or not isinstance(choices[0].get("message"), dict):
        raise ValueError("chat completion response does not contain a message")
    if choices[0].get("finish_reason") not in {"stop", "tool_calls"}:
        raise ValueError("completion ended without a successful finish reason")
    if choices[0]["message"].get("refusal"):
        raise ValueError("completion was refused")
    return choices[0]["message"]


def validate_tool_response(response: dict[str, Any], choice: str) -> None:
    tool_calls = first_message(response).get("tool_calls") or []
    if len(tool_calls) != 1:
        raise ValueError(f"{choice} tool probe did not return exactly one tool call")
    function = tool_calls[0].get("function") or {}
    if function.get("name") != "emit_final_answer":
        raise ValueError(f"{choice} tool probe returned the wrong tool")
    validate_final_answer(json.loads(str(function.get("arguments"))))


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    url = chat_completions_url(args.base_url)
    started = time.monotonic()
    cases = []
    concurrency = getattr(args, "warmup_concurrency", 1)
    if not 1 <= concurrency <= 16:
        raise ValueError("并发预热范围为 1 至 16")

    direct_response = post_json(
        url,
        direct_output_payload(args.model),
        api_key=args.api_key,
        timeout=args.timeout,
    )
    direct_content = first_message(direct_response).get("content")
    validate_final_answer(json.loads(str(direct_content)))
    print("[probe] response_format=json_schema PASS", flush=True)
    cases.append("json_schema")

    for choice in ("named", "required", "auto"):
        tool_response = post_json(
            url,
            tool_output_payload(args.model, stream=False, choice=choice),
            api_key=args.api_key,
            timeout=args.timeout,
        )
        validate_tool_response(tool_response, choice)
        print(f"[probe] {choice} strict tool call PASS", flush=True)
        cases.append(f"{choice}_tool")

        if not args.skip_stream:
            tool_name, arguments = post_sse_tool_arguments(
                url,
                tool_output_payload(args.model, stream=True, choice=choice),
                api_key=args.api_key,
                timeout=args.timeout,
            )
            if tool_name != "emit_final_answer":
                raise ValueError("streaming tool probe returned the wrong tool")
            validate_final_answer(json.loads(arguments))
            print(f"[probe] streaming {choice} strict tool arguments PASS", flush=True)
            cases.append(f"{choice}_stream")
    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(
                post_json, url, tool_output_payload(args.model, stream=False),
                api_key=args.api_key, timeout=args.timeout,
            ) for _ in range(concurrency)]
            for future in futures:
                validate_tool_response(future.result(), "concurrent named")
        cases.append(f"named_tool_concurrency_{concurrency}")
        print(f"[probe] {concurrency} 路严格工具并发预热 PASS", flush=True)
    report = {
        "status": "PASS", "model": args.model, "cases": cases,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = report_path.with_name(report_path.name + ".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(report_path)
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe vLLM structured-output support.")
    parser.add_argument("--base-url", default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:18082/v1"))
    parser.add_argument("--model", default=os.getenv("VLLM_MODEL", "qwen35-4b"))
    parser.add_argument("--api-key", default=os.getenv("VLLM_API_KEY"))
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--skip-stream", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-file", default=None)
    parser.add_argument("--warmup-concurrency", type=int, choices=range(1, 17), default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.dry_run:
        print(json.dumps(
            {
                "direct_output": direct_output_payload(args.model),
                "named_tool_output": tool_output_payload(args.model, stream=False),
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    run_probe(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
