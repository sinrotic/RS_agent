from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SNAPSHOTS = {
    "online": "dic/architecture/RS_AGENT_ONLINE_SERVICE_OPENAPI_SNAPSHOT.json",
    "agent": "dic/architecture/RS_AGENT_AGENT_SERVICE_OPENAPI_SNAPSHOT.json",
}


def online_openapi() -> dict[str, Any]:
    from rs_core.serving.api.online_app import create_app

    return create_app().openapi()


def agent_openapi() -> dict[str, Any]:
    from rs_core.serving.api.agent_app import create_app

    return create_app().openapi()


def normalized_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate or check service OpenAPI snapshots for migration hardening.")
    parser.add_argument("--check", action="store_true", help="Fail if generated snapshots differ from checked-in files.")
    return parser


def snapshot_payloads() -> dict[str, str]:
    return {
        "online": normalized_json(online_openapi()),
        "agent": normalized_json(agent_openapi()),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payloads = snapshot_payloads()
    changed: list[str] = []

    for name, relative_path in SNAPSHOTS.items():
        path = PROJECT_ROOT / relative_path
        content = payloads[name]
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                changed.append(relative_path)
            continue
        path.write_text(content, encoding="utf-8")
        print(f"generated {relative_path}")

    if changed:
        print("OpenAPI snapshots are out of date:", file=sys.stderr)
        for relative_path in changed:
            print(f"- {relative_path}", file=sys.stderr)
        return 1
    if args.check:
        print("OpenAPI snapshots are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
