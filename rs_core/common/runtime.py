from __future__ import annotations

import sys
from pathlib import Path


def enforce_project_venv(root: Path) -> None:
    executable = Path(sys.executable)
    expected = root / ".venv"
    for candidate, base in ((executable, expected), (executable.resolve(), expected.resolve())):
        try:
            candidate.relative_to(base)
            return
        except ValueError:
            continue
    raise RuntimeError(f"Project .venv Python is required, got {sys.executable}")
