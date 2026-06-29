from __future__ import annotations

from functools import lru_cache

from rs_core.offline.engine import OfflineModelEngine


@lru_cache(maxsize=1)
def _cached_engine() -> OfflineModelEngine:
    return OfflineModelEngine()


def get_offline_engine() -> OfflineModelEngine:
    return _cached_engine()


def clear_offline_engine_cache() -> None:
    _cached_engine.cache_clear()


get_offline_engine.cache_clear = clear_offline_engine_cache  # type: ignore[attr-defined]

__all__ = ["clear_offline_engine_cache", "get_offline_engine"]
