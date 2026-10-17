import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "java_agent/deploy/remote/app/check_service_readiness.py"
spec = importlib.util.spec_from_file_location("service_readiness", SCRIPT)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_selected_model_context_is_checked_not_a_different_large_model(monkeypatch):
    monkeypatch.setattr(probe, "read_json", lambda _: {"data": [
        {"id": "large-other-model", "max_model_len": 32768},
        {"id": "qwen35-4b", "max_model_len": 4096},
    ]})
    assert not probe.check_model("http://test/v1", "qwen35-4b", 16384)["ready"]


def test_unknown_context_and_missing_model_cannot_pass(monkeypatch):
    monkeypatch.setattr(probe, "read_json", lambda _: {"data": [{"id": "qwen35-4b"}]})
    assert not probe.check_model("http://test/v1", "qwen35-4b", 16384)["ready"]
    assert not probe.check_model("http://test/v1", "missing", 16384)["ready"]


def test_compatible_model_and_actual_health_status(monkeypatch):
    monkeypatch.setattr(probe, "read_json", lambda _: {"data": [{"id": "qwen35-4b", "max_model_len": 16384}]})
    assert probe.check_model("http://test/v1", "qwen35-4b", 16384)["ready"]
    monkeypatch.setattr(probe, "read_json", lambda _: {"status": "DOWN"})
    assert not probe.check_service("agent", "http://test/health")["ready"]


def test_connection_error_report_does_not_echo_secret_url(monkeypatch):
    def fail(_):
        raise OSError("http://secret:test@host")
    monkeypatch.setattr(probe, "read_json", fail)
    assert probe.check_service("agent", "http://test/health") == {"name": "agent", "ready": False, "error": "OSError"}
