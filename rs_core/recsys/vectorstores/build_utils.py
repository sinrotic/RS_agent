from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from rs_core.common.io import write_json

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


def write_manifest_if_requested(manifest_path: str | Path | None, manifest: dict) -> None:
    if manifest_path:
        write_json(Path(manifest_path), manifest)
