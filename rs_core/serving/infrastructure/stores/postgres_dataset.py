from __future__ import annotations

from typing import Any, Protocol


class PostgresDatasetStore(Protocol):
    def health(self) -> dict[str, Any]: ...

    def summary(self) -> dict[str, Any]: ...

    def get_product(self, parent_asin: str) -> dict[str, Any] | None: ...

    def get_user_sequence(self, user_id: str, window_name: str = "recent_2y") -> dict[str, Any] | None: ...

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]: ...


def build_postgres_dataset_store_from_env() -> PostgresDatasetStore:
    from rs_core.data import build_postgres_dataset_store_from_env as _build_postgres_dataset_store_from_env

    return _build_postgres_dataset_store_from_env()


def ensure_safe_postgres_dataset_store(store: PostgresDatasetStore) -> PostgresDatasetStore:
    from rs_core.data import ensure_safe_postgres_dataset_store as _ensure_safe_postgres_dataset_store

    return _ensure_safe_postgres_dataset_store(store)


__all__ = (
    "PostgresDatasetStore",
    "build_postgres_dataset_store_from_env",
    "ensure_safe_postgres_dataset_store",
)
