from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json
from rs_core.recsys.two_tower_DSSM.source_manifest import validate_two_tower_dssm_source_index_manifest
from rs_core.recsys.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_core.recsys.vector_index import VectorIndex, load_vector_index_artifact, normalize_vector
from rs_core.recsys.vectorstores.qdrant_builders import (
    batched,
    build_store,
    created_at_utc,
    infer_vector_size,
    qdrant_collection_manifest_base,
    validate_qdrant_build_controls,
    write_manifest_if_requested,
)
from rs_core.recsys.vectorstores.qdrant_contracts import (
    DEFAULT_QDRANT_DISTANCE,
    DEFAULT_TWO_TOWER_COLLECTION,
    QDRANT_TWO_TOWER_ITEM_INDEX_MANIFEST_SCHEMA_VERSION,
    QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION,
    QDRANT_TWO_TOWER_PAYLOAD_INDEX_FIELDS,
    QdrantCollectionSpec,
)
from rs_core.recsys.vectorstores.qdrant_filters import index_build_id_condition, schema_version_condition, source_name_condition
from rs_core.recsys.vectorstores.qdrant_payloads import stable_qdrant_point_id, two_tower_item_payload


def build_qdrant_two_tower_item_index(
    *,
    source_index_manifest_path: str | Path,
    collection_name: str = DEFAULT_TWO_TOWER_COLLECTION,
    qdrant_config: dict[str, Any] | None = None,
    manifest_path: str | Path | None = None,
    batch_size: int = 512,
    limit_items: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    validate_qdrant_build_controls(batch_size=batch_size, limit_items=limit_items, dry_run=dry_run, qdrant_config=qdrant_config)
    manifest_file = Path(source_index_manifest_path).resolve()
    source_manifest = _validate_source_manifest(manifest_file)
    index = _load_source_index(manifest_file, source_manifest)
    rows = list(_item_rows(index, limit_items=limit_items))
    vector_size = infer_vector_size([vector for _item_id, vector, _metadata in rows]) if rows else None
    _validate_vectors(rows, vector_size)
    build_started_at = created_at_utc()
    index_build_id = stable_qdrant_point_id("two_tower_build", index.source_name, manifest_file, len(rows), vector_size or "none", build_started_at)

    manifest = qdrant_collection_manifest_base(
        schema_version=QDRANT_TWO_TOWER_ITEM_INDEX_MANIFEST_SCHEMA_VERSION,
        collection_name=collection_name,
        collection_schema_version=QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION,
        vector_size=vector_size,
        distance=DEFAULT_QDRANT_DISTANCE,
        dry_run=dry_run,
    )
    manifest.update(
        {
            "source_index_manifest_path": str(manifest_file),
            "source_manifest_schema_version": source_manifest.get("schema_version"),
            "source_manifest_validated": True,
            "source_name": index.source_name,
            "variant": source_manifest.get("variant") or index.model_metadata.get("variant"),
            "model_type": source_manifest.get("model_type") or index.model_metadata.get("model_type"),
            "item_count": len(index.items),
            "upserted_item_count": 0 if dry_run else len(rows),
            "selected_item_count": len(rows),
            "index_build_id": index_build_id,
            "stale_points_deleted_for_source": False,
            "limit_items": limit_items,
            "train_only": True,
            "no_holdout": True,
            "candidate_generation_allowed": True,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
        }
    )

    if not dry_run and rows:
        store = build_store(qdrant_config)
        store.ensure_collection(
            QdrantCollectionSpec(
                collection_name=collection_name,
                vector_size=int(vector_size or 0),
                distance=DEFAULT_QDRANT_DISTANCE,
                schema_version=QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION,
                payload_indexes=QDRANT_TWO_TOWER_PAYLOAD_INDEX_FIELDS,
            )
        )
        for batch in batched(rows, batch_size):
            store.upsert_points(
                collection_name=collection_name,
                points=[
                    (
                        stable_qdrant_point_id("two_tower", index.source_name, item_id),
                        vector,
                        two_tower_item_payload(
                            item_id=item_id,
                            source_name=index.source_name,
                            index_build_id=index_build_id,
                            metadata=metadata | index.model_metadata,
                        ),
                    )
                    for item_id, vector, metadata in batch
                ],
            )
        store.delete_points_by_filter(
            collection_name=collection_name,
            query_filter=_stale_same_source_filter(index.source_name, index_build_id),
        )
        manifest["stale_points_deleted_for_source"] = True

    write_manifest_if_requested(manifest_path, manifest)
    return manifest


def _validate_source_manifest(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    schema_version = raw.get("schema_version")
    if schema_version == "two_tower_dssm_source_index_v1":
        return validate_two_tower_dssm_source_index_manifest(path)
    return validate_two_tower_source_index_manifest(path)


def _load_source_index(path: Path, manifest: dict[str, Any]) -> VectorIndex:
    if manifest.get("schema_version") == "two_tower_source_index_v1":
        return load_vector_index_artifact(path)
    return VectorIndex(
        items=_load_item_vectors(_resolve_path(path, manifest["index_path"]), manifest),
        user_embeddings=_load_user_vectors(_resolve_path(path, manifest.get("user_embedding_path"))) if manifest.get("user_embedding_path") else {},
        source_name=str(manifest["source_name"]),
        model_metadata={
            "artifact_type": manifest["schema_version"],
            "variant": manifest.get("variant", ""),
            "model_type": manifest.get("model_type", ""),
            "source_name": manifest["source_name"],
            "model_parameters": manifest.get("model_parameters", {}),
        },
    )


def _load_item_vectors(path: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items: dict[str, dict[str, Any]] = {}
    source_name = str(manifest["source_name"])
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        vector = _vector(row.get("embedding"))
        if not item_id or not vector:
            continue
        metadata = dict(row)
        metadata["embedding"] = normalize_vector(vector)
        metadata.setdefault("parent_asin", item_id)
        metadata.setdefault("two_tower_source_name", source_name)
        metadata.setdefault("two_tower_variant", manifest.get("variant", ""))
        metadata.setdefault("two_tower_model_type", manifest.get("model_type", ""))
        items[item_id] = metadata
    return items


def _load_user_vectors(path: Path) -> dict[str, list[float]]:
    vectors: dict[str, list[float]] = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        vector = _vector(row.get("embedding"))
        if user_id and vector:
            vectors[user_id] = normalize_vector(vector)
    return vectors


def _item_rows(index: VectorIndex, *, limit_items: int | None) -> list[tuple[str, list[float], dict[str, Any]]]:
    if limit_items == 0:
        return []
    rows: list[tuple[str, list[float], dict[str, Any]]] = []
    for item_id, record in index.items.items():
        if limit_items is not None and len(rows) >= limit_items:
            break
        vector = normalize_vector(list(record.get("embedding", [])))
        if not vector:
            continue
        rows.append((item_id, vector, {key: value for key, value in record.items() if key != "embedding"}))
    return rows


def _validate_limit_items(limit_items: int | None) -> None:
    if limit_items is not None and limit_items < 0:
        raise ValueError("limit_items must be non-negative")


def _validate_vectors(rows: list[tuple[str, list[float], dict[str, Any]]], vector_size: int | None) -> None:
    if not rows:
        return
    if not vector_size:
        raise ValueError("two-tower Qdrant build requires at least one non-empty vector")
    for item_id, vector, _metadata in rows:
        if len(vector) != vector_size:
            raise ValueError(f"two-tower vector dimension mismatch for item {item_id!r}: expected {vector_size}, got {len(vector)}")
        if any(not math.isfinite(value) for value in vector):
            raise ValueError(f"two-tower vector contains non-finite value for item {item_id!r}")


def _stale_same_source_filter(source_name: str, index_build_id: str) -> Any:
    from rs_core.recsys.vectorstores.qdrant_client import qdrant_models

    models = qdrant_models()
    return models.Filter(
        must=[
            schema_version_condition(QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION),
            source_name_condition(source_name),
        ],
        must_not=[index_build_id_condition(index_build_id)],
    )



def _vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(item) for item in value]


def _resolve_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()
