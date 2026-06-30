from __future__ import annotations

from functools import lru_cache

from rs_core.data.engine import DataAssetEngine


@lru_cache(maxsize=1)
def _cached_engine() -> DataAssetEngine:
    return DataAssetEngine()


def get_data_engine() -> DataAssetEngine:
    return _cached_engine()


def clear_data_engine_cache() -> None:
    _cached_engine.cache_clear()


get_data_engine.cache_clear = clear_data_engine_cache  # type: ignore[attr-defined]

__all__ = ["clear_data_engine_cache", "get_data_engine"]
