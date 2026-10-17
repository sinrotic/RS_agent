#!/usr/bin/env python3
"""Warm vLLM prefix cache for RS Agent profiles.

The script is intentionally stdlib-only so it can run on the remote model host
without adding deployment dependencies.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Callable


DEFAULT_SYSTEM_PROMPT = (
    "You are a Chinese shopping recommendation agent. Keep answers concise, "
    "use available evidence, and do not expose internal tool names or plans."
)

PROFILE_DESCRIPTIONS = {
    "rs_agent": "Main recommendation agent for shopping dialogue, candidate selection, evidence use, and explanation.",
    "rag_agent": "Internal recommendation RAG agent for query support and candidate-scoped evidence compression.",
}


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def chat_completions_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/chat/completions"


def models_url(base_url: str) -> str:
    return normalize_base_url(base_url) + "/models"


def read_system_prompt(prompt_file: str | None, prompt_url: str | None, timeout: float) -> str:
    if prompt_file:
        with open(prompt_file, "r", encoding="utf-8") as handle:
            content = handle.read().strip()
        if content:
            return content
    if prompt_url:
        try:
            data = get_json(prompt_url, timeout=timeout)
            content = data.get("content") or data.get("system_prompt")
            if isinstance(content, str) and content.strip():
                return content.strip()
        except Exception as error:  # noqa: BLE001 - deployment script must fall back cleanly
            print(f"[warmup] failed to fetch system prompt from {prompt_url}: {error}", file=sys.stderr)
    return DEFAULT_SYSTEM_PROMPT


def profile_context(profile: str) -> dict[str, object]:
    return {
        "agent_name": profile,
        "agent_description": PROFILE_DESCRIPTIONS.get(profile, ""),
        "warmup": True,
    }


def build_profile_system_prompt(system_prompt: str, profile: str) -> str:
    context_json = json.dumps(profile_context(profile), ensure_ascii=False, separators=(",", ":"))
    return (
        system_prompt
        + "\n\nrequest_context:\n"
        + context_json
        + "\n\nPrefix-cache warmup request. Cache this stable agent prefix for low-latency serving."
    )


def build_warmup_payloads(
    model: str,
    system_prompt: str,
    profiles: list[str],
    max_tokens: int,
) -> list[dict[str, object]]:
    payloads = []
    for profile in profiles:
        payloads.append(
            {
                "profile": profile,
                "payload": {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": build_profile_system_prompt(system_prompt, profile)},
                        {"role": "user", "content": "Warm the stable RS Agent prefix cache."},
                    ],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            }
        )
    return payloads


def read_warmup_payloads(payload_file: str, model: str, max_tokens: int) -> list[dict[str, object]]:
    """保留真实模板输入；预热只生成，不执行返回的工具调用。"""
    with open(payload_file, "r", encoding="utf-8") as handle:
        records = json.load(handle)
    if not isinstance(records, list) or not 1 <= len(records) <= 8:
        raise ValueError("预热文件必须包含 1 至 8 个请求记录")
    result = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("profile"), str):
            raise ValueError("每个预热记录必须有 profile 字符串")
        payload = copy.deepcopy(record.get("payload"))
        if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list) or not payload["messages"]:
            raise ValueError("每个预热请求必须有非空 messages")
        payload.update(model=model, max_tokens=max_tokens, temperature=0, stream=False)
        payload.pop("stream_options", None)
        payload.pop("max_completion_tokens", None)
        payload.pop("min_tokens", None)
        payload["n"] = 1
        result.append({"profile": record["profile"], "payload": payload})
    return result


def server_is_idle(base_url: str, timeout: float) -> bool:
    url = normalize_base_url(base_url).removesuffix("/v1") + "/metrics"
    request = urllib.request.Request(url, headers={"Accept": "text/plain"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        lines = response.read().decode("utf-8").splitlines()
    values: dict[str, list[float]] = {"num_requests_running": [], "num_requests_waiting": []}
    for line in lines:
        for name in values:
            if re.match(r"vllm:" + name + r"(?:\{|\s)", line):
                values[name].append(float(line.rsplit(" ", 1)[1]))
    if not all(values.values()):
        raise ValueError("模型指标缺少运行或等待请求数")
    return all(value == 0 for samples in values.values() for value in samples)


def get_json(url: str, timeout: float) -> dict[str, object]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def wait_until_ready(base_url: str, timeout_sec: float, interval_sec: float, request_timeout: float) -> None:
    deadline = time.monotonic() + timeout_sec
    last_error = None
    url = models_url(base_url)
    while time.monotonic() < deadline:
        try:
            get_json(url, timeout=request_timeout)
            return
        except Exception as error:  # noqa: BLE001 - readiness polling reports last error
            last_error = error
            time.sleep(interval_sec)
    raise TimeoutError(f"vLLM did not become ready at {url}: {last_error}")


def build_kernel_warmup_batches(model: str, batch_sizes: list[int]) -> list[dict[str, object]]:
    """Qwen 的有界合成输入：覆盖首次部分命中及 16/8/4/2/1 对齐类别。

    KV 前缀命中和 Triton 内核编译是不同缓存。短批次强制生成两 token，
    确保除 prefill 外也经过一次 decode；不包含真实用户数据或工具执行。
    """
    if not batch_sizes or len(set(batch_sizes)) != len(batch_sizes) or any(
        not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= 16 for size in batch_sizes
    ):
        raise ValueError("内核预热批次须为不重复的 1 至 16 整数")
    common = {"model": model, "temperature": 0, "seed": 0, "stream": False,
              "n": 1, "ignore_eos": True}
    full = [1030] + [1000] * 6607
    batches = [{"phase": "full-prefill", "label": "full-6608",
                "payload": dict(common, prompt=full, max_tokens=1)}]
    for index, remainder in enumerate((0, 1, 2, 4, 8)):
        length = 6608 + remainder
        batches.append({"phase": "partial-prefix", "label": f"partial-{length}",
                        "payload": dict(common, prompt=full[:5000] + [1001 + index] * (length - 5000), max_tokens=1)})
    for size in batch_sizes:
        prompts = [[1100 + index] + [1000] * 255 for index in range(size)]
        batches.append({"phase": "batch-decode", "label": f"decode-{size}",
                        "payload": dict(common, prompt=prompts, max_tokens=2)})
    return batches


def run_kernel_warmup(
    base_url: str, model: str, batch_sizes: list[int], timeout: float,
    post_json: Callable[[str, dict[str, object], float], dict[str, object]] = post_json,
    idle_check: Callable[[], bool] | None = None,
) -> None:
    for item in build_kernel_warmup_batches(model, batch_sizes):
        if idle_check is not None and not idle_check():
            # 不把中断的预热当作成功，不允许启动器提前发布 ready。
            raise RuntimeError("业务请求进入，内核预热中断；空闲后可重新执行")
        payload = item["payload"]
        count = len(payload["prompt"]) if item["phase"] == "batch-decode" else 1
        started = time.perf_counter()
        result = post_json(normalize_base_url(base_url) + "/completions", payload, timeout)
        if len(result.get("choices", [])) != count or result.get("usage", {}).get("completion_tokens") != count * payload["max_tokens"]:
            raise ValueError(f"内核预热输出不完整：{item['label']}")
        print(f"[warmup] kernel={item['label']} completed in {(time.perf_counter() - started) * 1000:.1f}ms", flush=True)


def run_warmup_once(
    base_url: str,
    model: str,
    system_prompt: str,
    profiles: list[str],
    max_tokens: int,
    timeout: float,
    delay_after_warmup_sec: float,
    post_json: Callable[[str, dict[str, object], float], dict[str, object]] = post_json,
    sleep: Callable[[float], None] = time.sleep,
    payloads: list[dict[str, object]] | None = None,
    idle_check: Callable[[], bool] | None = None,
) -> None:
    url = chat_completions_url(base_url)
    for item in payloads if payloads is not None else build_warmup_payloads(model, system_prompt, profiles, max_tokens):
        if idle_check is not None and not idle_check():
            print("[warmup] 业务请求进入，停止本轮剩余前缀保温", flush=True)
            return
        profile = item["profile"]
        payload = item["payload"]
        started = time.perf_counter()
        post_json(url, payload, timeout)
        elapsed_ms = (time.perf_counter() - started) * 1000
        print(f"[warmup] profile={profile} completed in {elapsed_ms:.1f}ms", flush=True)
    if delay_after_warmup_sec > 0:
        sleep(delay_after_warmup_sec)


def run_keepalive(args: argparse.Namespace, system_prompt: str, payloads: list[dict[str, object]] | None = None) -> None:
    while True:
        try:
            if args.only_when_idle and not server_is_idle(args.base_url, min(args.request_timeout_sec, 5)):
                print("[warmup] 模型有业务请求，跳过本次定时预热", flush=True)
            else:
                run_warmup_once(
                    base_url=args.base_url,
                    model=args.model,
                    system_prompt=system_prompt,
                    profiles=args.profiles,
                    max_tokens=args.max_tokens,
                    timeout=args.request_timeout_sec,
                    delay_after_warmup_sec=0,
                    payloads=payloads,
                    idle_check=(lambda: server_is_idle(args.base_url, min(args.request_timeout_sec, 5)))
                    if args.only_when_idle and args.recheck_idle_per_prefix else None,
                )
        except Exception as error:  # noqa: BLE001 - keepalive should continue after transient failures
            print(f"[warmup] keepalive failed: {error}", file=sys.stderr, flush=True)
        time.sleep(args.keepalive_interval_sec)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Warm and keep vLLM prefix cache hot for RS Agent profiles.")
    parser.add_argument("--base-url", default=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:18082/v1"))
    parser.add_argument("--model", default=os.getenv("VLLM_MODEL", "qwen35-4b"))
    parser.add_argument("--profiles", nargs="+", default=os.getenv("VLLM_WARMUP_PROFILES", "rs_agent rag_agent").split())
    parser.add_argument("--system-prompt-file", default=os.getenv("AGENT_SYSTEM_PROMPT_FILE"))
    parser.add_argument("--system-prompt-url", default=os.getenv("AGENT_SYSTEM_PROMPT_URL"))
    parser.add_argument("--payload-file", default=os.getenv("VLLM_WARMUP_PAYLOAD_FILE"))
    parser.add_argument("--only-when-idle", action=argparse.BooleanOptionalAction,
                        default=os.getenv("VLLM_WARMUP_ONLY_WHEN_IDLE", "true").lower() == "true")
    parser.add_argument("--recheck-idle-per-prefix", action=argparse.BooleanOptionalAction,
                        default=os.getenv("VLLM_RECHECK_IDLE_PER_PREFIX", "false").lower() == "true")
    parser.add_argument("--max-tokens", type=int, default=int(os.getenv("VLLM_WARMUP_MAX_TOKENS", "1")))
    parser.add_argument("--request-timeout-sec", type=float, default=float(os.getenv("VLLM_WARMUP_REQUEST_TIMEOUT_SEC", "120")))
    parser.add_argument("--ready-timeout-sec", type=float, default=float(os.getenv("VLLM_READY_TIMEOUT_SEC", "300")))
    parser.add_argument("--ready-interval-sec", type=float, default=float(os.getenv("VLLM_READY_INTERVAL_SEC", "2")))
    parser.add_argument("--delay-after-warmup-sec", type=float, default=float(os.getenv("VLLM_DELAY_AFTER_WARMUP_SEC", "2")))
    # The launcher decides whether to start the separate keepalive process.
    # Reading VLLM_PREFIX_KEEPALIVE here would make the one-shot startup warmup
    # loop forever and prevent creation of the readiness file.
    parser.add_argument("--keepalive", action="store_true")
    parser.add_argument("--keepalive-interval-sec", type=float, default=float(os.getenv("VLLM_KEEPALIVE_INTERVAL_SEC", "300")))
    parser.add_argument("--skip-ready-wait", action="store_true")
    parser.add_argument("--kernel-warmup", action=argparse.BooleanOptionalAction,
                        default=os.getenv("VLLM_KERNEL_WARMUP", "false").lower() == "true")
    parser.add_argument("--kernel-batch-sizes", nargs="+", type=int,
                        default=[int(size) for size in os.getenv("VLLM_KERNEL_WARMUP_BATCH_SIZES", "1 4 8 16").split()])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    payloads = read_warmup_payloads(args.payload_file, args.model, args.max_tokens) if args.payload_file else None
    if not args.skip_ready_wait:
        wait_until_ready(args.base_url, args.ready_timeout_sec, args.ready_interval_sec, args.request_timeout_sec)
    system_prompt = "" if payloads is not None else read_system_prompt(args.system_prompt_file, args.system_prompt_url, args.request_timeout_sec)
    if args.keepalive:
        run_keepalive(args, system_prompt, payloads)
    else:
        idle_check = None
        if args.kernel_warmup:
            if args.only_when_idle:
                def idle_check():
                    if not server_is_idle(args.base_url, min(args.request_timeout_sec, 5)):
                        raise RuntimeError("业务请求进入，预热中断；空闲后可重新执行")
                    return True
            run_kernel_warmup(args.base_url, args.model, args.kernel_batch_sizes, args.request_timeout_sec,
                              idle_check=idle_check)
        run_warmup_once(
            base_url=args.base_url,
            model=args.model,
            system_prompt=system_prompt,
            profiles=args.profiles,
            max_tokens=args.max_tokens,
            timeout=args.request_timeout_sec,
            delay_after_warmup_sec=args.delay_after_warmup_sec,
            payloads=payloads,
            idle_check=idle_check,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
