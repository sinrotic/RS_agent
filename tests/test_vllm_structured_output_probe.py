import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "java_agent/deploy/remote/model/vllm_structured_output_probe.py"
spec = importlib.util.spec_from_file_location("structured_probe", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def answer():
    return {"blocks": [{"type": "text", "content": "测试通过", "card_set_id": None, "item_ids": None, "layout": None}]}


def sse(event):
    return ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()


def stream(finish="tool_calls"):
    arguments = json.dumps(answer(), ensure_ascii=False)
    return [
        b": heartbeat\n",
        sse({"choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "id": "call_1", "function": {"name": "emit_final_answer", "arguments": arguments[:15]}
        }]}, "finish_reason": None}]}),
        sse({"choices": [{"index": 0, "delta": {"tool_calls": [{
            "index": 0, "function": {"arguments": arguments[15:]}
        }]}, "finish_reason": None}]}),
        sse({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}),
        sse({"choices": [], "usage": {"completion_tokens": 50}}),
        b"data: [DONE]\n",
    ]


def test_reconstructs_chinese_argument_fragments_and_ignores_usage():
    name, arguments = probe.collect_tool_stream(stream())
    assert name == "emit_final_answer"
    assert probe.validate_final_answer(json.loads(arguments)) == answer()


@pytest.mark.parametrize("finish", ["length", "content_filter", "error"])
def test_rejects_truncated_or_filtered_generation_even_if_json_is_valid(finish):
    with pytest.raises(ValueError):
        probe.collect_tool_stream(stream(finish))


def test_eof_without_terminal_marker_is_not_success():
    with pytest.raises(ValueError):
        probe.collect_tool_stream(stream()[:-1])


def test_done_without_successful_finish_reason_is_not_success():
    with pytest.raises(ValueError):
        probe.collect_tool_stream(stream()[:3] + [b"data: [DONE]\n"])


def test_rejects_parallel_tool_calls():
    lines = stream()
    lines.insert(2, sse({"choices": [{"delta": {"tool_calls": [{
        "index": 1, "id": "call_2", "function": {"name": "emit_final_answer", "arguments": "{}"}
    }]}}]}))
    with pytest.raises(ValueError, match="parallel"):
        probe.collect_tool_stream(lines)


@pytest.mark.parametrize("finish", ["length", "content_filter", None])
def test_nonstream_finish_reason_is_required(finish):
    with pytest.raises(ValueError):
        probe.first_message({"choices": [{"message": {"content": "{}"}, "finish_reason": finish}]})


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(extra=True),
    lambda p: p["blocks"][0].update(type="internal_debug"),
    lambda p: p["blocks"][0].update(item_ids=[3]),
    lambda p: p["blocks"][0].update(content="x" * 4001),
])
def test_rejects_schema_violations(mutation):
    payload = answer()
    mutation(payload)
    with pytest.raises(ValueError):
        probe.validate_final_answer(payload)


def test_probe_checks_all_tool_modes_and_publishes_report_only_after_success(monkeypatch, tmp_path):
    calls = []

    def post(url, payload, **kwargs):
        calls.append(payload)
        message = {"content": json.dumps(answer())}
        finish = "stop"
        if "tools" in payload:
            message = {"tool_calls": [{"id": "call_1", "function": {
                "name": "emit_final_answer", "arguments": json.dumps(answer())
            }}]}
            finish = "tool_calls"
        return {"choices": [{"message": message, "finish_reason": finish}]}

    stream_choices = []

    def post_stream(url, payload, **kwargs):
        stream_choices.append(payload["tool_choice"])
        return probe.collect_tool_stream(stream())

    monkeypatch.setattr(probe, "post_json", post)
    monkeypatch.setattr(probe, "post_sse_tool_arguments", post_stream)
    report_path = tmp_path / "report.json"
    args = SimpleNamespace(base_url="http://localhost:18082/v1", model="qwen35-4b",
                           api_key=None, timeout=5, skip_stream=False, report_file=str(report_path))
    report = probe.run_probe(args)
    assert report["cases"] == ["json_schema", "named_tool", "named_stream", "required_tool",
                               "required_stream", "auto_tool", "auto_stream"]
    assert len(stream_choices) == 3
    for payload in calls[1:]:
        assert payload["tools"][0]["function"]["strict"] is True
        assert "strict" not in payload["tools"][0]["function"]["parameters"]
        assert payload["parallel_tool_calls"] is False
        assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert json.loads(report_path.read_text())["status"] == "PASS"

    report_path.unlink()
    monkeypatch.setattr(probe, "post_json", lambda *a, **kw: {
        "choices": [{"message": {"content": json.dumps(answer())}, "finish_reason": "length"}]
    })
    with pytest.raises(ValueError):
        probe.run_probe(args)
    assert not report_path.exists()


@pytest.mark.parametrize("bad_parallel_response", [False, True])
def test_concurrent_warmup_validates_every_result_before_readiness(monkeypatch, tmp_path, bad_parallel_response):
    def post(url, payload, **kwargs):
        if "tools" not in payload:
            return {"choices": [{"message": {"content": json.dumps(answer())}, "finish_reason": "stop"}]}
        import threading
        invalid = bad_parallel_response and threading.current_thread() is not threading.main_thread()
        return {"choices": [{"message": {"tool_calls": [] if invalid else [{"function": {
            "name": "emit_final_answer", "arguments": json.dumps(answer())}}]}, "finish_reason": "tool_calls"}]}
    monkeypatch.setattr(probe, "post_json", post)
    report_path = tmp_path / "report.json"
    args = SimpleNamespace(base_url="http://localhost/v1", model="qwen35-4b", api_key=None,
                           timeout=5, skip_stream=True, report_file=str(report_path), warmup_concurrency=4)
    if bad_parallel_response:
        with pytest.raises(ValueError):
            probe.run_probe(args)
        assert not report_path.exists()
    else:
        report = probe.run_probe(args)
        assert report["cases"][-1] == "named_tool_concurrency_4"
        assert report_path.exists()

