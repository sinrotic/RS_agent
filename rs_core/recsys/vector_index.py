from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised in environments without numpy
    np = None

from rs_core.common.io import iter_jsonl, read_json
from rs_core.recsys.two_tower_source_manifest import validate_two_tower_source_index_manifest


@dataclass
class VectorSearchResult:
    item_id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorIndex:
    items: dict[str, dict[str, Any]]
    user_embeddings: dict[str, list[float]] = field(default_factory=dict)
    source_name: str = "two_tower"
    model_metadata: dict[str, Any] = field(default_factory=dict)
    _item_ids: list[str] | None = field(default=None, init=False, repr=False)
    _item_matrix: Any = field(default=None, init=False, repr=False)

    def __bool__(self) -> bool:
        return bool(self.items)

    def get_item_vector(self, item_id: str) -> list[float]:
        return list(self.items.get(item_id, {}).get("embedding", []))

    def get_user_vector(self, user_id: str) -> list[float]:
        return list(self.user_embeddings.get(user_id, []))

    def search(self, query_vector: list[float], limit: int, excluded_items: set[str] | None = None) -> list[VectorSearchResult]:
        excluded_items = excluded_items or set()
        normalized_query = normalize_vector(query_vector)
        if not normalized_query or limit <= 0:
            return []
        if np is not None:
            return self._search_numpy(normalized_query, limit, excluded_items)
        return self._search_heap(normalized_query, limit, excluded_items)

    def search_many(
        self,
        query_vectors: dict[str, list[float]],
        limit: int,
        excluded_items: dict[str, set[str]] | None = None,
        item_block_size: int = 50000,
    ) -> dict[str, list[VectorSearchResult]]:
        normalized = {key: normalize_vector(vector) for key, vector in query_vectors.items()}
        normalized = {key: vector for key, vector in normalized.items() if vector}
        if not normalized or limit <= 0:
            return {key: [] for key in query_vectors}
        if np is None:
            results = {key: [] for key in query_vectors}
            for key, vector in normalized.items():
                results[key] = self.search(vector, limit, (excluded_items or {}).get(key, set()))
            return results
        item_ids, matrix = self._numpy_items()
        query_keys = list(normalized)
        query_matrix = np.asarray([normalized[key] for key in query_keys], dtype=np.float32)
        per_query: dict[str, list[tuple[float, str]]] = {key: [] for key in query_keys}
        keep_count = max(limit * 4, limit + max((len(items) for items in (excluded_items or {}).values()), default=0))
        for start in range(0, len(item_ids), item_block_size):
            block = matrix[start : start + item_block_size]
            scores = query_matrix @ block.T
            block_keep = min(scores.shape[1], keep_count)
            for row_index, key in enumerate(query_keys):
                row_scores = scores[row_index]
                if block_keep < row_scores.shape[0]:
                    local_indices = np.argpartition(row_scores, -block_keep)[-block_keep:]
                else:
                    local_indices = np.arange(row_scores.shape[0])
                excluded = (excluded_items or {}).get(key, set())
                block_entries = []
                for local_index in local_indices:
                    score = float(row_scores[int(local_index)])
                    if score <= 0.0:
                        continue
                    item_id = item_ids[start + int(local_index)]
                    if item_id not in excluded:
                        block_entries.append((-round(score, 6), item_id))
                if block_entries:
                    per_query[key] = heapq.nsmallest(keep_count, per_query[key] + block_entries)
        results = {key: [] for key in query_vectors}
        for key, entries in per_query.items():
            results[key] = [self._result(item_id, -score) for score, item_id in entries[:limit]]
        return results

    def _search_numpy(self, normalized_query: list[float], limit: int, excluded_items: set[str]) -> list[VectorSearchResult]:
        item_ids, matrix = self._numpy_items()
        if matrix.size == 0:
            return []
        scores = matrix @ np.asarray(normalized_query, dtype=np.float32)
        keep_count = min(len(item_ids), max(limit + len(excluded_items), limit * 4))
        if keep_count < len(item_ids):
            candidate_indices = np.argpartition(scores, -keep_count)[-keep_count:]
        else:
            candidate_indices = np.arange(len(item_ids))
        rows = []
        for index in candidate_indices:
            score = float(scores[int(index)])
            if score <= 0.0:
                continue
            item_id = item_ids[int(index)]
            if item_id in excluded_items:
                continue
            rows.append(self._result(item_id, score))
        return heapq.nsmallest(limit, rows, key=lambda item: (-item.score, item.item_id))

    def _search_heap(self, normalized_query: list[float], limit: int, excluded_items: set[str]) -> list[VectorSearchResult]:
        heap: list[tuple[float, str, VectorSearchResult]] = []
        for item_id, record in self.items.items():
            if item_id in excluded_items:
                continue
            score = dot_score(normalized_query, record.get("embedding", []))
            if score <= 0.0:
                continue
            result = self._result(item_id, score)
            entry = (-result.score, item_id, result)
            if len(heap) < limit:
                heapq.heappush(heap, entry)
            else:
                combined = heap + [entry]
                heap = heapq.nsmallest(limit, combined)
        return [item for _score, _item_id, item in sorted(heap, key=lambda entry: (entry[0], entry[1]))]

    def _numpy_items(self) -> tuple[list[str], Any]:
        if self._item_ids is None or self._item_matrix is None:
            self._item_ids = list(self.items)
            self._item_matrix = np.asarray([self.items[item_id].get("embedding", []) for item_id in self._item_ids], dtype=np.float32)
        return self._item_ids, self._item_matrix

    def _result(self, item_id: str, score: float) -> VectorSearchResult:
        record = self.items[item_id]
        return VectorSearchResult(item_id=item_id, score=round(score, 6), metadata={k: v for k, v in record.items() if k != "embedding"})


