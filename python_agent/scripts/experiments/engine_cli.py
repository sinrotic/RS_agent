from __future__ import annotations

import argparse
import json

from rs_core.offline.runtime.worker import main as offline_main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RS Agent experiment entrypoint router")
    parser.add_argument("--route", choices=["offline", "agent"], default="offline")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.route == "agent":
        print(json.dumps({"status": "ok", "route": "agent", "engine": "AgentOrchestrationEngine"}))
        return 0
    return offline_main(args.args or ["health"])


if __name__ == "__main__":
    raise SystemExit(main())
