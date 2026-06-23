from __future__ import annotations

from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROVIDER_ORDER = [
    "two_tower_qdrant",
    "candidate_store_itemcf_strong",
    "candidate_store_itemcf_weak",
    "candidate_store_co_visit_repair",
    "candidate_store_usercf",
    "candidate_store_category",
    "semantic_token",
    "candidate_store_popular",
    "semantic_vector",
    "pool500_fallback",
    # Legacy provider names kept for config compatibility. They now route through
    # the neutral CandidateStore factory and may use Cassandra/Scylla at runtime.
    "postgres_item_neighbors",
    "postgres_usercf",
    "postgres_category",
    "postgres_popular",
]


def online_retrieval_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("online_retrieval") if isinstance(config.get("online_retrieval"), dict) else {}
    if raw:
        return dict(raw)
    return {"enabled": False, "providers": {}}


def provider_configs(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    retrieval = online_retrieval_config(config)
    raw_providers = retrieval.get("providers") if isinstance(retrieval.get("providers"), dict) else {}
    providers: dict[str, dict[str, Any]] = {}
    for name in DEFAULT_PROVIDER_ORDER:
        value = raw_providers.get(name)
        if isinstance(value, dict):
            providers[name] = dict(value)
    for name, value in raw_providers.items():
        if name not in providers and isinstance(value, dict):
            providers[str(name)] = dict(value)
    return providers


def provider_enabled(provider_config: dict[str, Any]) -> bool:
    return bool(provider_config.get("enabled", True))


def resolve_project_path(value: Any, config_path: str | Path | None = None) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    project_path = PROJECT_ROOT / path
    if project_path.exists():
        return project_path
    if config_path:
        config_dir_path = Path(config_path).resolve().parent / path
        if config_dir_path.exists():
            return config_dir_path
    return project_path


def clamp_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 5000) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
