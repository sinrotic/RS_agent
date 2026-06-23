from __future__ import annotations

from rs_core.serving.domain import adapter_contracts as _adapter_contracts

__all__ = _adapter_contracts.__all__

for _name in __all__:
    globals()[_name] = getattr(_adapter_contracts, _name)

del _name
