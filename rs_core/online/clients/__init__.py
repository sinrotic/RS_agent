from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rs_core.online.engine import OnlineRecommendationEngine


@dataclass
class OnlineRecommendationClient:
    engine: OnlineRecommendationEngine = field(default_factory=OnlineRecommendationEngine)

    def recommend(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.engine.recommend(payload)

    def recall(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.engine.recall(payload)

    def rank(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.engine.rank(payload)


__all__ = ["OnlineRecommendationClient"]