def load_vector_index_artifact(path: str | Path) -> VectorIndex:
    artifact_path = Path(path)
    manifest = read_json(artifact_path) if artifact_path.suffix == ".json" else {}
    if manifest.get("schema_version") == "two_tower_source_index_v1":
        return _load_two_tower_source_index(artifact_path)
    contract = manifest.get("contract", {}) if manifest else {}
    index_path = _contract_path(artifact_path, contract.get("recall_index")) if contract else artifact_path
    user_path = _contract_path(artifact_path, contract.get("user_embeddings")) if contract.get("user_embeddings") else None
    model_path = _contract_path(artifact_path, contract.get("model")) if contract.get("model") else None

    model_metadata = read_json(model_path) if model_path and model_path.exists() else {}
    source_name = str(manifest.get("source_name") or model_metadata.get("source_name") or "two_tower")
    return VectorIndex(
        items=_load_item_vectors(index_path, source_name, manifest, model_metadata),
        user_embeddings=_load_user_vectors(user_path) if user_path else {},
        source_name=source_name,
        model_metadata={
            "artifact_type": manifest.get("artifact_type", "two_tower_recall_index"),
            "variant": manifest.get("variant") or model_metadata.get("variant", ""),
            "model_type": model_metadata.get("model_type", ""),
            "source_name": source_name,
        },
    )


def _load_two_tower_source_index(manifest_path: Path) -> VectorIndex:
    manifest = validate_two_tower_source_index_manifest(manifest_path)
    index_path = _contract_path(manifest_path, manifest["index_path"])
    user_path = _contract_path(manifest_path, manifest.get("user_embedding_path")) if manifest.get("user_embedding_path") else None
    source_name = str(manifest["source_name"])
    return VectorIndex(
        items=_load_item_vectors(index_path, source_name, manifest, manifest),
        user_embeddings=_load_user_vectors(user_path) if user_path else {},
        source_name=source_name,
        model_metadata={
            "artifact_type": manifest["schema_version"],
            "variant": manifest["variant"],
            "model_type": manifest["model_type"],
            "source_name": source_name,
        },
    )


def average_vectors(vectors: list[list[float]], recency_decay: float = 0.85) -> list[float]:
    vectors = [vector for vector in vectors if vector]
    if not vectors:
        return []
    dim = len(vectors[0])
    output = [0.0] * dim
    total_weight = 0.0
    for rank, vector in enumerate(reversed(vectors)):
        weight = recency_decay**rank
        total_weight += weight
        for index, value in enumerate(vector[:dim]):
            output[index] += value * weight
    if total_weight:
        output = [value / total_weight for value in output]
    return normalize_vector(output)


def dot_score(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if not norm:
        return []
    return [float(value) / norm for value in vector]


def _load_item_vectors(path: Path, source_name: str, manifest: dict[str, Any], model_metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = {}
    for row in iter_jsonl(path):
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        vector = _vector(row.get("embedding"))
        if not item_id or not vector:
            continue
        metadata = dict(row)
        metadata["embedding"] = normalize_vector(vector)
        metadata.setdefault("parent_asin", item_id)
        metadata.setdefault("two_tower_source_name", source_name)
        metadata.setdefault("two_tower_variant", manifest.get("variant") or model_metadata.get("variant", ""))
        metadata.setdefault("two_tower_model_type", model_metadata.get("model_type", ""))
        items[item_id] = metadata
    return items


def _load_user_vectors(path: Path) -> dict[str, list[float]]:
    vectors = {}
    for row in iter_jsonl(path):
        user_id = str(row.get("user_id") or "")
        vector = _vector(row.get("embedding"))
        if user_id and vector:
            vectors[user_id] = normalize_vector(vector)
    return vectors


def _vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(item) for item in value]


def _contract_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute() or path.exists():
        return path
    relative_to_manifest = manifest_path.parent / path
    if relative_to_manifest.exists():
        return relative_to_manifest
    return path
