from __future__ import annotations

from typing import Any

from rs_core.online.runtime.pool500 import OnlinePool500Recommender, OnlineRecommendationResult


def build_online_pool500_recommender(env: Any) -> OnlinePool500Recommender:
    """Build the legacy pool500 runtime host through the online runtime boundary."""

    return OnlinePool500Recommender.from_environment(env)


__all__ = ["OnlinePool500Recommender", "OnlineRecommendationResult", "build_online_pool500_recommender"]
