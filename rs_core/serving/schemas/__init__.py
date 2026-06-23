"""Canonical serving request and response schemas."""

from __future__ import annotations

from rs_core.serving.schemas import models as _models

__all__ = _models.__all__

for _name in __all__:
    globals()[_name] = getattr(_models, _name)

del _name
