from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class VectorSearchHit:
    item_id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    point_id: str | int | None = None
