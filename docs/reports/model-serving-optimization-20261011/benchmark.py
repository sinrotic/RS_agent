#!/usr/bin/env python3
"""仅调用已运行模型的小规模基线；不加载权重、不重启或修改服务。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics
import subprocess
import time
import urllib.request
import uuid


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "category": {"type": "string"},
        "budget_max": {"type": "number"},
        "features": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "budget_max", "features"],
}
SYSTEM = "你是购物需求提取助手。只提取用户明确提供的信息，不编造商品。category为中文类目，budget_max为人民币预算上限，features只包含已提供的条件。"
USER = "我想买一个500元以内的通勤背包，能装14英寸电脑，防泼水，不要皮质。"


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def metrics(base_url: str) -> dict:
    with urllib.request.urlopen(base_url.removesuffix("/v1") + "/metrics", timeout=5) as response:
        lines = response.read().decode().splitlines()
    wanted = (
        "num_requests_running", "num_requests_waiting", "prefix_cache_queries_total",
        "prefix_cache_hits_total", "num_preemptions_total", "kv_cache_usage_perc",
        "request_prompt_tokens_sum", "request_generation_tokens_sum",
    )
    result = {}
    for name in wanted:
        matches = [float(line.rsplit(" ", 1)[1]) for line in lines
                   if re.match(r"vllm:" + name + r"(?:\{|\s)", line)]
        if matches:
            result[name] = sum(matches)
    return result


def payload(model: str, system: str = SYSTEM, *, tool: bool = False, decode: bool = False) -> dict:
    result = {
        "model": model, "temperature": 0, "max_tokens": 256,
        "stream": True, "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": USER}],
    }
    if decode:
        result.update({"max_tokens": 128, "ignore_eos": True,
                       "messages": [{"role": "system", "content": "你是中文购物助手。"},
                                    {"role": "user", "content": "详细介绍挑选通勤背包的注意事项，至少写600字。"}]})
    elif tool:
        result.update({
            "tools": [{"type": "function", "function": {
                "name": "extract_shopping_intent", "description": "提取购物需求", "strict": True, "parameters": SCHEMA,
            }}],
            "tool_choice": {"type": "function", "function": {"name": "extract_shopping_intent"}},
            "parallel_tool_calls": False,
        })
    else:
        result["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "shopping_intent", "strict": True, "schema": SCHEMA,
        }}
    return result


def measure(base_url: str, request_payload: dict, scenario: str, *, fixed_decode: bool = False) -> dict:
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(request_payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    started = time.perf_counter()
    first_payload = None
    content = ""
    arguments = ""
    tool_name = ""
    finish = None
    usage = None
    done = False
    with urllib.request.urlopen(request, timeout=30) as response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done = True
                break
            event = json.loads(data)
            if event.get("error"):
                raise RuntimeError(event["error"])
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("refusal"):
                    raise ValueError("模型拒绝了测试请求")
                part = delta.get("content") or ""
                content += part
                calls = delta.get("tool_calls", [])
                if len(calls) > 1 or any(call.get("index", 0) != 0 for call in calls):
                    raise ValueError("意外的多个工具调用")
                for call in calls:
                    function = call.get("function", {})
                    tool_name += function.get("name") or ""
                    fragment = function.get("arguments") or ""
                    arguments += fragment
                    part += fragment
                if part and first_payload is None:
                    first_payload = time.perf_counter() - started
                finish = choice.get("finish_reason") or finish
    elapsed = time.perf_counter() - started
    if not done or not usage or first_payload is None:
        raise ValueError("SSE 缺少完整结束、usage 或有效生成内容")
    if fixed_decode:
        if finish != "length" or usage["completion_tokens"] != 128:
            raise ValueError("固定长度解码测试没有生成128 tokens")
        parsed = None
    else:
        if finish not in {"stop", "tool_calls"}:
            raise ValueError("结构化响应被截断或异常结束")
        if "tools" in request_payload and tool_name != "extract_shopping_intent":
            raise ValueError("未调用指定测试工具")
        parsed = json.loads(arguments or content)
        if (set(parsed) != set(SCHEMA["required"]) or not isinstance(parsed["category"], str)
                or "背包" not in parsed["category"] or parsed["budget_max"] != 500):
            raise ValueError("提取结果不满足字段、类目或预算要求")
        if not isinstance(parsed["features"], list) or not all(isinstance(x, str) for x in parsed["features"]):
            raise ValueError("features 字段类型错误")
    tokens = usage["completion_tokens"]
    return {
        "scenario": scenario,
        "first_content_seconds": round(first_payload, 6),
        "e2e_seconds": round(elapsed, 6),
        "mean_token_time_proxy_seconds": round((elapsed - first_payload) / (tokens - 1), 6) if tokens > 1 else None,
        "finish_reason": finish, "usage": usage,
        "parsed_output": parsed, "raw_output": arguments or content,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18082/v1")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model_info = get_json(args.base_url + "/models")
    model = model_info["data"][0]["id"]
    initial_metrics = metrics(args.base_url)
    if initial_metrics.get("num_requests_running", 0) or initial_metrics.get("num_requests_waiting", 0):
        raise RuntimeError("当前有模型请求，暂停基线实验")
    records = []
    gpu_before = subprocess.check_output([
        "nvidia-smi", "--query-gpu=index,name,memory.used,utilization.gpu,pstate,clocks.current.sm", "--format=csv",
    ], text=True)

    def sequential(name: str, request_payload: dict, count: int, **options) -> None:
        for _ in range(count):
            record = measure(args.base_url, request_payload, name, **options)
            records.append(record)
        print(json.dumps({"scenario": name, "samples": count}, ensure_ascii=False), flush=True)

    sequential("short_json_warmup", payload(model), 1)
    sequential("short_json", payload(model), 6)
    for pair in range(3):
        # 开头的随机标识使每组长前缀独立；不调用缓存清空接口影响其他用户。
        prefix = "测试批次 " + uuid.uuid4().hex + "\n" + "\n".join(
            f"资料{i:03d}：这是虚构的占位资料，只用于测量长上下文前填充，不是实际商品证据。" for i in range(100)
        ) + "\n" + SYSTEM
        sequential(f"long_prefix_first_{pair}", payload(model, prefix), 1)
        sequential(f"long_prefix_repeat_{pair}", payload(model, prefix), 1)
    sequential("named_tool_warmup", payload(model, tool=True), 1)
    sequential("named_tool", payload(model, tool=True), 6)
    sequential("decode_128", payload(model, decode=True), 4, fixed_decode=True)
    batch_started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(measure, args.base_url, payload(model, tool=True), "named_tool_concurrency4") for _ in range(8)]
        for future in futures:
            records.append(future.result())
    batch_elapsed = time.perf_counter() - batch_started
    summaries = {}
    for scenario in sorted({row["scenario"] for row in records}):
        rows = [row for row in records if row["scenario"] == scenario]
        summaries[scenario] = {
            "samples": len(rows),
            "first_content_median_ms": round(statistics.median(row["first_content_seconds"] for row in rows)*1000, 2),
            "e2e_median_ms": round(statistics.median(row["e2e_seconds"] for row in rows)*1000, 2),
            "e2e_max_ms": round(max(row["e2e_seconds"] for row in rows)*1000, 2),
            "completion_tokens_median": statistics.median(row["usage"]["completion_tokens"] for row in rows),
        }
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "model_info": model_info,
        "scope": "主机 loopback 上的小样本模型直连测试；非完整Agent、非生产P95、非持续容量。first_content是首个文本/工具参数片段，mean_token_time_proxy是估算值而非逐token ITL。",
        "structured_samples": 28, "fixed_decode_samples": 4,
        "request_templates": {"short_json": payload(model), "named_tool": payload(model, tool=True), "decode_128": payload(model, decode=True)},
        "gpu_before": gpu_before, "initial_metrics": initial_metrics,
        "final_metrics": metrics(args.base_url), "concurrency4_batch_seconds": round(batch_elapsed, 4),
        "summaries": summaries, "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
