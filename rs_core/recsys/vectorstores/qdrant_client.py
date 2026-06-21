from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from rs_core.recsys.vectorstores.qdrant_contracts import (
    OptionalQdrantDependencyMissing,
    QdrantCollectionSpec,
    VectorSearchHit,
    normalize_qdrant_distance,
)


def qdrant_models() -> Any:
    try:
        from qdrant_client import models
    except ImportError as exc:  # pragma: no cover - depends on optional dependency state
        raise OptionalQdrantDependencyMissing(
            "qdrant-client is required for Qdrant vector backends; "
            "install the optional qdrant dependency before enabling this backend."
        ) from exc
    return models


def build_qdrant_client(*, location: str | None = None, path: str | None = None, url: str | None = None, host: str | None = None, port: int | None = None, prefer_grpc: bool | None = None) -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:  # pragma: no cover - depends on optional dependency state
        raise OptionalQdrantDependencyMissing(
            "qdrant-client is required for Qdrant vector backends; "
            "install the optional qdrant dependency before enabling this backend."
        ) from exc

    kwargs: dict[str, Any] = {}
    if prefer_grpc is not None:
        kwargs["prefer_grpc"] = bool(prefer_grpc)
    if path:
        return QdrantClient(path=str(path), **kwargs)
    if url:
        return QdrantClient(url=str(url), **kwargs)
    if host:
        client_kwargs = dict(kwargs)
        if port is not None:
            client_kwargs["port"] = int(port)
        return QdrantClient(host=str(host), **client_kwargs)
    return QdrantClient(location or ":memory:", **kwargs)


@dataclass
class QdrantVectorStore:
    client: Any

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "QdrantVectorStore":
        return cls(
            build_qdrant_client(
                location=config.get("location"),
                path=config.get("path"),
                url=config.get("url"),
                host=config.get("host"),
                port=config.get("port"),
                prefer_grpc=config.get("prefer_grpc"),
            )
        )

    def ensure_collection(self, spec: QdrantCollectionSpec) -> None:
        models = qdrant_models()
        expected_distance = normalize_qdrant_distance(spec.distance)
        try:
            collection = self.client.get_collection(collection_name=spec.collection_name)
            existing_size, existing_distance = _collection_vector_config(collection)
            if existing_size is not None and existing_size != spec.vector_size:
                raise ValueError(
                    f"Qdrant collection {spec.collection_name!r} vector size mismatch: "
                    f"expected {spec.vector_size}, got {existing_size}"
                )
            if existing_distance is not None and existing_distance != expected_distance:
                raise ValueError(
                    f"Qdrant collection {spec.collection_name!r} distance mismatch: "
                    f"expected {expected_distance}, got {existing_distance}"
                )
            self.ensure_payload_indexes(collection_name=spec.collection_name, fields=spec.payload_indexes)
            return
        except ValueError as exc:
            if not _is_missing_collection_error(exc):
                raise
        except TypeError:
            raise
        except Exception as exc:
            if not _is_missing_collection_error(exc):
                raise
        distance = getattr(models.Distance, expected_distance)
        self.client.create_collection(
            collection_name=spec.collection_name,
            vectors_config=models.VectorParams(size=spec.vector_size, distance=distance),
        )
        self.ensure_payload_indexes(collection_name=spec.collection_name, fields=spec.payload_indexes)

    def ensure_payload_indexes(self, *, collection_name: str, fields: Iterable[str]) -> None:
        if not fields:
            return
        models = qdrant_models()
        for field_name in fields:
            try:
                self.client.create_payload_index(
                    collection_name=collection_name,
                    field_name=str(field_name),
                    field_schema=_payload_schema_for_field(models, str(field_name)),
                    wait=True,
                )
            except Exception as exc:
                if not _is_existing_payload_index_error(exc):
                    raise

    def upsert_points(
        self,
        *,
        collection_name: str,
        points: Iterable[tuple[str | int, list[float], dict[str, Any]]],
        wait: bool = True,
    ) -> None:
        models = qdrant_models()
        point_structs = [
            models.PointStruct(id=point_id, vector=[float(value) for value in vector], payload=dict(payload))
            for point_id, vector, payload in points
            if vector
        ]
        if not point_structs:
            return
        self.client.upsert(collection_name=collection_name, points=point_structs, wait=wait)

    def delete_points_by_filter(
        self,
        *,
        collection_name: str,
        query_filter: Any,
        wait: bool = True,
    ) -> None:
        models = qdrant_models()
        self.client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(filter=query_filter),
            wait=wait,
        )

    def query_points(
        self,
        *,
        collection_name: str,
        query_vector: list[float],
        limit: int,
        query_filter: Any | None = None,
    ) -> list[VectorSearchHit]:
        if not query_vector or limit <= 0:
            return []
        response = self.client.query_points(
            collection_name=collection_name,
            query=[float(value) for value in query_vector],
            limit=int(limit),
            query_filter=query_filter,
        )
        points = getattr(response, "points", response)
        hits: list[VectorSearchHit] = []
        for point in points:
            payload = dict(getattr(point, "payload", {}) or {})
            item_id = str(payload.get("item_id") or "")
            if not item_id:
                continue
            hits.append(
                VectorSearchHit(
                    item_id=item_id,
                    score=float(getattr(point, "score", 0.0) or 0.0),
                    payload=payload,
                    point_id=getattr(point, "id", None),
                )
            )
        return hits


def _is_missing_collection_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status_code == 404:
        return True
    message = str(exc).lower()
    return isinstance(exc, KeyError) or "not found" in message or "doesn't exist" in message or "does not exist" in message


def _is_existing_payload_index_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "already exists" in message or "already has" in message


def _collection_vector_config(collection: Any) -> tuple[int | None, str | None]:
    config = _get_attr_or_key(collection, "config")
    params = _get_attr_or_key(config, "params") or config
    vectors = _get_attr_or_key(params, "vectors") or _get_attr_or_key(params, "vectors_config") or _get_attr_or_key(collection, "vectors_config") or params
    if isinstance(vectors, dict):
        vectors = next(iter(vectors.values()), None)
    size = _get_attr_or_key(vectors, "size")
    distance = _get_attr_or_key(vectors, "distance")
    return (int(size) if size is not None else None, normalize_qdrant_distance(str(distance)) if distance is not None else None)


def _payload_schema_for_field(models: Any, field_name: str) -> Any:
    schema_type = getattr(models, "PayloadSchemaType", None)
    if schema_type is None:
        return None
    if field_name in {"candidate_generation_allowed", "no_holdout", "promotion_allowed", "ranking_input_replacement_allowed", "train_only"}:
        return schema_type.BOOL
    if field_name == "chunk_index":
        return schema_type.INTEGER
    return schema_type.KEYWORD


def _get_attr_or_key(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
