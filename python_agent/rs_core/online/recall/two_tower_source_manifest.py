from __future__ import annotations

from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json

SCHEMA_VERSION = "two_tower_source_index_v1"
EXPECTED_FIELDS = {
    "source": "two_tower",
    "canonical_source": "two_tower",
    "source_name": "two_tower_youtube_dnn",
    "variant": "youtube_dnn",
    "model_type": "youtube_dnn_two_tower_v1",
    "index_scope": "FULL_DERIVED_INDEX",
}
SOURCE_STATUS = "FULL_DERIVED_INDEX_DIAGNOSTIC"
GOVERNANCE_FIELDS = {
    "train_only": True,
    "candidate_generation_allowed": False,
    "ranking_input_replacement_allowed": False,
    "ranking_replacement_allowed": False,
    "pool1000_allowed": False,
    "promotion_allowed": False,
    "final_pool500_ready_claimed": False,
}
FORBIDDEN_PATH_TOKENS = {"valid", "validation", "test", "holdout", "eval", "oracle"}


def validate_two_tower_source_index_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    if manifest_path.name not in {"source_index_manifest.json", "source_index_manifest.json.tmp"}:
        raise ValueError("two_tower candidate generation requires source_index_manifest.json")
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid two_tower source_index_manifest schema_version")
    for field, expected in EXPECTED_FIELDS.items():
        actual = manifest.get(field)
        if actual != expected:
            raise ValueError(f"invalid two_tower source manifest {field}: {actual!r}")
    if manifest.get("source_status") != SOURCE_STATUS:
        raise ValueError(f"invalid two_tower source manifest source_status: {manifest.get('source_status')!r}")
    for field, expected in GOVERNANCE_FIELDS.items():
        actual = manifest.get(field)
        if actual is not expected:
            raise ValueError(f"invalid two_tower source manifest {field}: {actual!r}")
    row_count = _positive_int(manifest, "row_count")
    embedding_row_count = _positive_int(manifest, "embedding_row_count")
    index_row_count = _positive_int(manifest, "index_row_count")
    if row_count != embedding_row_count or row_count != index_row_count:
        raise ValueError("two_tower source manifest row_count, embedding_row_count, and index_row_count must match")

    embedding_path = _resolve_required_path(manifest_path, manifest.get("embedding_path"), "embedding_path")
    index_path = _resolve_required_path(manifest_path, manifest.get("index_path"), "index_path")
    _reject_forbidden_path_references({"manifest_path": str(manifest_path), "manifest": manifest})
    if _jsonl_row_count(embedding_path) != embedding_row_count:
        raise ValueError("embedding_path row count does not match embedding_row_count")
    if _jsonl_row_count(index_path) != index_row_count:
        raise ValueError("index_path row count does not match index_row_count")

    item_vocab_manifest_path = manifest.get("item_vocab_manifest")
    if item_vocab_manifest_path:
        item_vocab_manifest = read_json(_resolve_required_path(manifest_path, item_vocab_manifest_path, "item_vocab_manifest"))
        item_count = item_vocab_manifest.get("item_count")
        if item_count is not None and int(item_count) != row_count:
            raise ValueError("item vocab item_count must match source index row_count")
        item_vocab_path = item_vocab_manifest.get("item_vocab_path")
        if item_vocab_path:
            resolved_vocab_path = _resolve_required_path(manifest_path, item_vocab_path, "item_vocab_path")
            if _jsonl_row_count(resolved_vocab_path) != row_count:
                raise ValueError("item vocab row count must match source index row_count")
    return manifest


def is_two_tower_source_index_manifest(path: str | Path) -> bool:
    return Path(path).name == "source_index_manifest.json"


def _positive_int(manifest: dict[str, Any], key: str) -> int:
    try:
        value = int(manifest.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _resolve_required_path(manifest_path: Path, value: Any, key: str) -> Path:
    if not value:
        raise ValueError(f"two_tower source manifest missing {key}")
    path = Path(str(value))
    resolved = path if path.is_absolute() else manifest_path.parent / path
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    if _is_forbidden_path(resolved):
        raise ValueError(f"forbidden two_tower source path for {key}: {resolved}")
    return resolved


def _reject_forbidden_path_references(value: Any) -> None:
    matches = []
    for text in _walk_strings(value):
        if _looks_like_path(text) and _is_forbidden_path(Path(text)):
            matches.append(text)
    if matches:
        raise ValueError(f"forbidden two_tower source path references: {sorted(set(matches))}")


def _is_forbidden_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    return bool(parts & FORBIDDEN_PATH_TOKENS)


def _looks_like_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return "/" in normalized or normalized.endswith((".json", ".jsonl", ".parquet", ".npy", ".faiss"))


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_strings(str(key))
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def _jsonl_row_count(path: Path) -> int:
    return sum(1 for _ in iter_jsonl(path))
