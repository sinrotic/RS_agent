from __future__ import annotations

from rs_core.serving.governance import manifest_gate as _manifest_gate

__all__ = _manifest_gate.__all__

for _name in __all__:
    globals()[_name] = getattr(_manifest_gate, _name)

del _name
