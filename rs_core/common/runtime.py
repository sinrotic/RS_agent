from __future__ import annotations

import sys
from pathlib import Path


def enforce_project_venv(root: Path) -> None:
    executable = Path(sys.executable).resolve()
    expected = (root / ".venv").resolve()
    try:
        executable.relative_to(expected)
    except ValueError as exc:
        raise RuntimeError(f"Project .venv Python is required, got {sys.executable}") from exc
