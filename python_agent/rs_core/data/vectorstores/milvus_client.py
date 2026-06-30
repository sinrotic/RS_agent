from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Iterable

from rs_core.data.vectorstores.milvus_contracts import (
    DEFAULT_MILVUS_INDEX_TYPE,
    OptionalMilvusDependencyMissing,
    MilvusCollectionSpec,
    normalize_milvus_index_type,
    normalize_milvus_metric_type,
)
from rs_core.data.vectorstores.types import VectorSearchHit

VECTOR_FIELD = "vector"
PRIMARY_KEY_FIELD = "id"
SEARCH_OUTPUT_FIELDS = [
    PRIMARY_KEY_FIELD,
    "item_id",
    "text",
    "field",
    "schema_version",
    "source_name",
    "index_build_id",
    "no_holdout",
    "candidate_generation_allowed",
    "ranking_input_replacement_allowed",
    "promotion_allowed",
    "corpus_scope",
    "chunk_index",
    "embedding_method",
    "embedding_model_name",
    "artifact_scope",
]


def milvus_types() -> tuple[Any, Any]:
    try:
        from pymilvus import DataType, MilvusClient
    except ImportError as exc:  # pragma: no cover - depends on optional dependency state
        raise OptionalMilvusDependencyMissing(
            "pymilvus is required for Milvus vector backends; install the optional milvus dependency before enabling this backend."
        ) from exc
    return MilvusClient, DataType


def build_milvus_client(
    *,
    uri: str | None = None,
    token: str | None = None,
    db_name: str | None = None,
    timeout: int | None = None,
) -> Any:
    _patch_milvus_lite_windows_manifest_save(str(uri or ""))
    MilvusClient, _DataType = milvus_types()
    kwargs: dict[str, Any] = {}
    if token:
        kwargs["token"] = str(token)
    if db_name:
        kwargs["db_name"] = str(db_name)
    if timeout is not None:
        kwargs["timeout"] = int(timeout)
    return MilvusClient(uri=str(uri or "./milvus_lite.db"), **kwargs)


@dataclass
class MilvusVectorStore:
    client: Any

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "MilvusVectorStore":
        return cls(
            build_milvus_client(
                uri=config.get("uri"),
                token=config.get("token"),
                db_name=config.get("db_name"),
                timeout=config.get("timeout"),
            )
        )

    def ensure_collection(self, spec: MilvusCollectionSpec) -> None:
        metric_type = normalize_milvus_metric_type(spec.metric_type)
        index_type = normalize_milvus_index_type(spec.index_type)
        if self._has_collection(spec.collection_name):
            existing_size, existing_metric = _collection_vector_config(self.client.describe_collection(spec.collection_name))
            if existing_size is not None and existing_size != spec.vector_size:
                raise ValueError(
                    f"Milvus collection {spec.collection_name!r} vector size mismatch: expected {spec.vector_size}, got {existing_size}"
                )
            if existing_metric is not None and existing_metric != metric_type:
                raise ValueError(
                    f"Milvus collection {spec.collection_name!r} metric type mismatch: expected {metric_type}, got {existing_metric}"
                )
            return
        _MilvusClient, DataType = milvus_types()
        schema = self.client.create_schema(enable_dynamic_field=True)
        schema.add_field(field_name=PRIMARY_KEY_FIELD, datatype=DataType.VARCHAR, is_primary=True, auto_id=False, max_length=256)
        schema.add_field(field_name=VECTOR_FIELD, datatype=DataType.FLOAT_VECTOR, dim=int(spec.vector_size))
        for field_name in spec.scalar_fields:
            _add_scalar_field(schema, DataType, field_name)
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name=VECTOR_FIELD,
            index_name=f"{VECTOR_FIELD}_index",
            index_type=index_type or DEFAULT_MILVUS_INDEX_TYPE,
            metric_type=metric_type,
        )
        self.client.create_collection(collection_name=spec.collection_name, schema=schema, index_params=index_params, consistency_level="Strong")

    def upsert_points(
        self,
        *,
        collection_name: str,
        points: Iterable[tuple[str | int, list[float], dict[str, Any]]],
    ) -> None:
        rows = _point_rows(points)
        if rows:
            self.client.upsert(collection_name=collection_name, data=rows)

    def insert_points(
        self,
        *,
        collection_name: str,
        points: Iterable[tuple[str | int, list[float], dict[str, Any]]],
    ) -> None:
        rows = _point_rows(points)
        if rows:
            self.client.insert(collection_name=collection_name, data=rows)

    def delete_points_by_filter(self, *, collection_name: str, query_filter: str, ignore_missing: bool = False) -> None:
        try:
            self.client.delete(collection_name=collection_name, filter=str(query_filter))
        except Exception as exc:
            if not ignore_missing or not _is_missing_collection_error(exc):
                raise

    def query_points(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        query_filter: str | None = None,
    ) -> list[VectorSearchHit]:
        if not query_vector or limit <= 0:
            return []
        if hasattr(self.client, "load_collection"):
            self.client.load_collection(collection_name=collection_name)
        response = self.client.search(
            collection_name=collection_name,
            data=[[float(value) for value in query_vector]],
            anns_field=VECTOR_FIELD,
            limit=int(limit),
            filter=query_filter,
            output_fields=SEARCH_OUTPUT_FIELDS,
        )
        rows = response[0] if response and isinstance(response, list) else response
        hits: list[VectorSearchHit] = []
        for row in rows or []:
            payload = _hit_payload(row)
            item_id = str(payload.get("item_id") or "")
            if not item_id:
                continue
            point_id = _get_attr_or_key(row, "id") or _get_attr_or_key(row, PRIMARY_KEY_FIELD) or payload.get(PRIMARY_KEY_FIELD)
            hits.append(VectorSearchHit(item_id=item_id, score=float(_hit_score(row)), payload=payload, point_id=point_id))
        return hits

    def _has_collection(self, collection_name: str) -> bool:
        if hasattr(self.client, "has_collection"):
            return bool(self.client.has_collection(collection_name=collection_name))
        try:
            self.client.describe_collection(collection_name)
            return True
        except Exception as exc:
            if _is_missing_collection_error(exc):
                return False
            raise


