from __future__ import annotations

from typing import Any

from rs_core.common.milvus_config import (
    merge_milvus_config as merge_milvus_config,
    milvus_config_from_args as milvus_config_from_args,
    milvus_config_from_env as milvus_config_from_env,
)
from rs_core.recsys.vectorstores.milvus_client import MilvusVectorStore
from rs_core.recsys.vectorstores.milvus_contracts import DEFAULT_MILVUS_METRIC_TYPE, normalize_milvus_metric_type
from rs_core.recsys.vectorstores.build_utils import batched, created_at_utc, infer_vector_size, write_manifest_if_requested


def add_milvus_connection_args(parser: Any) -> None:
    parser.add_argument("--milvus-uri", default=None, help="Milvus URI, e.g. http://localhost:19530 or local .db path")
    parser.add_argument("--milvus-token", default=None, help="Milvus auth token")
    parser.add_argument("--milvus-db-name", default=None, help="Milvus database name")
    parser.add_argument("--milvus-timeout", type=int, default=None, help="Milvus client timeout in seconds")


def build_store(milvus_config: dict[str, Any] | None) -> MilvusVectorStore:
    require_explicit_milvus_target(milvus_config)
    return MilvusVectorStore.from_config(milvus_config or {})


def require_explicit_milvus_target(milvus_config: dict[str, Any] | None) -> None:
    config = milvus_config or {}
    if config.get("uri") not in (None, ""):
        return
    raise ValueError("live Milvus build requires an explicit target; pass --milvus-uri for local smoke or server builds")


def is_ephemeral_milvus_target(milvus_config: dict[str, Any] | None) -> bool:
    uri = str((milvus_config or {}).get("uri") or "")
    return uri.endswith(".db") or uri.startswith("./") or uri.startswith("outputs/")


def validate_milvus_build_controls(
    *,
    batch_size: int,
    limit_items: int | None,
    dry_run: bool,
    milvus_config: dict[str, Any] | None,
) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if limit_items is not None and limit_items < 0:
        raise ValueError("limit_items must be non-negative")
    if not dry_run and limit_items is not None and not is_ephemeral_milvus_target(milvus_config):
        raise ValueError("non-dry-run --limit-items is only allowed with local Milvus smoke builds")


def milvus_collection_manifest_base(
    *,
    schema_version: str,
    collection_name: str,
    collection_schema_version: str,
    vector_size: int | None,
    metric_type: str = DEFAULT_MILVUS_METRIC_TYPE,
    index_type: str = "AUTOINDEX",
    dry_run: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "created_at": created_at_utc(),
        "backend": "milvus",
        "collection_name": str(collection_name),
        "milvus_collection_schema_version": collection_schema_version,
        "vector_size": int(vector_size) if vector_size is not None else None,
        "metric_type": normalize_milvus_metric_type(metric_type),
        "index_type": str(index_type),
        "dry_run": bool(dry_run),
    }


__all__ = [
    "add_milvus_connection_args",
    "batched",
    "build_store",
    "infer_vector_size",
    "merge_milvus_config",
    "milvus_collection_manifest_base",
    "milvus_config_from_args",
    "milvus_config_from_env",
    "require_explicit_milvus_target",
    "validate_milvus_build_controls",
    "write_manifest_if_requested",
]
