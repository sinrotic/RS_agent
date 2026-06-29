from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request


UNBOUND_RESPONSE_MARKERS = (
    "unbound_fallback",
    "no_recommender_bound",
    "no_service_bound",
    "online engine is available without a bound recommender",
    "agent engine is available without a bound service",
    "feedback recorded by unbound agent engine",
)


@dataclass(frozen=True)
class SmokeCase:
    name: str
    method: str
    path: str
    payload: dict[str, Any] | None = None
    expected_status: int = 200


def build_cases() -> list[SmokeCase]:
    sequence = {"recent_item_ids": ["i3", "i2", "i1"]}
    return [
        SmokeCase("online_health", "GET", "/api/health/online"),
        SmokeCase("agent_health", "GET", "/api/health/agent"),
        SmokeCase("frontend_root", "GET", "/"),
        SmokeCase("recommend", "POST", "/api/recommend", {"user_sequence": sequence, "top_k": 2}),
        SmokeCase("recall", "POST", "/api/recall", {"user_sequence": sequence, "candidate_pool_size": 2}),
        SmokeCase("rank", "POST", "/api/rank", {"candidate_item_ids": ["i2", "i1"], "return_top_k": 1}),
        SmokeCase("session_start", "POST", "/api/session/start", {"user_id": "local-session"}),
        SmokeCase("chat", "POST", "/api/chat", {"session_id": "local-session", "message": "想看新品"}),
        SmokeCase(
            "feedback",
            "POST",
            "/api/feedback",
            {"session_id": "local-session", "action_type": "skip", "item_id": "i1", "comment": "smoke"},
        ),
        SmokeCase("rag", "POST", "/api/rag/query", {"query": "running shoes", "max_chunks": 1}),
    ]


def call_case(base_url: str, case: SmokeCase, timeout: float) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if case.payload is not None:
        data = json.dumps(case.payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{base_url.rstrip('/')}{case.path}", data=data, method=case.method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
            status = response.status
    except error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        status = exc.code
    body_failure = _response_body_failure(case, body) if status == case.expected_status else None
    return {
        "name": case.name,
        "method": case.method,
        "path": case.path,
        "status": status,
        "passed": status == case.expected_status and body_failure is None,
        "failure": body_failure,
        "body_preview": body[:300],
    }


def _response_body_failure(case: SmokeCase, body: str) -> str | None:
    normalized = body.lower()
    for marker in UNBOUND_RESPONSE_MARKERS:
        if marker in normalized:
            return f"response contains degraded shell marker: {marker}"

    if case.name in {"recommend", "chat", "feedback"}:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return "expected JSON response body"
        if case.name == "recommend" and not (isinstance(payload, dict) and ("display" in payload or "items" in payload)):
            return "recommend response lacks display/items"
        if case.name in {"chat", "feedback"}:
            display = payload.get("display") if isinstance(payload, dict) else None
            if not isinstance(display, dict) or not display.get("assistant_message"):
                return f"{case.name} response lacks display.assistant_message"
    return None


def wait_until_ready(base_url: str, timeout: float, deadline_seconds: float) -> bool:
    deadline = time.monotonic() + deadline_seconds
    probes = [SmokeCase("online_health", "GET", "/api/health/online"), SmokeCase("agent_health", "GET", "/api/health/agent")]
    while time.monotonic() < deadline:
        if all(call_case(base_url, probe, timeout)["passed"] for probe in probes):
            return True
        time.sleep(1.0)
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run lightweight RS Agent gateway smoke against an already running Nginx gateway.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--ready-timeout", type=float, default=30.0, help="Seconds to wait for online and agent health routes before smoke cases.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not wait_until_ready(args.base_url, args.timeout, args.ready_timeout):
        print(f"gateway dependencies were not ready within {args.ready_timeout:.1f}s", file=sys.stderr)
    results = [call_case(args.base_url, case, args.timeout) for case in build_cases()]
    report = {
        "status": "passed" if all(result["passed"] for result in results) else "failed",
        "base_url": args.base_url,
        "cases": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
