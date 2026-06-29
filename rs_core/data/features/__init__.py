from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rs_core.data.contracts import FeatureSchemaContract


@dataclass(frozen=True)
class FeatureViewContract:
    name: str
    schema: FeatureSchemaContract
    source: str = "rs_core.data.features"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema": self.schema.to_dict(),
            "source": self.source,
            "metadata": dict(self.metadata),
        }


__all__ = ["FeatureViewContract"]
