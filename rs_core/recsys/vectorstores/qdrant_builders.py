from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from rs_core.common.io import write_json
from rs_core.recsys.vectorstores.qdrant_client import QdrantVectorStore
from rs_core.recsys.vectorstores.qdrant_contracts import DEFAULT_QDRANT_DISTANCE, normalize_qdrant_distance

T = TypeVar("T")


def created_at_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def batched(values: Iterable[T], batch_size: int) -> Iterator[list[T]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def infer_vector_size(vectors: Iterable[list[float]]) -> int:
    for vector in vectors:
        if vector:
            return len(vector)
    raise ValueError("cannot infer vector size from empty vectors")


def qdrant_config_from_args(args: Any) -> dict[str, Any]:
    config = {
        "location": getattr(args, "qdrant_location", None),
        "path": getattr(args, "qdrant_path", None),
        "url": getattr(args, "qdrant_url", None),
        "host": getattr(args, "qdrant_host", None),
        "port": getattr(args, "qdrant_port", None),
        "prefer_grpc": getattr(args, "prefer_grpc", None),
    }
    return {key: value for key, value in config.items() if value not in (None, "")}


def add_qdrant_connection_args(parser: Any) -> None:
    parser.add_argument("--qdrant-location", default=None, help="Qdrant local location, e.g. :memory:")
    parser.add_argument("--qdrant-path", default=None, help="Qdrant local persistent path")
    parser.add_argument("--qdrant-url", default=None, help="Qdrant server URL")
    parser.add_argument("--qdrant-host", default=None, help="Qdrant server host")
    parser.add_argument("--qdrant-port", type=int, default=None, help="Qdrant server port")
    parser.add_argument("--prefer-grpc", action="store_true", help="Prefer gRPC when connecting to Qdrant")


def build_store(qdrant_config: dict[str, Any] | None) -> QdrantVectorStore:
    require_explicit_qdrant_target(qdrant_config)
    return QdrantVectorStore.from_config(qdrant_config or {})


def require_explicit_qdrant_target(qdrant_config: dict[str, Any] | None) -> None:
    config = qdrant_config or {}
    if any(config.get(key) not in (None, "") for key in ("location", "path", "url", "host")):
        return
    raise ValueError(
        "live Qdrant build requires an explicit target; pass --qdrant-location :memory: "
        "for ephemeral smoke, or --qdrant-path/--qdrant-url/--qdrant-host for durable builds"
    )


def is_ephemeral_qdrant_target(qdrant_config: dict[str, Any] | None) -> bool:
    config = qdrant_config or {}
    return config.get("location") == ":memory:" and not any(config.get(key) not in (None, "") for key in ("path", "url", "host"))


def validate_qdrant_build_controls(
    *,
    batch_size: int,
    limit_items: int | None,
    dry_run: bool,
    qdrant_config: dict[str, Any] | None,
) -> None:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if limit_items is not None and limit_items < 0:
        raise ValueError("limit_items must be non-negative")
    if not dry_run and limit_items is not None and not is_ephemeral_qdrant_target(qdrant_config):
        raise ValueError("non-dry-run --limit-items is only allowed with --qdrant-location :memory: smoke builds")


def qdrant_collection_manifest_base(
    *,
    schema_version: str,
    collection_name: str,
    collection_schema_version: str,
    vector_size: int | None,
    distance: str = DEFAULT_QDRANT_DISTANCE,
    dry_run: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "created_at": created_at_utc(),
        "backend": "qdrant",
        "collection_name": str(collection_name),
        "qdrant_collection_schema_version": collection_schema_version,
        "vector_size": int(vector_size) if vector_size is not None else None,
        "distance": normalize_qdrant_distance(distance),
        "dry_run": bool(dry_run),
    }


def write_manifest_if_requested(manifest_path: str | Path | None, manifest: dict[str, Any]) -> None:
    if manifest_path:
        write_json(Path(manifest_path), manifest)
