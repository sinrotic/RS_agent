from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REQUEST_ID_HEADER = "X-Request-ID"
DEFAULT_CHAT_MESSAGE = "For commute, prefer bluetooth and Audio"
DEFAULT_FEEDBACK_COMMENT = "Smoke trial asks for a short explanation."


class SmokeFailure(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test RS Agent trial serving endpoints.")
    parser.add_argument("--base-url", required=True, help="Serving base URL, for example http://127.0.0.1:8000.")
    parser.add_argument(
        "--trial-token",
        default=os.environ.get("RS_TRIAL_TOKEN", ""),
        help="Low-privilege trial token. Prefer RS_TRIAL_TOKEN env; CLI value is for local temporary smoke only.",
    )
    parser.add_argument(
        "--debug-token",
        default=os.environ.get("RS_DEBUG_TOKEN", ""),
        help="Debug token. Prefer RS_DEBUG_TOKEN env; CLI value is for local temporary smoke only.",
    )
    parser.add_argument("--user-id", default="online-u1", help="User id used in session and sequence requests.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout in seconds.")
    parser.add_argument("--verbose", action="store_true", help="Print each completed smoke step.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results: list[dict[str, Any]] = []
    session_id = ""
    try:
        _validate_base_url(args.base_url)
        health = _request_json(args.base_url, "GET", "/health", step="health", timeout=args.timeout)
        _assert_equal(health["json"].get("status"), "ok", "health.status")
        _assert_equal(health["json"].get("service"), "rs-agent-serving", "health.service")
        _record(results, health, args.verbose)

        ready = _request_json(args.base_url, "GET", "/ready", step="ready", token=args.trial_token, timeout=args.timeout)
        _assert_in(ready["json"].get("status"), {"ready", "degraded"}, "ready.status")
        _assert_equal(ready["json"].get("service"), "rs-agent-serving", "ready.service")
        _assert_is_dict(ready["json"].get("online_route"), "ready.online_route")
        _record(results, ready, args.verbose)

        start = _request_json(
            args.base_url,
            "POST",
            "/session/start",
            step="session-start",
            payload={"user_id": args.user_id},
            token=args.trial_token,
            timeout=args.timeout,
        )
        session_id = _non_empty_string(start["json"].get("session_id"), "session_start.session_id")
        _record(results, start, args.verbose)

        chat = _request_json(
            args.base_url,
            "POST",
            "/chat",
            step="chat",
            payload={"session_id": session_id, "message": DEFAULT_CHAT_MESSAGE},
            token=args.trial_token,
            timeout=args.timeout,
        )
        _assert_equal(chat["json"].get("session_id"), session_id, "chat.session_id")
        chat_display = _display_payload(chat["json"], "chat.display", session_id)
        _record(results, chat, args.verbose)

        feedback_payload: dict[str, Any] = {
            "session_id": session_id,
            "action_type": "why",
            "comment": DEFAULT_FEEDBACK_COMMENT,
        }
        item_id = _first_display_item_id(chat_display)
        if item_id:
            feedback_payload["item_id"] = item_id
        feedback = _request_json(
            args.base_url,
            "POST",
            "/feedback",
            step="feedback",
            payload=feedback_payload,
            token=args.trial_token,
            timeout=args.timeout,
        )
        _assert_equal(feedback["json"].get("session_id"), session_id, "feedback.session_id")
        _display_payload(feedback["json"], "feedback.display", session_id)
        _record(results, feedback, args.verbose)

        export = _request_json(
            args.base_url,
            "GET",
            f"/session/{session_id}",
            step="session-export",
            token=args.trial_token,
            timeout=args.timeout,
        )
        _assert_equal(export["json"].get("session_id"), session_id, "session_export.session_id")
        _assert_in(str(export["json"].get("user_id", "")), {args.user_id, ""}, "session_export.user_id")
        _assert_min_int(export["json"].get("turn_count"), 2, "session_export.turn_count")
        timeline = _assert_is_dict(export["json"].get("public_timeline"), "session_export.public_timeline")
        _assert_equal(timeline.get("schema_version"), "rs_agent_public_timeline_v1", "public_timeline.schema_version")
        _assert_min_len(timeline.get("events"), 2, "public_timeline.events")
        _assert_min_len(export["json"].get("display_responses"), 2, "session_export.display_responses")
        _record(results, export, args.verbose)

        recommend_payload = {
            "user_sequence": {
                "user_id": args.user_id,
                "recent_item_sequence": ["seed_audio"],
                "recent_positive_item_sequence": ["seed_audio"],
                "recent_strong_positive_item_sequence": [],
            },
            "feedback_text": "prefer bluetooth Audio",
            "top_k": 3,
            "candidate_pool_size": 20,
            "complete_pool500": True,
        }
        recommend = _request_json(
            args.base_url,
            "POST",
            "/recommend",
            step="recommend",
            payload=recommend_payload,
            token=args.trial_token,
            timeout=args.timeout,
        )
        _non_empty_string(recommend["json"].get("request_id"), "recommend.request_id")
        recommend_display = _display_payload(recommend["json"], "recommend.display")
        items = _assert_is_list(recommend["json"].get("items"), "recommend.items")
        _assert_equal(recommend["json"].get("item_count"), len(items), "recommend.item_count")
        candidate_count = _assert_int(recommend["json"].get("candidate_count"), "recommend.candidate_count")
        if candidate_count < len(items):
            raise SmokeFailure("recommend.candidate_count must be >= len(items)")
        if not isinstance(recommend["json"].get("fallback_used"), bool):
            raise SmokeFailure("recommend.fallback_used must be bool")
        _assert_is_list(recommend_display.get("items"), "recommend.display.items")
        _record(results, recommend, args.verbose)

        if args.debug_token:
            recall_payload = {
                "user_sequence": {
                    "user_id": args.user_id,
                    "recent_item_sequence": ["seed_audio"],
                    "recent_positive_item_sequence": ["seed_audio"],
                    "recent_strong_positive_item_sequence": [],
                },
                "candidate_pool_size": 20,
                "prior_turn_items": [],
            }
            if args.trial_token:
                trial_recall = _request_json(
                    args.base_url,
                    "POST",
                    "/recall",
                    step="recall-trial-forbidden",
                    payload=recall_payload,
                    token=args.trial_token,
                    timeout=args.timeout,
                    expected_status=403,
                )
                detail = _assert_is_dict(trial_recall["json"].get("detail"), "recall_trial.detail")
                _assert_equal(detail.get("code"), "FORBIDDEN", "recall_trial.detail.code")
                _record(results, trial_recall, args.verbose)

            debug_recall = _request_json(
                args.base_url,
                "POST",
                "/recall",
                step="recall-debug",
                payload=recall_payload,
                token=args.debug_token,
                timeout=args.timeout,
            )
            _non_empty_string(debug_recall["json"].get("request_id"), "recall_debug.request_id")
            candidate_item_ids = _assert_is_list(debug_recall["json"].get("candidate_item_ids"), "recall_debug.candidate_item_ids")
            _assert_equal(debug_recall["json"].get("candidate_count"), len(candidate_item_ids), "recall_debug.candidate_count")
            _assert_is_dict(debug_recall["json"].get("retrieval_summary"), "recall_debug.retrieval_summary")
            for forbidden_key in ("display", "items", "diagnostics", "ranking"):
                if forbidden_key in debug_recall["json"]:
                    raise SmokeFailure(f"recall_debug response must not contain {forbidden_key!r}")
            _record(results, debug_recall, args.verbose)

    except SmokeFailure as exc:
        print(json.dumps({"ok": False, "error": str(exc), "completed_steps": results}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, "base_url": args.base_url.rstrip("/"), "session_id": session_id, "steps": results}, ensure_ascii=False, indent=2))
    return 0


def _validate_base_url(base_url: str) -> None:
    if not base_url.startswith(("http://", "https://")):
        raise SmokeFailure("base-url must include http:// or https://")


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    step: str,
    payload: dict[str, Any] | None = None,
    token: str = "",
    timeout: float = 10.0,
    expected_status: int = 200,
) -> dict[str, Any]:
    request_id = f"smoke-{step}-{uuid.uuid4()}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json", REQUEST_ID_HEADER: request_id}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)

    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            response_request_id = response.headers.get(REQUEST_ID_HEADER)
            raw_body = response.read()
    except HTTPError as exc:
        status = int(exc.code)
        response_request_id = exc.headers.get(REQUEST_ID_HEADER)
        raw_body = exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise SmokeFailure(f"{step} {method} {path} network error: {exc}. Is the service running at {base_url.rstrip('/')}?") from exc

    text = raw_body.decode("utf-8", errors="replace")
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{step} {method} {path} returned non-JSON body: {text[:500]}") from exc

    if not response_request_id:
        raise SmokeFailure(f"{step} {method} {path} missing {REQUEST_ID_HEADER} response header")
    if response_request_id != request_id:
        raise SmokeFailure(f"{step} {method} {path} request id mismatch: sent={request_id} got={response_request_id}")
    if status != expected_status:
        raise SmokeFailure(f"{step} {method} {path} expected HTTP {expected_status}, got {status}, body={str(data)[:500]}")

    return {"step": step, "method": method, "path": path, "status": status, "request_id": response_request_id, "json": data}


