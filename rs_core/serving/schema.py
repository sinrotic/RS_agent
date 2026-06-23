"""Legacy serving schema import shim.

Canonical DTO definitions live in :mod:`rs_core.serving.schemas`.
This module remains for backwards-compatible imports.
"""

from __future__ import annotations

from rs_core.serving import schemas as _schemas
from rs_core.serving.schemas.models import _oracle_fields_in as _oracle_fields_in

__all__ = _schemas.__all__

for _name in __all__:
    globals()[_name] = getattr(_schemas, _name)

del _name
