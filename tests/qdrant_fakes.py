from __future__ import annotations

import math
import sys
import types
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


class Distance:
    COSINE = "COSINE"
    DOT = "DOT"
    EUCLID = "EUCLID"
    MANHATTAN = "MANHATTAN"


class PayloadSchemaType:
    BOOL = "BOOL"
    INTEGER = "INTEGER"
    KEYWORD = "KEYWORD"


@dataclass
class VectorParams:
    size: int
    distance: str


@dataclass
class MatchAny:
    any: list[Any]


@dataclass
class MatchValue:
    value: Any


@dataclass
class FieldCondition:
    key: str
    match: Any


@dataclass
class Filter:
    must: list[Any] = field(default_factory=list)
    must_not: list[Any] = field(default_factory=list)


@dataclass
class PointStruct:
    id: str | int
    vector: list[float]
    payload: dict[str, Any]


@dataclass
class FilterSelector:
    filter: Filter


class FakeQdrantClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.payload_indexes: dict[str, dict[str, Any]] = {}

    def get_collection(self, *, collection_name: str) -> dict[str, Any]:
        if collection_name not in self.collections:
            raise KeyError(collection_name)
        return self.collections[collection_name]

    def create_collection(self, *, collection_name: str, vectors_config: VectorParams) -> None:
        self.collections[collection_name] = {"config": vectors_config, "points": []}

    def create_payload_index(self, *, collection_name: str, field_name: str, field_schema: Any, wait: bool = True) -> None:
        self.payload_indexes.setdefault(collection_name, {})[field_name] = field_schema

    def upsert(self, *, collection_name: str, points: list[PointStruct], wait: bool = True) -> None:
        collection = self.collections.setdefault(collection_name, {"config": None, "points": []})
        config = collection.get("config")
        rows = collection["points"]
        by_id = {point.id: point for point in rows}
        for point in points:
            if config is not None and len(point.vector) != config.size:
                raise ValueError(f"vector size mismatch: expected {config.size}, got {len(point.vector)}")
            by_id[point.id] = point
        collection["points"] = list(by_id.values())

    def delete(self, *, collection_name: str, points_selector: FilterSelector, wait: bool = True) -> None:
        collection = self.collections.setdefault(collection_name, {"config": None, "points": []})
        query_filter = points_selector.filter
        collection["points"] = [
            point for point in collection.get("points", [])
            if not _matches_filter(point.payload, query_filter)
        ]

    def query_points(
        self,
        *,
        collection_name: str,
        query: list[float],
        limit: int,
        query_filter: Filter | None = None,
    ) -> SimpleNamespace:
        collection = self.collections.get(collection_name, {})
        config = collection.get("config")
        if config is not None and len(query) != config.size:
            raise ValueError(f"query vector size mismatch: expected {config.size}, got {len(query)}")
        points = collection.get("points", [])
        rows = []
        for point in points:
            if query_filter and not _matches_filter(point.payload, query_filter):
                continue
            score = _score(query, point.vector, getattr(config, "distance", Distance.COSINE))
            rows.append(SimpleNamespace(id=point.id, payload=point.payload, score=score))
        rows.sort(key=lambda row: (-(row.score or 0.0), str(row.id)))
        return SimpleNamespace(points=rows[:limit])


def install_fake_qdrant(monkeypatch: Any) -> None:
    models = SimpleNamespace(
        Distance=Distance,
        PayloadSchemaType=PayloadSchemaType,
        VectorParams=VectorParams,
        MatchAny=MatchAny,
        MatchValue=MatchValue,
        FieldCondition=FieldCondition,
        Filter=Filter,
        FilterSelector=FilterSelector,
        PointStruct=PointStruct,
    )
    module = types.ModuleType("qdrant_client")
    module.QdrantClient = FakeQdrantClient
    module.models = models
    monkeypatch.setitem(sys.modules, "qdrant_client", module)


def _score(query: list[float], vector: list[float], distance: str) -> float:
    dot = sum(float(left) * float(right) for left, right in zip(query, vector, strict=True))
    if distance == Distance.COSINE:
        left_norm = math.sqrt(sum(float(value) * float(value) for value in query))
        right_norm = math.sqrt(sum(float(value) * float(value) for value in vector))
        return dot / left_norm / right_norm if left_norm and right_norm else 0.0
    return dot


def _matches_filter(payload: dict[str, Any], query_filter: Filter) -> bool:
    return all(_matches_condition(payload, condition) for condition in query_filter.must or []) and not any(
        _matches_condition(payload, condition) for condition in query_filter.must_not or []
    )


def _matches_condition(payload: dict[str, Any], condition: FieldCondition) -> bool:
    value = payload.get(condition.key)
    match = condition.match
    if hasattr(match, "any"):
        return value in set(match.any)
    if hasattr(match, "value"):
        return value == match.value
    return False
