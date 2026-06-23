from __future__ import annotations

from rs_core.serving.domain import serving_fact as _serving_fact

__all__ = _serving_fact.__all__

for _name in __all__:
    globals()[_name] = getattr(_serving_fact, _name)

del _name