def _patch_milvus_lite_windows_manifest_save(uri: str) -> None:
    if not (sys.platform == "win32" and uri.endswith(".db")):
        return
    try:
        import milvus_lite.storage.manifest as manifest_module
        from milvus_lite.storage.manifest import Manifest
    except ImportError:
        return
    if getattr(Manifest.save, "_rs_agent_windows_replace_patch", False):
        return
    original_save = Manifest.save

    def patched_save(self: Any) -> Any:
        original_rename = manifest_module.os.rename
        manifest_module.os.rename = os.replace
        try:
            return original_save(self)
        finally:
            manifest_module.os.rename = original_rename

    setattr(patched_save, "_rs_agent_windows_replace_patch", True)
    Manifest.save = patched_save


def _point_rows(points: Iterable[tuple[str | int, list[float], dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for point_id, vector, payload in points:
        if not vector:
            continue
        row = dict(payload)
        row[PRIMARY_KEY_FIELD] = str(point_id)
        row[VECTOR_FIELD] = [float(value) for value in vector]
        rows.append(row)
    return rows


def _add_scalar_field(schema: Any, DataType: Any, field_name: str) -> None:
    if field_name in {PRIMARY_KEY_FIELD, VECTOR_FIELD}:
        return
    if field_name in {"candidate_generation_allowed", "no_holdout", "promotion_allowed", "ranking_input_replacement_allowed", "train_only"}:
        schema.add_field(field_name=field_name, datatype=DataType.BOOL, nullable=True)
    else:
        schema.add_field(field_name=field_name, datatype=DataType.VARCHAR, max_length=1024, nullable=True)


def _collection_vector_config(collection: Any) -> tuple[int | None, str | None]:
    fields = _get_attr_or_key(collection, "fields") or _get_attr_or_key(_get_attr_or_key(collection, "schema"), "fields") or []
    size = None
    for field in fields:
        name = _get_attr_or_key(field, "name") or _get_attr_or_key(field, "field_name")
        if name == VECTOR_FIELD:
            params = _get_attr_or_key(field, "params") or {}
            size = _get_attr_or_key(params, "dim") or _get_attr_or_key(field, "dim")
            break
    indexes = _get_attr_or_key(collection, "indexes") or _get_attr_or_key(collection, "index_descriptions") or []
    metric_type = None
    for index in indexes:
        params = _get_attr_or_key(index, "params") or _get_attr_or_key(index, "index_param") or index
        metric_type = _get_attr_or_key(params, "metric_type") or _get_attr_or_key(index, "metric_type")
        if metric_type:
            break
    return (int(size) if size is not None else None, normalize_milvus_metric_type(str(metric_type)) if metric_type else None)


def _hit_payload(row: Any) -> dict[str, Any]:
    entity = _get_attr_or_key(row, "entity") or _get_attr_or_key(row, "payload") or row
    if isinstance(entity, dict):
        payload = dict(entity)
    else:
        payload = dict(getattr(entity, "fields", {}) or {})
    payload.pop(VECTOR_FIELD, None)
    return payload


def _hit_score(row: Any) -> float:
    return _get_attr_or_key(row, "distance") or _get_attr_or_key(row, "score") or 0.0


def _is_missing_collection_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, KeyError) or "not found" in message or "doesn't exist" in message or "does not exist" in message


def _get_attr_or_key(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
