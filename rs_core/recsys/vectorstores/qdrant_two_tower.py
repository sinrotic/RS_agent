from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rs_core.recsys.vector_index import VectorSearchResult, normalize_vector
from rs_core.recsys.vectorstores.qdrant_client import QdrantVectorStore
from rs_core.recsys.vectorstores.qdrant_contracts import QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION
from rs_core.recsys.vectorstores.qdrant_filters import (
    candidate_generation_allowed_condition,
    exclude_item_ids_filter,
    no_holdout_condition,
    schema_version_condition,
    source_name_condition,
    train_only_condition,
)


@dataclass
class QdrantTwoTowerIndex:
    store: QdrantVectorStore
    collection_name: str
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    user_embeddings: dict[str, list[float]] = field(default_factory=dict)
    source_name: str = "two_tower"
    model_metadata: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.collection_name)

    def get_item_vector(self, item_id: str) -> list[float]:
        return list(self.items.get(item_id, {}).get("embedding", []))

    def get_user_vector(self, user_id: str) -> list[float]:
        return list(self.user_embeddings.get(user_id, []))

    def search(
        self,
        query_vector: list[float],
        limit: int,
        excluded_items: set[str] | None = None,
    ) -> list[VectorSearchResult]:
        normalized_query = normalize_vector(query_vector)
        if not normalized_query or limit <= 0:
            return []
        query_filter = exclude_item_ids_filter(
            excluded_items or set(),
            must=[
                schema_version_condition(QDRANT_TWO_TOWER_ITEM_SCHEMA_VERSION),
                source_name_condition(self.source_name),
                no_holdout_condition(),
                train_only_condition(),
                candidate_generation_allowed_condition(),
            ],
        )
        hits = self.store.query_points(
            collection_name=self.collection_name,
            query_vector=normalized_query,
            limit=limit,
            query_filter=query_filter,
        )
        results: list[VectorSearchResult] = []
        for hit in hits:
            if hit.score <= 0.0:
                continue
            metadata = dict(hit.payload)
            metadata.setdefault("two_tower_backend", "qdrant")
            metadata.setdefault("qdrant_collection_name", self.collection_name)
            results.append(VectorSearchResult(item_id=hit.item_id, score=round(hit.score, 6), metadata=metadata))
        return results
