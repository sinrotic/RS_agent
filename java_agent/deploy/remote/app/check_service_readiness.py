#!/usr/bin/env python3
"""在发布前检查真实 HTTP 就绪状态及选定模型的上下文容量，不加载模型。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.error
import urllib.request

SERVICES = {"gateway": 18088, "user": 18101, "catalog": 18102, "recommend": 18103,
            "agent": 18104, "model": 18105, "platform-trace": 18108}


def read_json(url: str, timeout: float = 3) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def check_service(name: str, url: str) -> dict:
    try:
        body = read_json(url)
        return {"name": name, "ready": body.get("status") == "UP", "status": body.get("status", "UNKNOWN")}
    except (OSError, ValueError) as error:
        # Error class only: connection errors can contain credentials from a URL.
        return {"name": name, "ready": False, "error": type(error).__name__}


def check_model(base_url: str, model_name: str, minimum: int) -> dict:
    try:
        models = read_json(base_url.rstrip("/") + "/models").get("data", [])
        selected = next((model for model in models if model.get("id") == model_name), None)
        length = selected.get("max_model_len") if selected else None
        ready = isinstance(length, int) and not isinstance(length, bool) and length >= minimum
        return {"name": model_name, "ready": ready, "max_model_len": length, "required_context": minimum,
                "reason": "compatible" if ready else "missing_model_or_insufficient_context"}
    except (OSError, ValueError, TypeError) as error:
        return {"name": model_name, "ready": False, "error": type(error).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model-url", help="仅在 Agent 使用本地模型时填写其 /v1 地址")
    parser.add_argument("--model", default="qwen35-4b")
    parser.add_argument("--minimum-context", type=int, default=16384)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.minimum_context < 16384:
        parser.error("minimum-context must be at least 16384")
    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(lambda pair: check_service(pair[0],
                           f"http://{args.host}:{pair[1]}/actuator/health/readiness"), SERVICES.items()))
    model = check_model(args.model_url, args.model, args.minimum_context) if args.model_url else {
        "checked": False, "ready": True, "reason": "no_local_model_selected"}
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "services": checks, "model": model,
              "ready": all(item["ready"] for item in checks) and model["ready"],
              "scope": "readiness_and_context_only; functional_acceptance_still_required"}
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
