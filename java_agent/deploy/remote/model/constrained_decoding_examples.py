#!/usr/bin/env python3
"""向现有 Qwen 服务发送购物提示词，保存实际请求与响应示例。"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from vllm_structured_output_probe import (
    chat_completions_url,
    final_answer_tool,
    first_message,
    post_json,
    validate_final_answer,
)


INTENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {"type": "string", "enum": ["recommend", "clarify"]},
        "category": {"type": "string"},
        "budget_max": {"type": ["number", "null"]},
        "features": {"type": "array", "items": {"type": "string"}},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "category", "budget_max", "features", "missing_fields"],
}

INTENT_PROMPT = (
    "你是购物需求提取助手。只提取用户明确提供的信息，不补造预算、品牌或商品。"
    "category 使用中文类目名；budget_max 是人民币预算上限，未提供时为 null。"
    "features 只保留用户明确提供的用途、尺寸、性能要求和排除条件；"
    "未提及的条件不添加，不填写‘无’等默认条件。"
    "本示例只将预算列为必需信息：缺少预算时 intent=clarify，"
    "missing_fields=[\"budget_max\"]；已有预算时 intent=recommend，missing_fields=[]。"
    "按照给定的 JSON Schema 输出。"
)


def requests(model: str) -> list[tuple[str, dict]]:
    common = {
        "model": model,
        "temperature": 0,
        "max_tokens": 512,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    examples = []
    for name, prompt in [
        ("购物条件提取", "我想买一个500元以内的通勤背包，能装14英寸电脑，下雨时防泼水，不要皮质。"),
        ("缺少预算时澄清", "帮我选双跑鞋，主要晚上慢跑。"),
    ]:
        examples.append((name, {
            **common,
            "messages": [
                {"role": "system", "content": INTENT_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "shopping_intent", "strict": True, "schema": INTENT_SCHEMA},
            },
        }))
    examples.append(("前端最终回答工具", {
        **common,
        "messages": [
            {"role": "system", "content": (
                "你是购物助手。尚未检索商品，不要编造商品、价格或 item_id。"
                "用户缺少预算时，调用 emit_final_answer 输出两个 block："
                "第一个 type=text，用一句话确认用户需求，不宣称已经开始搜索；"
                "第二个 type=followup_question，询问预算上限。"
                "两个 block 的 card_set_id、item_ids、layout 都设为 null。"
            )},
            {"role": "user", "content": "帮我选双跑鞋，主要晚上慢跑。"},
        ],
        "tools": [final_answer_tool()],
        "tool_choice": {"type": "function", "function": {"name": "emit_final_answer"}},
        "parallel_tool_calls": False,
    }))
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18082/v1")
    parser.add_argument("--model", default="qwen35-4b")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = []
    for name, payload in requests(args.model):
        started = time.monotonic()
        response = post_json(
            chat_completions_url(args.base_url), payload,
            api_key=os.environ.get("VLLM_API_KEY"), timeout=30,
        )
        message = first_message(response)
        if "tools" in payload:
            calls = message.get("tool_calls", [])
            if len(calls) != 1 or calls[0]["function"]["name"] != "emit_final_answer":
                raise ValueError("响应必须调用一次 emit_final_answer")
            parsed = validate_final_answer(json.loads(calls[0]["function"]["arguments"]))
        else:
            parsed = json.loads(message["content"])
            if set(parsed) != set(INTENT_SCHEMA["required"]):
                raise ValueError("购物条件字段不匹配")
        records.append({
            "name": name, "request": payload, "response": response,
            "parsed_output": parsed, "elapsed_seconds": round(time.monotonic() - started, 3),
        })
        print(json.dumps({"name": name, "output": parsed}, ensure_ascii=False), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model, "examples": records,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
