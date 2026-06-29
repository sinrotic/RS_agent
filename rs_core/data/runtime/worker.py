from __future__ import annotations

import argparse
import json
from typing import Any

from rs_core.data.runtime.composition import get_data_engine


def _print_json(payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _with_dry_run(payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        payload.setdefault("metadata", {})["dry_run"] = True
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RS Agent data asset worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check DataAssetEngine health")
    subparsers.add_parser("readiness", help="Check DataAssetEngine adapter readiness")

    dataset = subparsers.add_parser("import-dataset", help="Build a dataset import contract")
    dataset.add_argument("name")
    dataset.add_argument("path")
    dataset.add_argument("--split", default="train")
    dataset.add_argument("--dry-run", action="store_true", help="Emit the contract without importing data")

    window = subparsers.add_parser("build-window-dataset", help="Build a windowed dataset contract")
    window.add_argument("name")
    window.add_argument("path")
    window.add_argument("--window", required=True)
    window.add_argument("--dry-run", action="store_true", help="Emit the contract without materializing data")

    artifact = subparsers.add_parser("register-artifact", help="Build an artifact contract")
    artifact.add_argument("artifact_id")
    artifact.add_argument("uri")
    artifact.add_argument("--kind", default="generic")

    pool = subparsers.add_parser("build-candidate-pool", help="Build a candidate pool contract")
    pool.add_argument("pool_id")
    pool.add_argument("item_ids", nargs="*")
    pool.add_argument("--source", default="manual")

    chunks = subparsers.add_parser("build-knowledge-chunks", help="Load knowledge chunk contracts from JSONL")
    chunks.add_argument("path")
    chunks.add_argument("--limit", type=int, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    engine = get_data_engine()

    if args.command == "health":
        _print_json(engine.health())
    elif args.command == "readiness":
        _print_json(engine.readiness())
    elif args.command == "import-dataset":
        _print_json(_with_dry_run(engine.import_dataset(args.name, args.path, split=args.split), args.dry_run))
    elif args.command == "build-window-dataset":
        _print_json(_with_dry_run(engine.build_window_dataset(args.name, args.path, window=args.window), args.dry_run))
    elif args.command == "register-artifact":
        _print_json(engine.register_artifact(args.artifact_id, args.uri, kind=args.kind))
    elif args.command == "build-candidate-pool":
        _print_json(engine.build_candidate_pool(args.pool_id, args.item_ids, source=args.source))
    elif args.command == "build-knowledge-chunks":
        _print_json(engine.build_knowledge_chunks(args.path, limit=args.limit))
    else:  # pragma: no cover - argparse enforces choices
        raise ValueError(f"Unsupported command: {args.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
