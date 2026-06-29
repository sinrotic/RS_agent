from __future__ import annotations

import math
import re
import sys
import types
from dataclasses import dataclass, field
from typing import Any


class DataType:
    VARCHAR = "VARCHAR"
    FLOAT_VECTOR = "FLOAT_VECTOR"
    BOOL = "BOOL"


@dataclass
class Field:
    name: str
    datatype: str
    params: dict[str, Any] = field(default_factory=dict)
    is_primary: bool = False
    nullable: bool = False


class Schema:
    def __init__(self, *, enable_dynamic_field: bool = True) -> None:
        self.enable_dynamic_field = enable_dynamic_field
        self.fields: list[Field] = []

    def add_field(self, *, field_name: str, datatype: str, is_primary: bool = False, auto_id: bool = False, max_length: int | None = None, dim: int | None = None, nullable: bool = False) -> None:
        params: dict[str, Any] = {}
        if max_length is not None:
            params["max_length"] = max_length
        if dim is not None:
            params["dim"] = dim
        self.fields.append(Field(name=field_name, datatype=datatype, params=params, is_primary=is_primary, nullable=nullable))


class IndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict[str, Any]] = []

    def add_index(self, **kwargs: Any) -> None:
        self.indexes.append(dict(kwargs))


class FakeMilvusClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.collections: dict[str, dict[str, Any]] = {}
        self.last_search_output_fields: list[str] | None = None

    @staticmethod
    def create_schema(enable_dynamic_field: bool = True) -> Schema:
        return Schema(enable_dynamic_field=enable_dynamic_field)

    @staticmethod
    def prepare_index_params() -> IndexParams:
        return IndexParams()

    def has_collection(self, *, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_collection(self, *, collection_name: str, schema: Schema, index_params: IndexParams, consistency_level: str = "Strong") -> None:
        self.collections[collection_name] = {"schema": schema, "fields": schema.fields, "indexes": index_params.indexes, "rows": []}

    def describe_collection(self, collection_name: str) -> dict[str, Any]:
        if collection_name not in self.collections:
            raise KeyError(collection_name)
        return self.collections[collection_name]

    def upsert(self, *, collection_name: str, data: list[dict[str, Any]]) -> None:
        collection = self.collections.setdefault(collection_name, {"fields": [], "indexes": [], "rows": []})
        dim = _vector_dim(collection)
        by_id = {row["id"]: row for row in collection["rows"]}
        for row in data:
            if dim is not None and len(row["vector"]) != dim:
                raise ValueError(f"vector size mismatch: expected {dim}, got {len(row['vector'])}")
            by_id[str(row["id"])] = dict(row)
        collection["rows"] = list(by_id.values())

    def insert(self, *, collection_name: str, data: list[dict[str, Any]]) -> None:
        collection = self.collections.setdefault(collection_name, {"fields": [], "indexes": [], "rows": []})
        dim = _vector_dim(collection)
        for row in data:
            if dim is not None and len(row["vector"]) != dim:
                raise ValueError(f"vector size mismatch: expected {dim}, got {len(row['vector'])}")
            collection["rows"].append(dict(row))

    def delete(self, *, collection_name: str, filter: str) -> None:
        collection = self.collections.setdefault(collection_name, {"fields": [], "indexes": [], "rows": []})
        collection["rows"] = [row for row in collection["rows"] if not _matches_expr(row, filter)]

    def search(self, *, collection_name: str, data: list[list[float]], anns_field: str, limit: int, filter: str | None = None, output_fields: list[str] | None = None) -> list[list[dict[str, Any]]]:
        self.last_search_output_fields = output_fields
        collection = self.collections.get(collection_name, {"rows": []})
        query = data[0]
        rows = []
        for row in collection.get("rows", []):
            if filter and not _matches_expr(row, filter):
                continue
            entity = _project_output_fields(row, output_fields)
            rows.append({"id": row["id"], "distance": _score(query, row[anns_field]), "entity": entity})
        rows.sort(key=lambda item: (-float(item["distance"]), str(item["id"])))
        return [rows[:limit]]


def install_fake_milvus(monkeypatch: Any) -> None:
    module = types.ModuleType("pymilvus")
    module.MilvusClient = FakeMilvusClient
    module.DataType = DataType
    monkeypatch.setitem(sys.modules, "pymilvus", module)


def _vector_dim(collection: dict[str, Any]) -> int | None:
    for schema_field in collection.get("fields", []):
        if getattr(schema_field, "name", "") == "vector":
            return int(schema_field.params["dim"])
    return None


def _score(query: list[float], vector: list[float]) -> float:
    dot = sum(float(left) * float(right) for left, right in zip(query, vector, strict=True))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in query))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    return dot / left_norm / right_norm if left_norm and right_norm else 0.0


def _project_output_fields(row: dict[str, Any], output_fields: list[str] | None) -> dict[str, Any]:
    if output_fields is None:
        return dict(row)
    if output_fields == ["*"]:
        return {"id": row["id"]}
    entity = {"id": row["id"]}
    entity.update({field_name: row[field_name] for field_name in output_fields if field_name in row})
    return entity


def _matches_expr(row: dict[str, Any], expr: str) -> bool:
    if not expr:
        return True
    return all(_matches_part(row, part.strip().strip("()")) for part in expr.split(" and "))


def _matches_part(row: dict[str, Any], part: str) -> bool:
    match = re.fullmatch(r"(\w+)\s*==\s*(.+)", part)
    if match:
        return row.get(match.group(1)) == _parse_literal(match.group(2))
    match = re.fullmatch(r"(\w+)\s*!=\s*(.+)", part)
    if match:
        return row.get(match.group(1)) != _parse_literal(match.group(2))
    match = re.fullmatch(r"(\w+)\s+in\s+\[(.*)\]", part)
    if match:
        return row.get(match.group(1)) in [_parse_literal(value.strip()) for value in match.group(2).split(",") if value.strip()]
    match = re.fullmatch(r"(\w+)\s+not in\s+\[(.*)\]", part)
    if match:
        return row.get(match.group(1)) not in [_parse_literal(value.strip()) for value in match.group(2).split(",") if value.strip()]
    return False


def _parse_literal(value: str) -> Any:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
    return value
