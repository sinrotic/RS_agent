from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json


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

    def __bool__(self) -> bool:
        return bool(self.items)

    def get_item_vector(self, item_id: str) -> list[float]:
        return list(self.items.get(item_id, {}).get("embedding", []))

    def get_user_vector(self, user_id: str) -> list[float]:
        return list(self.user_embeddings.get(user_id, []))

    def search(self, query_vector: list[float], limit: int, excluded_items: set[str] | None = None) -> list[VectorSearchResult]:
        excluded_items = excluded_items or set()
        normalized_query = normalize_vector(query_vector)
        if not normalized_query:
            return []
        rows = []
        for item_id, record in self.items.items():
            if item_id in excluded_items:
                continue
            score = dot_score(normalized_query, record.get("embedding", []))
            if score <= 0.0:
                continue
            rows.append(VectorSearchResult(item_id=item_id, score=round(score, 6), metadata={k: v for k, v in record.items() if k != "embedding"}))
        return heapq.nsmallest(limit, rows, key=lambda item: (-item.score, item.item_id))


def load_vector_index_artifact(path: str | Path) -> VectorIndex:
    artifact_path = Path(path)
    manifest = read_json(artifact_path) if artifact_path.suffix == ".json" else {}
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
