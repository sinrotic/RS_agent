import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "java_agent"
    / "deploy"
    / "remote"
    / "model"
    / "vllm_prefix_warmup.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("vllm_prefix_warmup", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_warmup_payloads_include_main_and_rag_agent_prefixes():
    warmup = load_module()

    payloads = warmup.build_warmup_payloads(
        model="qwen35-4b",
        system_prompt="stable system prompt",
        profiles=["rs_agent", "rag_agent"],
        max_tokens=1,
    )

    assert [payload["profile"] for payload in payloads] == ["rs_agent", "rag_agent"]
    rs_system = payloads[0]["payload"]["messages"][0]["content"]
    rag_system = payloads[1]["payload"]["messages"][0]["content"]
    assert "stable system prompt" in rs_system
    assert "agent_name" in rs_system
    assert "rs_agent" in rs_system
    assert "rag_agent" in rag_system
    assert payloads[0]["payload"]["max_tokens"] == 1
    assert payloads[0]["payload"]["temperature"] == 0


def test_run_warmup_once_posts_each_profile_and_waits_after_success():
    warmup = load_module()
    calls = []
    sleeps = []

    def post_json(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"ok": True}

    warmup.run_warmup_once(
        base_url="http://127.0.0.1:18082/v1",
        model="qwen35-4b",
        system_prompt="stable system prompt",
        profiles=["rs_agent", "rag_agent"],
        max_tokens=1,
        timeout=7,
        delay_after_warmup_sec=2,
        post_json=post_json,
        sleep=sleeps.append,
    )

    assert len(calls) == 2
    assert all(call[0] == "http://127.0.0.1:18082/v1/chat/completions" for call in calls)
    assert [call[1]["messages"][0]["content"].find(profile) >= 0 for call, profile in zip(calls, ["rs_agent", "rag_agent"])] == [True, True]
    assert sleeps == [2]


def test_exact_payload_preserves_template_inputs_and_does_not_mutate_source(tmp_path):
    warmup = load_module()
    original = {"profile": "shopping", "payload": {
        "model": "old", "max_tokens": 500, "stream": True,
        "max_completion_tokens": 1000, "min_tokens": 100, "n": 4,
        "stream_options": {"include_usage": True},
        "messages": [{"role": "system", "content": "真实固定前缀"}, {"role": "user", "content": "脱敏示例"}],
        "tools": [{"type": "function", "function": {"name": "lookup", "strict": True, "parameters": {"type": "object"}}}],
        "tool_choice": "required", "chat_template_kwargs": {"enable_thinking": False},
    }}
    path = tmp_path / "payloads.json"
    path.write_text(json.dumps([original]), encoding="utf-8")
    payload = warmup.read_warmup_payloads(str(path), "qwen35-4b", 1)[0]["payload"]
    for key in ("messages", "tools", "tool_choice", "chat_template_kwargs"):
        assert payload[key] == original["payload"][key]
    assert payload["model"] == "qwen35-4b"
    assert payload["max_tokens"] == 1
    assert payload["stream"] is False
    assert "stream_options" not in payload
    assert "max_completion_tokens" not in payload
    assert "min_tokens" not in payload
    assert payload["n"] == 1
    assert original["payload"]["stream"] is True
    assert "warmup" not in payload["messages"][0]["content"]


@pytest.mark.parametrize("records", [[], {}, [{"profile": "shopping", "payload": {"messages": []}}]])
def test_explicit_invalid_payload_file_fails_without_fallback(tmp_path, records):
    warmup = load_module()
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    with pytest.raises(ValueError):
        warmup.read_warmup_payloads(str(path), "qwen35-4b", 1)


@pytest.mark.parametrize("running,waiting,idle", [(0, 0, True), (1, 0, False), (0, 2, False)])
def test_idle_check_includes_waiting_requests(monkeypatch, running, waiting, idle):
    warmup = load_module()
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return (f'vllm:num_requests_running{{engine="0"}} {running}\n'
                    f'vllm:num_requests_waiting{{engine="0"}} {waiting}\n').encode()
    monkeypatch.setattr(warmup.urllib.request, "urlopen", lambda request, timeout: Response())
    assert warmup.server_is_idle("http://127.0.0.1:18082/v1", 1) is idle


def test_keepalive_skips_generation_when_busy(monkeypatch):
    warmup = load_module()
    args = warmup.parse_args(["--only-when-idle"])
    monkeypatch.setattr(warmup, "server_is_idle", lambda *args: False)
    monkeypatch.setattr(warmup, "run_warmup_once", lambda **kwargs: pytest.fail("有业务请求时不应预热"))
    monkeypatch.setattr(warmup.time, "sleep", lambda seconds: (_ for _ in ()).throw(InterruptedError()))
    with pytest.raises(InterruptedError):
        warmup.run_keepalive(args, "stable prompt")


def test_keepalive_entrypoint_checks_busy_before_first_generation(monkeypatch):
    warmup = load_module()
    monkeypatch.setattr(warmup, "read_system_prompt", lambda *args: "stable prompt")
    monkeypatch.setattr(warmup, "server_is_idle", lambda *args: False)
    monkeypatch.setattr(warmup, "run_warmup_once", lambda **kwargs: pytest.fail("保温入口也必须先检查负载"))
    monkeypatch.setattr(warmup.time, "sleep", lambda seconds: (_ for _ in ()).throw(InterruptedError()))
    with pytest.raises(InterruptedError):
        warmup.main(["--keepalive", "--skip-ready-wait", "--only-when-idle"])


