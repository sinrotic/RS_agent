from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

FOCUSED_TESTS = [
    "tests/contracts/test_architecture_migration_boundaries.py",
    "tests/data/test_data_adapter_readiness.py",
    "tests/data/test_data_clients.py",
    "tests/services/test_serving_reorg_compatibility.py",
    "tests/services/test_serving_run_service.py",
    "tests/services/test_serving_smoke.py",
    "tests/services/test_service_runtime_binding.py",
    "tests/agent/test_agent_dialogue.py",
    "tests/agent/test_agent_facade_parity.py",
    "tests/agent/test_agent_tools.py",
    "tests/agent/test_agent_runtime.py",
    "tests/agent/test_agent_runtime_contracts.py",
    "tests/agent/test_llm_dialogue_planner.py",
    "tests/agent/test_multi_turn_sft_generator.py",
    "tests/agent/test_rag_agent_adapter.py",
    "tests/agent/test_agent_simulation_contract.py",
    "tests/online/test_online_engine_contracts.py",
    "tests/online/test_online_retrieval_orchestrator.py",
    "tests/offline/test_offline_engine_contracts.py",
    "tests/test_rag_core.py",
    "tests/test_milvus_config_env.py",
]

RUFF_TARGETS = [
    "rs_core",
    "services",
    "scripts/data/engine_cli.py",
    "scripts/artifacts/engine_cli.py",
    "scripts/training/offline_engine_cli.py",
    "scripts/evaluation/offline_engine_cli.py",
    "scripts/experiments/engine_cli.py",
    "scripts/ci/generate_frontend_types.py",
    "scripts/ci/generate_service_openapi_snapshots.py",
    "scripts/ci/gateway_smoke.py",
    "scripts/ci/run_gateway_smoke.py",
    "scripts/ci/run_migration_hardening_checks.py",
    "scripts/recall/build_milvus_rag_index.py",
    "scripts/recall/build_rag_bm25_index.py",
    "scripts/serving/run_service.py",
    "tests/contracts/test_architecture_migration_boundaries.py",
    "tests/data/test_data_adapter_readiness.py",
    "tests/data/test_data_clients.py",
    "tests/services/test_serving_run_service.py",
    "tests/services/test_service_runtime_binding.py",
    "tests/agent/test_agent_facade_parity.py",
    "tests/agent/test_agent_runtime.py",
    "tests/agent/test_agent_simulation_contract.py",
    "tests/online/test_online_retrieval_orchestrator.py",
    "tests/offline/test_offline_engine_contracts.py",
    "tests/test_rag_core.py",
    "tests/test_milvus_config_env.py",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run lightweight migration-hardening checks without heavy infra or training jobs.")
    parser.add_argument("--python", default=str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"))
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-ruff", action="store_true")
    parser.add_argument("--skip-compose-config", action="store_true")
    parser.add_argument("--frontend-build", action="store_true", help="Also run npm --prefix frontend run build.")
    parser.add_argument("--gateway-smoke", action="store_true", help="Also build/start/smoke/down the lightweight gateway stack.")
    return parser


def run(command: list[str]) -> None:
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.skip_tests:
        run([args.python, "-m", "pytest", *FOCUSED_TESTS, "-q"])
    run([args.python, "scripts/ci/generate_service_openapi_snapshots.py", "--check"])
    run([args.python, "scripts/ci/generate_frontend_types.py"])
    if not args.skip_ruff:
        run([args.python, "-m", "ruff", "check", *RUFF_TARGETS])
    if not args.skip_compose_config:
        run(["docker", "compose", "-f", "deploy/docker-compose.yml", "config", "--profiles"])
    if args.frontend_build:
        run(["npm", "--prefix", "frontend", "run", "build"])
    if args.gateway_smoke:
        run([args.python, "scripts/ci/run_gateway_smoke.py"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