def _record(results: list[dict[str, Any]], result: dict[str, Any], verbose: bool) -> None:
    item = {key: result[key] for key in ("step", "method", "path", "status", "request_id")}
    results.append(item)
    if verbose:
        print(f"[OK] {item['step']} {item['method']} {item['path']} -> {item['status']}")


def _display_payload(payload: dict[str, Any], field_name: str, session_id: str | None = None) -> dict[str, Any]:
    display = _assert_is_dict(_nested_get(payload, field_name), field_name)
    _assert_equal(display.get("schema_version"), "rs_agent_display_v1", f"{field_name}.schema_version")
    if session_id is not None:
        _assert_equal(display.get("session_id"), session_id, f"{field_name}.session_id")
    return display


def _first_display_item_id(display: dict[str, Any]) -> str | None:
    items = display.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("item_id", "parent_asin", "asin", "id"):
            value = item.get(key)
            if value not in (None, ""):
                return str(value)
    return None


def _nested_get(payload: dict[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SmokeFailure(f"{field_name} must be a non-empty string")
    return value


def _assert_equal(actual: Any, expected: Any, field_name: str) -> None:
    if actual != expected:
        raise SmokeFailure(f"{field_name} expected {expected!r}, got {actual!r}")


def _assert_in(actual: Any, expected_values: set[Any], field_name: str) -> None:
    if actual not in expected_values:
        raise SmokeFailure(f"{field_name} expected one of {sorted(expected_values)!r}, got {actual!r}")


def _assert_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int):
        raise SmokeFailure(f"{field_name} must be int, got {type(value).__name__}")
    return value


def _assert_min_int(value: Any, minimum: int, field_name: str) -> None:
    actual = _assert_int(value, field_name)
    if actual < minimum:
        raise SmokeFailure(f"{field_name} expected >= {minimum}, got {actual}")


def _assert_is_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SmokeFailure(f"{field_name} must be object, got {type(value).__name__}")
    return value


def _assert_is_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SmokeFailure(f"{field_name} must be list, got {type(value).__name__}")
    return value


def _assert_min_len(value: Any, minimum: int, field_name: str) -> None:
    items = _assert_is_list(value, field_name)
    if len(items) < minimum:
        raise SmokeFailure(f"{field_name} expected length >= {minimum}, got {len(items)}")


if __name__ == "__main__":
    raise SystemExit(main())