def test_keepalive_stops_remaining_prefixes_when_business_arrives(monkeypatch):
    warmup = load_module()
    args = warmup.parse_args(["--only-when-idle", "--recheck-idle-per-prefix"])
    checks = iter([True, True, False])  # 本轮入口、第一条前缀、第二条前缀。
    monkeypatch.setattr(warmup, "server_is_idle", lambda *args: next(checks))
    calls = []
    post = lambda *args: calls.append(args) or {}
    original_run = warmup.run_warmup_once
    monkeypatch.setattr(warmup, "run_warmup_once", lambda **kwargs: original_run(**kwargs, post_json=post))
    monkeypatch.setattr(warmup.time, "sleep", lambda seconds: (_ for _ in ()).throw(InterruptedError()))
    with pytest.raises(InterruptedError):
        warmup.run_keepalive(args, "stable prompt")
    assert len(calls) == 1
    assert "rs_agent" in calls[0][1]["messages"][0]["content"]


def test_per_prefix_recheck_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("VLLM_RECHECK_IDLE_PER_PREFIX", raising=False)
    warmup = load_module()
    assert warmup.parse_args([]).recheck_idle_per_prefix is False


def test_default_keepalive_preserves_original_whole_cycle_check(monkeypatch):
    warmup = load_module()
    args = warmup.parse_args(["--only-when-idle", "--no-recheck-idle-per-prefix"])
    checks, calls = [], []
    monkeypatch.setattr(warmup, "server_is_idle", lambda *args: checks.append(args) or True)
    monkeypatch.setattr(warmup, "run_warmup_once", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(warmup.time, "sleep", lambda seconds: (_ for _ in ()).throw(InterruptedError()))
    with pytest.raises(InterruptedError):
        warmup.run_keepalive(args, "stable prompt")
    assert len(checks) == len(calls) == 1
    assert calls[0]["idle_check"] is None


def test_kernel_warmup_covers_partial_prefix_alignment_and_real_decode():
    warmup = load_module()
    batches = warmup.build_kernel_warmup_batches("qwen35-4b", [1, 4, 8, 16])
    full = batches[0]["payload"]["prompt"]
    partials = [item["payload"]["prompt"] for item in batches if item["phase"] == "partial-prefix"]
    assert len(full) == 6608
    assert [len(prompt) % 16 for prompt in partials] == [0, 1, 2, 4, 8]
    assert all(prompt[:5000] == full[:5000] and prompt[5000:] != full[5000:] for prompt in partials)
    decode = [item for item in batches if item["phase"] == "batch-decode"]
    assert [len(item["payload"]["prompt"]) for item in decode] == [1, 4, 8, 16]
    assert all(item["payload"]["max_tokens"] == 2 and item["payload"]["ignore_eos"] for item in decode)
    assert all("messages" not in item["payload"] and "tools" not in item["payload"] for item in batches)


def test_kernel_warmup_stops_when_business_arrives_without_dispatching_next_batch():
    warmup = load_module()
    calls = []
    idle = iter([True, False])
    with pytest.raises(RuntimeError, match="业务请求"):
        warmup.run_kernel_warmup("http://localhost:18082/v1", "qwen35-4b", [1, 4], 10,
            post_json=lambda *args: calls.append(args) or {"choices": [{}], "usage": {"completion_tokens": 1}},
            idle_check=lambda: next(idle))
    assert len(calls) == 1


@pytest.mark.parametrize("sizes", [[], [0], [17], [4, 4]])
def test_kernel_warmup_rejects_invalid_batch_budgets(sizes):
    warmup = load_module()
    with pytest.raises(ValueError):
        warmup.build_kernel_warmup_batches("qwen35-4b", sizes)


def test_one_shot_refills_real_prefixes_after_kernel_warmup(monkeypatch):
    warmup = load_module()
    calls = []
    monkeypatch.setattr(warmup, "read_system_prompt", lambda *args: "stable")
    monkeypatch.setattr(warmup, "server_is_idle", lambda *args: True)
    monkeypatch.setattr(warmup, "run_kernel_warmup", lambda *args, **kwargs: calls.append("kernel"))
    monkeypatch.setattr(warmup, "run_warmup_once", lambda **kwargs: calls.append("prefix"))
    assert warmup.main(["--skip-ready-wait", "--kernel-warmup"]) == 0
    assert calls == ["kernel", "prefix"]


def test_keepalive_does_not_repeat_expensive_kernel_warmup(monkeypatch):
    warmup = load_module()
    monkeypatch.setattr(warmup, "read_system_prompt", lambda *args: "stable")
    monkeypatch.setattr(warmup, "run_kernel_warmup", lambda *args, **kwargs: pytest.fail("定时保温不应做内核批次预热"))
    monkeypatch.setattr(warmup, "run_keepalive", lambda *args: None)
    assert warmup.main(["--skip-ready-wait", "--keepalive", "--kernel-warmup"]) == 0


def test_kernel_warmup_rejects_incomplete_model_generation():
    warmup = load_module()
    with pytest.raises(ValueError, match="预热输出"):
        warmup.run_kernel_warmup("http://localhost:18082/v1", "qwen35-4b", [1], 10,
            post_json=lambda *args: {"choices": [{}], "usage": {"completion_tokens": 0}})
