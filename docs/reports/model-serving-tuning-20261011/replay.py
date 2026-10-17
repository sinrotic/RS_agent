"""在同机私有目录重放真实测试请求，只保存计时与参数摘要。"""
import hashlib
import json
from pathlib import Path
import time
import urllib.request

from jsonschema import Draft202012Validator


def replay(base_url: str, records: list[dict]) -> list[dict]:
    result = []
    for record in records:
        request_payload = dict(record["payload"])
        request_payload.update(stream=False, temperature=0)
        request_payload.pop("stream_options", None)
        name = request_payload["tool_choice"]["function"]["name"]
        schema = next(tool["function"]["parameters"] for tool in request_payload["tools"] if tool["function"]["name"] == name)
        validator = Draft202012Validator(schema)
        for repeat in range(3):
            started = time.perf_counter()
            request = urllib.request.Request(base_url + "/chat/completions", data=json.dumps(request_payload).encode(),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=90) as response:
                body = json.load(response)
            choice = body["choices"][0]
            if choice["finish_reason"] not in {"stop", "tool_calls"}:
                raise ValueError("真实最终回答被截断或失败")
            calls = choice["message"].get("tool_calls", [])
            if len(calls) != 1 or calls[0]["function"]["name"] != name:
                raise ValueError("最终回答未调用指定工具")
            arguments = json.loads(calls[0]["function"]["arguments"])
            validator.validate(arguments)
            if not arguments.get("blocks"):
                raise ValueError("最终回答没有公开块")
            for block in arguments["blocks"]:
                if block.get("type") in {"text", "followup_question"} and not (block.get("content") or "").strip():
                    raise ValueError("最终回答文字为空")
            result.append({"profile": record["profile"], "repeat": repeat,
                           "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                           "usage": body["usage"], "finish_reason": choice["finish_reason"],
                           "argument_sha256": hashlib.sha256(json.dumps(arguments, ensure_ascii=False, sort_keys=True).encode()).hexdigest()})
    return result


def append_replay(artifact: Path, base_url: str) -> None:
    private = Path(__file__).with_name("replay-payloads.private.json")
    records = json.loads(private.read_text())
    result = replay(base_url, records)
    data = json.loads(artifact.read_text())
    data["real_request_replay"] = result
    artifact.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n")
