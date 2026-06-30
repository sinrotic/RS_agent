from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from rs_core.online.recall.vector_index import normalize_vector
from rs_core.data.vectorstores.milvus_builders import (
    batched,
    build_store,
    infer_vector_size,
    milvus_collection_manifest_base,
    validate_milvus_build_controls,
    write_manifest_if_requested,
)
from rs_core.data.vectorstores.milvus_contracts import (
    DEFAULT_MILVUS_INDEX_TYPE,
    DEFAULT_MILVUS_METRIC_TYPE,
    DEFAULT_MILVUS_TWO_TOWER_COLLECTION,
    MILVUS_TWO_TOWER_ITEM_INDEX_MANIFEST_SCHEMA_VERSION,
    MILVUS_TWO_TOWER_ITEM_SCHEMA_VERSION,
    MILVUS_TWO_TOWER_SCALAR_FIELDS,
    MilvusCollectionSpec,
    milvus_payload_for_schema,
)
from rs_core.data.vectorstores.milvus_filters import and_expr, ne_expr, schema_version_expr, source_name_expr
from rs_core.data.vectorstores.payloads import stable_vector_point_id, two_tower_item_payload
from rs_core.online.recall.vectorstores.two_tower_source_build import item_rows, load_source_index, validate_source_manifest


def build_milvus_two_tower_item_index(
    *,
    source_index_manifest_path: str | Path,
    collection_name: str = DEFAULT_MILVUS_TWO_TOWER_COLLECTION,
    milvus_config: dict[str, Any] | None = None,
    manifest_path: str | Path | None = None,
    batch_size: int = 512,
    limit_items: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    validate_milvus_build_controls(batch_size=batch_size, limit_items=limit_items, dry_run=dry_run, milvus_config=milvus_config)
    manifest_file = Path(source_index_manifest_path).resolve()
    source_manifest = validate_source_manifest(manifest_file)
    index = load_source_index(manifest_file, source_manifest)
    rows = [(item_id, normalize_vector(vector), metadata) for item_id, vector, metadata in item_rows(index, limit_items=limit_items)]
    vector_size = infer_vector_size([vector for _item_id, vector, _metadata in rows]) if rows else None
    _validate_vectors(rows, vector_size)
    index_build_id = stable_vector_point_id("milvus_two_tower_build", index.source_name, manifest_file, uuid4().hex)

    manifest = milvus_collection_manifest_base(
        schema_version=MILVUS_TWO_TOWER_ITEM_INDEX_MANIFEST_SCHEMA_VERSION,
        collection_name=collection_name,
        collection_schema_version=MILVUS_TWO_TOWER_ITEM_SCHEMA_VERSION,
        vector_size=vector_size,
        metric_type=DEFAULT_MILVUS_METRIC_TYPE,
        index_type=DEFAULT_MILVUS_INDEX_TYPE,
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

    if not dry_run:
        store = build_store(milvus_config)
        if rows:
            store.ensure_collection(
                MilvusCollectionSpec(
                    collection_name=collection_name,
                    vector_size=int(vector_size or 0),
                    metric_type=DEFAULT_MILVUS_METRIC_TYPE,
                    index_type=DEFAULT_MILVUS_INDEX_TYPE,
                    schema_version=MILVUS_TWO_TOWER_ITEM_SCHEMA_VERSION,
                    scalar_fields=MILVUS_TWO_TOWER_SCALAR_FIELDS,
                )
            )
            for batch in batched(rows, batch_size):
                store.upsert_points(
                    collection_name=collection_name,
                    points=[
                        (
                            stable_vector_point_id("milvus_two_tower", index.source_name, item_id),
                            vector,
                            milvus_payload_for_schema(
                                two_tower_item_payload(
                                    item_id=item_id,
                                    source_name=index.source_name,
                                    index_build_id=index_build_id,
                                    metadata=metadata | index.model_metadata,
                                ),
                                MILVUS_TWO_TOWER_ITEM_SCHEMA_VERSION,
                            ),
                        )
                        for item_id, vector, metadata in batch
                    ],
                )
            store.delete_points_by_filter(collection_name=collection_name, query_filter=_stale_same_source_expr(index.source_name, index_build_id), ignore_missing=True)
            manifest["stale_points_deleted_for_source"] = True

    write_manifest_if_requested(manifest_path, manifest)
    return manifest


def _validate_vectors(rows: list[tuple[str, list[float], dict[str, Any]]], vector_size: int | None) -> None:
    if not rows:
        return
    if not vector_size:
        raise ValueError("two-tower Milvus build requires at least one non-empty vector")
    for item_id, vector, _metadata in rows:
        if len(vector) != vector_size:
            raise ValueError(f"two-tower vector dimension mismatch for item {item_id!r}: expected {vector_size}, got {len(vector)}")
        if any(not math.isfinite(value) for value in vector):
            raise ValueError(f"two-tower vector contains non-finite value for item {item_id!r}")


def _stale_same_source_expr(source_name: str, index_build_id: str) -> str:
    return and_expr(schema_version_expr(MILVUS_TWO_TOWER_ITEM_SCHEMA_VERSION), source_name_expr(source_name), ne_expr("index_build_id", index_build_id))
