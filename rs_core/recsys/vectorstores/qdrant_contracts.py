from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

QDRANT_RAG_CHUNK_SCHEMA_VERSION = "qdrant_rag_chunk_v1"
QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION = "qdrant_two_tower_item_v1"
QDRANT_SEMANTIC_VECTOR_ITEM_SCHEMA_VERSION = "qdrant_semantic_vector_item_v1"

QDRANT_RAG_CHUNK_INDEX_MANIFEST_SCHEMA_VERSION = "qdrant_rag_chunk_index_manifest_v1"
QDRANT_TWO_TOWER_ITEM_INDEX_MANIFEST_SCHEMA_VERSION = "qdrant_two_tower_item_index_manifest_v1"

DEFAULT_QDRANT_DISTANCE = "COSINE"
DEFAULT_RAG_CHUNK_COLLECTION = "rs_agent_rag_chunks_v1"
DEFAULT_TWO_TOWER_COLLECTION = "rs_agent_two_tower_items_v1"
DEFAULT_SEMANTIC_VECTOR_COLLECTION = "rs_agent_semantic_vector_items_v1"

QDRANT_RAG_PAYLOAD_INDEX_FIELDS = (
    "schema_version",
    "item_id",
    "corpus_scope",
    "index_build_id",
    "no_holdout",
)
QDRANT_TWO_TOWER_PAYLOAD_INDEX_FIELDS = (
    "schema_version",
    "source_name",
    "item_id",
    "index_build_id",
    "no_holdout",
    "train_only",
    "candidate_generation_allowed",
)


class OptionalQdrantDependencyMissing(RuntimeError):
    """Raised when a Qdrant backend is requested without qdrant-client installed."""


@dataclass(frozen=True)
class QdrantCollectionSpec:
    collection_name: str
    vector_size: int
    distance: str = DEFAULT_QDRANT_DISTANCE
    schema_version: str = ""
    payload_indexes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.collection_name:
            raise ValueError("Qdrant collection_name is required")
        if self.vector_size <= 0:
            raise ValueError("Qdrant vector_size must be positive")


@dataclass(frozen=True)
class VectorSearchHit:
    item_id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    point_id: str | int | None = None


def normalize_qdrant_distance(value: str) -> str:
    distance = str(value or DEFAULT_QDRANT_DISTANCE).strip().upper()
    if distance not in {"COSINE", "DOT", "EUCLID", "MANHATTAN"}:
        raise ValueError(f"unsupported Qdrant distance: {value}")
    return distance
