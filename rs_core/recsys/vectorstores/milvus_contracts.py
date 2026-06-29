from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MILVUS_RAG_CHUNK_SCHEMA_VERSION = "milvus_rag_chunk_v1"
MILVUS_TWO_TOWER_ITEM_SCHEMA_VERSION = "milvus_two_tower_item_v1"

MILVUS_RAG_CHUNK_INDEX_MANIFEST_SCHEMA_VERSION = "milvus_rag_chunk_index_manifest_v1"
MILVUS_TWO_TOWER_ITEM_INDEX_MANIFEST_SCHEMA_VERSION = "milvus_two_tower_item_index_manifest_v1"

DEFAULT_MILVUS_METRIC_TYPE = "COSINE"
DEFAULT_MILVUS_INDEX_TYPE = "AUTOINDEX"
DEFAULT_MILVUS_RAG_CHUNK_COLLECTION = "rs_agent_rag_chunks_milvus_v1"
DEFAULT_MILVUS_TWO_TOWER_COLLECTION = "rs_agent_two_tower_items_milvus_v1"

MILVUS_RAG_SCALAR_FIELDS = (
    "schema_version",
    "item_id",
    "corpus_scope",
    "source_name",
    "index_build_id",
    "no_holdout",
    "candidate_generation_allowed",
)
MILVUS_TWO_TOWER_SCALAR_FIELDS = (
    "schema_version",
    "source_name",
    "item_id",
    "index_build_id",
    "no_holdout",
    "train_only",
    "candidate_generation_allowed",
)


class OptionalMilvusDependencyMissing(RuntimeError):
    """Raised when a Milvus backend is requested without pymilvus installed."""


@dataclass(frozen=True)
class MilvusCollectionSpec:
    collection_name: str
    vector_size: int
    metric_type: str = DEFAULT_MILVUS_METRIC_TYPE
    index_type: str = DEFAULT_MILVUS_INDEX_TYPE
    schema_version: str = ""
    scalar_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.collection_name:
            raise ValueError("Milvus collection_name is required")
        if self.vector_size <= 0:
            raise ValueError("Milvus vector_size must be positive")


def normalize_milvus_metric_type(value: str) -> str:
    metric_type = str(value or DEFAULT_MILVUS_METRIC_TYPE).strip().upper()
    if metric_type not in {"COSINE", "IP", "L2"}:
        raise ValueError(f"unsupported Milvus metric type: {value}")
    return metric_type


def normalize_milvus_index_type(value: str) -> str:
    return str(value or DEFAULT_MILVUS_INDEX_TYPE).strip().upper()


def milvus_payload_for_schema(payload: dict[str, Any], schema_version: str) -> dict[str, Any]:
    row = dict(payload)
    row["schema_version"] = schema_version
    if "source" in row and "source_name" not in row:
        row["source_name"] = row.get("source")
    return row
