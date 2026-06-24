from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STRICT_AUTH_ENV = "RS_SERVING_STRICT_AUTH"
TRIAL_TOKEN_ENV = "RS_TRIAL_TOKEN"
DEBUG_TOKEN_ENV = "RS_DEBUG_TOKEN"
SIMULATION_TOKEN_ENV = "RS_SIMULATION_TOKEN"
ENABLE_SIMULATION_ENV = "RS_ENABLE_SIMULATION_ENDPOINTS"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RS Agent single-process demo service.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn reload for local development.")
    parser.add_argument("--config", help="Serving config path. Also available via RS_SERVING_CONFIG.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.config:
        os.environ["RS_SERVING_CONFIG"] = args.config
    _validate_serving_bind_security(args.host)
    print("Starting RS Agent online service: FastAPI only; vLLM/Qwen external providers are not started by serving.")
    print("Runtime note: in-memory sessions, single process, restart loses state, not production concurrency-safe.")
    print(f"Agent inference provider status: {_agent_provider_status()}")
    uvicorn.run("rs_core.serving.api.app:app", host=args.host, port=args.port, reload=args.reload)


def _agent_provider_status() -> str:
    provider = os.environ.get("RS_AGENT_INFERENCE_POLICY", "disabled").strip().lower() or "disabled"
    if provider in _FALSE_VALUES:
        provider = "disabled"
    endpoint_configured = bool(os.environ.get("RS_AGENT_OPENAI_COMPATIBLE_BASE_URL", "").strip())
    model_configured = bool(os.environ.get("RS_AGENT_OPENAI_COMPATIBLE_MODEL", "").strip())
    if provider in {"openai_compatible", "openai", "vllm"}:
        return f"provider=openai_compatible endpoint_configured={endpoint_configured} model_configured={model_configured} probe=not_started"
    if provider in {"qwen", "qwen_local", "local_transformers", "on", "true", "1"}:
        return "provider=local_transformers lazy_load=true started_by_serving=false"
    return "provider=disabled started_by_serving=false"


def _validate_serving_bind_security(host: str) -> None:
    if _is_loopback_host(host):
        return
    if not _env_true(STRICT_AUTH_ENV):
        raise SystemExit(
            "Refusing to bind RS Agent serving to non-loopback host without RS_SERVING_STRICT_AUTH=1. "
            "Use 127.0.0.1 for local trials or configure strict auth tokens before exposing the service."
        )
    missing_tokens = [name for name in (TRIAL_TOKEN_ENV, DEBUG_TOKEN_ENV) if not os.environ.get(name, "").strip()]
    if _simulation_endpoints_enabled() and not os.environ.get(SIMULATION_TOKEN_ENV, "").strip():
        missing_tokens.append(SIMULATION_TOKEN_ENV)
    if missing_tokens:
        raise SystemExit(f"Refusing non-loopback serving bind with missing auth token env: {', '.join(missing_tokens)}")


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in _LOOPBACK_HOSTS


def _simulation_endpoints_enabled() -> bool:
    return os.environ.get(ENABLE_SIMULATION_ENV, "").strip().lower() not in _FALSE_VALUES


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


if __name__ == "__main__":
    main()
