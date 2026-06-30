from __future__ import annotations

import argparse
import json
from typing import Any

from rs_core.offline.runtime.composition import get_offline_engine


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RS Agent offline model worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check OfflineModelEngine health")

    training = subparsers.add_parser("start-training-job", help="Create a dry-run training job contract")
    training.add_argument("job_id")
    training.add_argument("--config-path", default="")
    training.add_argument("--model-family", default="")
    training.add_argument("--execution-mode", default="dry_run")
    training.add_argument("--estimated-memory-gb", type=float, default=1.0)

    model_artifact = subparsers.add_parser("register-model-artifact", help="Build a model artifact contract")
    model_artifact.add_argument("artifact_id")
    model_artifact.add_argument("uri")
    model_artifact.add_argument("--model-family", default="")
    model_artifact.add_argument("--metrics-ref", default="")

    evaluation = subparsers.add_parser("run-evaluation-smoke", help="Run a lightweight evaluation smoke")
    evaluation.add_argument("--eval-id", default="offline-smoke")
    evaluation.add_argument("--dataset-ref", default="")
    evaluation.add_argument("--model-artifact-id", default="")

    resource = subparsers.add_parser("resource-estimate", help="Create a lightweight resource estimate")
    resource.add_argument("job_type")
    resource.add_argument("--estimated-memory-gb", type=float, default=1.0)
    resource.add_argument("--heavy-job", action="store_true")

    experiment = subparsers.add_parser("run-experiment-smoke", help="Create an experiment smoke contract")
    experiment.add_argument("--experiment-id", default="offline-experiment-smoke")
    experiment.add_argument("--route", default="offline")

    simulation = subparsers.add_parser("run-simulation-smoke", help="Create an offline simulation smoke contract")
    simulation.add_argument("--simulation-id", default="offline-simulation-smoke")
    simulation.add_argument("--sample-count", type=int, default=0)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = get_offline_engine()

    if args.command == "health":
        _print_json(engine.health())
    elif args.command == "start-training-job":
        _print_json(
            engine.start_training_job(
                args.job_id,
                config_path=args.config_path,
                model_family=args.model_family,
                execution_mode=args.execution_mode,
                estimated_memory_gb=args.estimated_memory_gb,
            )
        )
    elif args.command == "register-model-artifact":
        _print_json(
            engine.register_model_artifact(
                args.artifact_id,
                args.uri,
                model_family=args.model_family,
                metrics_ref=args.metrics_ref,
            )
        )
    elif args.command == "run-evaluation-smoke":
        _print_json(
            engine.run_evaluation_smoke(
                eval_id=args.eval_id,
                dataset_ref=args.dataset_ref,
                model_artifact_id=args.model_artifact_id,
            )
        )
    elif args.command == "resource-estimate":
        _print_json(
            engine.resource_estimate(
                args.job_type,
                estimated_memory_gb=args.estimated_memory_gb,
                heavy_job=args.heavy_job,
            )
        )
    elif args.command == "run-experiment-smoke":
        _print_json(engine.experiment_smoke(args.experiment_id, route=args.route))
    elif args.command == "run-simulation-smoke":
        _print_json(engine.simulation_smoke(args.simulation_id, sample_count=args.sample_count))
    else:  # pragma: no cover - argparse enforces choices
        raise ValueError(f"Unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
