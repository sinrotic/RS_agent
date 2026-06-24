from __future__ import annotations

import argparse

import pytest

from scripts.serving import run_service

pytestmark = [pytest.mark.serving, pytest.mark.smoke]


def test_run_service_uses_canonical_fastapi_app_target(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_uvicorn_run(target: str, **kwargs: object) -> None:
        captured["target"] = target
        captured["kwargs"] = kwargs

    monkeypatch.setattr(
        run_service,
        "parse_args",
        lambda: argparse.Namespace(host="127.0.0.1", port=8765, reload=False, config=None),
    )
    monkeypatch.setattr(run_service.uvicorn, "run", fake_uvicorn_run)

    run_service.main()

    assert captured == {
        "target": "rs_core.serving.api.app:app",
        "kwargs": {"host": "127.0.0.1", "port": 8765, "reload": False},
    }


def test_loopback_bind_allows_local_dev_without_strict_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_SERVING_STRICT_AUTH", raising=False)

    run_service._validate_serving_bind_security("127.0.0.1")
    run_service._validate_serving_bind_security("localhost")


def test_non_loopback_bind_requires_strict_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_SERVING_STRICT_AUTH", raising=False)

    with pytest.raises(SystemExit, match="RS_SERVING_STRICT_AUTH=1"):
        run_service._validate_serving_bind_security("0.0.0.0")


def test_non_loopback_bind_requires_trial_and_debug_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.delenv("RS_TRIAL_TOKEN", raising=False)
    monkeypatch.delenv("RS_DEBUG_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="RS_TRIAL_TOKEN, RS_DEBUG_TOKEN"):
        run_service._validate_serving_bind_security("0.0.0.0")


def test_non_loopback_bind_requires_simulation_token_when_simulation_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setenv("RS_DEBUG_TOKEN", "debug-secret")
    monkeypatch.setenv("RS_ENABLE_SIMULATION_ENDPOINTS", "1")
    monkeypatch.delenv("RS_SIMULATION_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="RS_SIMULATION_TOKEN"):
        run_service._validate_serving_bind_security("0.0.0.0")


def test_non_loopback_bind_requires_simulation_token_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setenv("RS_DEBUG_TOKEN", "debug-secret")
    monkeypatch.delenv("RS_ENABLE_SIMULATION_ENDPOINTS", raising=False)
    monkeypatch.delenv("RS_SIMULATION_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="RS_SIMULATION_TOKEN"):
        run_service._validate_serving_bind_security("0.0.0.0")


def test_non_loopback_bind_allows_strict_auth_with_required_tokens_and_simulation_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setenv("RS_DEBUG_TOKEN", "debug-secret")
    monkeypatch.setenv("RS_ENABLE_SIMULATION_ENDPOINTS", "0")
    monkeypatch.delenv("RS_SIMULATION_TOKEN", raising=False)

    run_service._validate_serving_bind_security("0.0.0.0")


def test_non_loopback_bind_allows_strict_auth_with_all_required_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_SERVING_STRICT_AUTH", "1")
    monkeypatch.setenv("RS_TRIAL_TOKEN", "trial-secret")
    monkeypatch.setenv("RS_DEBUG_TOKEN", "debug-secret")
    monkeypatch.delenv("RS_ENABLE_SIMULATION_ENDPOINTS", raising=False)
    monkeypatch.setenv("RS_SIMULATION_TOKEN", "simulation-secret")

    run_service._validate_serving_bind_security("0.0.0.0")
