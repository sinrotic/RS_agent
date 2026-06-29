from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci.gateway_smoke import main as gateway_smoke_main


COMPOSE_PROFILES = ["frontend", "online", "agent", "gateway"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build, start, smoke, and stop the lightweight RS Agent gateway stack.")
    parser.add_argument("--compose-file", default="deploy/docker-compose.yml")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--log-dir", default="outputs/smoke/gateway")
    parser.add_argument("--skip-build", action="store_true", help="Start existing images without rebuilding them.")
    return parser


def compose_command(compose_file: str, *args: str) -> list[str]:
    command = ["docker", "compose", "-f", compose_file]
    for profile in COMPOSE_PROFILES:
        command.extend(["--profile", profile])
    command.extend(args)
    return command


def run(command: list[str], *, stdout_path: Path | None = None) -> None:
    if stdout_path is None:
        subprocess.run(command, check=True)
        return
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as handle:
        subprocess.run(command, check=True, stdout=handle, stderr=subprocess.STDOUT)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log_dir = Path(args.log_dir)
    up_args = ["up", "-d"]
    if not args.skip_build:
        up_args.append("--build")

    try:
        run(compose_command(args.compose_file, *up_args), stdout_path=log_dir / "compose-up.log")
        smoke_status = gateway_smoke_main(["--base-url", args.base_url])
        if smoke_status != 0:
            run(compose_command(args.compose_file, "logs", "--no-color"), stdout_path=log_dir / "compose-logs.log")
        return smoke_status
    finally:
        try:
            run(compose_command(args.compose_file, "down"), stdout_path=log_dir / "compose-down.log")
        except subprocess.CalledProcessError as exc:
            print(f"failed to stop gateway smoke stack: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
