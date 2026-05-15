from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.engineering_contracts import select_test_paths_by_markers


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Select test files by file-level pytest markers without importing test modules.")
    parser.add_argument("--root", default=str(ROOT), help="Project root path.")
    parser.add_argument(
        "--marker",
        action="append",
        dest="markers",
        required=True,
        help="Marker to include. Can be passed more than once.",
    )
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    args = parse_args()
    root = Path(args.root).resolve()
    test_paths = [path.relative_to(root).as_posix() for path in sorted((root / "tests").glob("test_*.py"))]
    selected = select_test_paths_by_markers(root, test_paths, set(args.markers))
    if not selected:
        raise SystemExit("no tests selected")
    print("\n".join(selected))


if __name__ == "__main__":
    main()
