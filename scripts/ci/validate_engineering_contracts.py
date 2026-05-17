from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.engineering_contracts import validate_engineering_contracts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate lightweight engineering contracts.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path.")
    parser.add_argument(
        "--config",
        action="append",
        dest="configs",
        help="Config path to validate. Defaults to current configs/**/*.yaml.",
    )
    parser.add_argument(
        "--script",
        action="append",
        dest="scripts",
        help="Script path to validate. Defaults to current scripts/**/*.py excluding scripts/archive/.",
    )
    parser.add_argument(
        "--test",
        action="append",
        dest="tests",
        help="Test path to validate. Defaults to current tests/test_*.py.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    root = Path(args.root).resolve()
    config_paths = args.configs or _workspace_paths(root, "configs/**/*.yaml")
    script_paths = args.scripts or _workspace_paths(root, "scripts/**/*.py", exclude_parts={"archive"})
    test_paths = args.tests or _workspace_paths(root, "tests/test_*.py")
    violations = validate_engineering_contracts(root, config_paths, script_paths, test_paths)
    if violations:
        for violation in violations:
            print(f"[{violation.check}] {violation.path}: {violation.message}")
        raise SystemExit(1)
    print(f"Engineering contracts passed: {len(config_paths)} configs, {len(script_paths)} scripts, {len(test_paths)} tests")


def _workspace_paths(root: Path, pattern: str, exclude_parts: set[str] | None = None) -> list[str]:
    excluded = exclude_parts or set()
    return [path.relative_to(root).as_posix() for path in sorted(root.glob(pattern)) if path.is_file() and not (set(path.relative_to(root).parts) & excluded)]


if __name__ == "__main__":
    main()
