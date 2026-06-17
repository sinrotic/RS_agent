from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from rs_core.recsys.vector_index import VectorIndex, average_vectors

ARTIFACT_USER_EMBEDDING_SOURCE = "artifact_user_embedding"
NO_QUERY_SOURCE = "none"
DEFAULT_SEED_SEQUENCE_KEYS = (
    "recent_positive_item_sequence",
    "recent_strong_positive_item_sequence",
    "recent_item_sequence",
)


@dataclass
class TwoTowerQueryDiagnostics:
    user_id: str
    query_vector: list[float] = field(default_factory=list)
    query_source: str = NO_QUERY_SOURCE
    queryless_reason: str = ""
    seed_sequence_key: str = ""
    seed_items: list[str] = field(default_factory=list)
    seed_item_count: int = 0
    seed_vector_count: int = 0
    excluded_items: set[str] = field(default_factory=set)
    applied_projection: bool = False

    @property
    def has_query(self) -> bool:
        return bool(self.query_vector)


def build_two_tower_query_for_user(
    user_sequence: dict[str, Any],
    index: VectorIndex,
    *,
    seed_window: int,
    recency_decay: float,
    artifact_user_embedding_first: bool = True,
    project_seed_average: bool = True,
    seed_sequence_keys: tuple[str, ...] = DEFAULT_SEED_SEQUENCE_KEYS,
    exclude_recent_items: bool = True,
    exclude_seed_items: bool = True,
) -> TwoTowerQueryDiagnostics:
    """Build a train-only TwoTower query vector and structured diagnostics for one user.

    The returned query only uses trained artifact vectors and train sequence fields from
    ``user_sequence``. Labels from valid/test/eval splits must not be passed here.
    Seed vectors are ordered oldest-to-newest so ``average_vectors`` applies recency
    weights in the intended direction.
    """

    if seed_window <= 0:
        raise ValueError("seed_window must be positive")
    user_id = str(user_sequence.get("user_id") or user_sequence.get("reviewer_id") or "")
    recent_items = _sequence_items(user_sequence.get("recent_item_sequence", []))
    excluded_items = set(recent_items) if exclude_recent_items else set()

    if artifact_user_embedding_first and user_id:
        user_vector = index.get_user_vector(user_id)
        if _valid_vector(user_vector):
            return TwoTowerQueryDiagnostics(
                user_id=user_id,
                query_vector=user_vector,
                query_source=ARTIFACT_USER_EMBEDDING_SOURCE,
                excluded_items=excluded_items,
            )

    best_reason = "no_train_seed_items"
    best_seed_items: list[str] = []
    best_seed_vector_count = 0
    for sequence_key in seed_sequence_keys:
        seed_items = unique_recent_items_chronological(_sequence_items(user_sequence.get(sequence_key, [])), seed_window)
        if not seed_items:
            continue
        best_seed_items = seed_items
        seed_vectors = [index.get_item_vector(item_id) for item_id in seed_items]
        seed_vectors = [vector for vector in seed_vectors if _valid_vector(vector)]
        best_seed_vector_count = max(best_seed_vector_count, len(seed_vectors))
        if not seed_vectors:
            best_reason = "seed_items_missing_item_vectors"
            continue
        query_vector = average_vectors(seed_vectors, recency_decay=recency_decay)
        if not query_vector:
            best_reason = "average_seed_vector_empty"
            continue
        applied_projection = False
        if project_seed_average and has_user_tower_projection(index):
            projected = apply_user_tower_projection(query_vector, index)
            if not projected:
                best_reason = "user_tower_projection_empty"
                continue
            query_vector = projected
            applied_projection = True
        excluded = set(excluded_items)
        if exclude_seed_items:
            excluded.update(seed_items)
        return TwoTowerQueryDiagnostics(
            user_id=user_id,
            query_vector=query_vector,
            query_source=seed_query_source(sequence_key),
            seed_sequence_key=sequence_key,
            seed_items=seed_items,
            seed_item_count=len(seed_items),
            seed_vector_count=len(seed_vectors),
            excluded_items=excluded,
            applied_projection=applied_projection,
        )

    return TwoTowerQueryDiagnostics(
        user_id=user_id,
        query_source=NO_QUERY_SOURCE,
        queryless_reason=best_reason,
        seed_items=best_seed_items,
        seed_item_count=len(best_seed_items),
        seed_vector_count=best_seed_vector_count,
        excluded_items=excluded_items,
    )


def unique_recent_items_chronological(items: list[str], max_items_per_user: int) -> list[str]:
    """Return unique recent items in oldest-to-newest order within the selected window."""

    recent = deque(maxlen=max_items_per_user)
    seen: set[str] = set()
    for item_id in reversed(items):
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        recent.appendleft(item_id)
        if len(recent) >= max_items_per_user:
            break
    return list(recent)


def seed_query_source(sequence_key: str) -> str:
    return f"{sequence_key}_average_vectors"


def is_seed_average_source(query_source: str) -> bool:
    return query_source.endswith("_average_vectors")


def has_user_tower_projection(index: VectorIndex) -> bool:
    params = index.model_metadata.get("model_parameters", {})
    return isinstance(params, dict) and bool(params.get("user_tower.0.weight")) and bool(params.get("user_tower.2.weight"))


def apply_user_tower_projection(query_vector: list[float], index: VectorIndex) -> list[float]:
    params = index.model_metadata.get("model_parameters", {})
    if not isinstance(params, dict) or not params:
        return query_vector
    w1 = params.get("user_tower.0.weight")
    b1 = params.get("user_tower.0.bias")
    w2 = params.get("user_tower.2.weight")
    b2 = params.get("user_tower.2.bias")
    if not w1 or not w2:
        return query_vector
    try:
        import numpy as np

        x0 = np.asarray(query_vector, dtype=np.float32)
        w1_array = np.asarray(w1, dtype=np.float32)
        b1_array = np.asarray(b1 if b1 is not None else np.zeros(w1_array.shape[0]), dtype=np.float32)
        w2_array = np.asarray(w2, dtype=np.float32)
        b2_array = np.asarray(b2 if b2 is not None else np.zeros(w2_array.shape[0]), dtype=np.float32)
        x1 = np.maximum(w1_array @ x0 + b1_array, 0.0)
        out = w2_array @ x1 + b2_array + x0
        norm = float(np.linalg.norm(out))
        if norm <= 1e-9:
            return []
        return (out / norm).astype(float).tolist()
    except (ImportError, TypeError, ValueError):
        return query_vector


def _sequence_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def _valid_vector(vector: list[float]) -> bool:
    return bool(vector) and all(math.isfinite(float(value)) for value in vector)
