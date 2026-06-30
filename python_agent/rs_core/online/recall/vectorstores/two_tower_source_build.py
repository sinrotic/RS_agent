from __future__ import annotations

from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json
from rs_core.offline.training.two_tower_DSSM.source_manifest import validate_two_tower_dssm_source_index_manifest
from rs_core.online.recall.two_tower_source_manifest import validate_two_tower_source_index_manifest
from rs_core.online.recall.vector_index import VectorIndex, load_vector_index_artifact, normalize_vector


def validate_source_manifest(path: Path) -> dict[str, Any]:
    raw = read_json(path)
    schema_version = raw.get("schema_version")
    if schema_version == "two_tower_dssm_source_index_v1":
        manifest = validate_two_tower_dssm_source_index_manifest(path)
    else:
        manifest = validate_two_tower_source_index_manifest(path)
    if manifest.get("no_holdout") is not True:
        raise ValueError("two-tower source manifest must explicitly set no_holdout=true")
    return manifest


def load_source_index(path: Path, manifest: dict[str, Any]) -> VectorIndex:
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


def item_rows(index: VectorIndex, *, limit_items: int | None) -> list[tuple[str, list[float], dict[str, Any]]]:
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


def _vector(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [float(item) for item in value]


def _resolve_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()
