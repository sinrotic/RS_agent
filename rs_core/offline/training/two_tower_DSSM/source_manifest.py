from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json

SCHEMA_VERSION = "two_tower_dssm_source_index_v1"
EXPECTED_FIELDS = {
    "source": "two_tower_dssm",
    "canonical_source": "two_tower_dssm",
    "source_name": "two_tower_dssm",
    "variant": "dssm",
    "model_type": "dssm_two_tower_v1",
}
ALLOWED_INDEX_SCOPES = {"RECENT_2Y_DERIVED_INDEX", "FULL_DERIVED_INDEX"}
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


def validate_two_tower_dssm_source_index_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    if manifest_path.name not in {"source_index_manifest.json", "source_index_manifest.json.tmp"}:
        raise ValueError("two_tower_dssm direct eval requires source_index_manifest.json")
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("invalid two_tower_dssm source_index_manifest schema_version")
    for field, expected in EXPECTED_FIELDS.items():
        actual = manifest.get(field)
        if actual != expected:
            raise ValueError(f"invalid two_tower_dssm source manifest {field}: {actual!r}")
    if manifest.get("index_scope") not in ALLOWED_INDEX_SCOPES:
        raise ValueError(f"invalid two_tower_dssm source manifest index_scope: {manifest.get('index_scope')!r}")
    if manifest.get("source_status") != SOURCE_STATUS:
        raise ValueError(f"invalid two_tower_dssm source manifest source_status: {manifest.get('source_status')!r}")
    for field, expected in GOVERNANCE_FIELDS.items():
        actual = manifest.get(field)
        if actual is not expected:
            raise ValueError(f"invalid two_tower_dssm source manifest {field}: {actual!r}")

    row_count = _positive_int(manifest, "row_count")
    embedding_row_count = _positive_int(manifest, "embedding_row_count")
    index_row_count = _positive_int(manifest, "index_row_count")
    if row_count != embedding_row_count or row_count != index_row_count:
        raise ValueError("two_tower_dssm source manifest row_count, embedding_row_count, and index_row_count must match")

    embedding_path = _resolve_required_path(manifest_path, manifest.get("embedding_path"), "embedding_path")
    index_path = _resolve_required_path(manifest_path, manifest.get("index_path"), "index_path")
    _reject_forbidden_path_references({"manifest_path": str(manifest_path), "manifest": manifest})
    embedding_dim = _validate_vector_rows(embedding_path, embedding_row_count, "embedding_path")
    index_dim = _validate_vector_rows(index_path, index_row_count, "index_path")
    if embedding_dim != index_dim:
        raise ValueError("embedding_path and index_path embedding dimensions must match")
    user_embedding_path = manifest.get("user_embedding_path")
    if user_embedding_path:
        resolved_user_embedding_path = _resolve_required_path(manifest_path, user_embedding_path, "user_embedding_path")
        expected_user_count = _required_non_negative_int(manifest, "user_embedding_row_count")
        _validate_user_vector_rows(resolved_user_embedding_path, embedding_dim, expected_user_count, "user_embedding_path")

    item_vocab_manifest_path = manifest.get("item_vocab_manifest")
    if item_vocab_manifest_path:
        item_vocab_manifest = read_json(_resolve_required_path(manifest_path, item_vocab_manifest_path, "item_vocab_manifest"))
        _reject_forbidden_path_references({"item_vocab_manifest": item_vocab_manifest})
        source_paths = item_vocab_manifest.get("source_paths", {}) if isinstance(item_vocab_manifest.get("source_paths"), dict) else {}
        canonical_train = source_paths.get("canonical_interactions_train")
        if canonical_train and Path(str(canonical_train)).name != "canonical_interactions.train.jsonl":
            raise ValueError("item vocab canonical_interactions_train must be canonical_interactions.train.jsonl")
        item_count = item_vocab_manifest.get("item_count")
        if item_count is not None and int(item_count) != row_count:
            raise ValueError("item vocab item_count must match source index row_count")
        item_vocab_path = item_vocab_manifest.get("item_vocab_path")
        if item_vocab_path:
            resolved_vocab_path = _resolve_required_path(manifest_path, item_vocab_path, "item_vocab_path")
            if _jsonl_row_count(resolved_vocab_path) != row_count:
                raise ValueError("item vocab row count must match source index row_count")
    return manifest


def is_two_tower_dssm_source_index_manifest(path: str | Path) -> bool:
    return Path(path).name == "source_index_manifest.json"


def _positive_int(manifest: dict[str, Any], key: str) -> int:
    try:
        value = int(manifest.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{key} must be a positive integer")
    return value


def _required_non_negative_int(manifest: dict[str, Any], key: str) -> int:
    if key not in manifest or manifest.get(key) is None:
        raise ValueError(f"{key} must be provided when user_embedding_path is set")
    try:
        value = int(manifest.get(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a non-negative integer") from exc
    if value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _validate_vector_rows(path: Path, expected_count: int, key: str) -> int:
    row_count = 0
    embedding_dim: int | None = None
    for row_number, row in enumerate(iter_jsonl(path), start=1):
        row_count += 1
        item_id = str(row.get("parent_asin") or row.get("item_id") or "")
        if not item_id:
            raise ValueError(f"{key} row {row_number} missing item id")
        embedding = _validated_embedding(row.get("embedding"), key, row_number)
        if embedding_dim is None:
            embedding_dim = len(embedding)
        elif len(embedding) != embedding_dim:
            raise ValueError(f"{key} row {row_number} embedding dimension mismatch")
    if row_count != expected_count:
        raise ValueError(f"{key} row count does not match manifest row count")
    if embedding_dim is None:
        raise ValueError(f"{key} must contain at least one vector row")
    return embedding_dim


def _validate_user_vector_rows(path: Path, expected_dim: int, expected_count: int | None, key: str) -> None:
    row_count = 0
    for row_number, row in enumerate(iter_jsonl(path), start=1):
        row_count += 1
        user_id = str(row.get("user_id") or "")
        if not user_id:
            raise ValueError(f"{key} row {row_number} missing user_id")
        embedding = _validated_embedding(row.get("embedding"), key, row_number)
        if len(embedding) != expected_dim:
            raise ValueError(f"{key} row {row_number} embedding dimension mismatch")
    if expected_count is not None and row_count != expected_count:
        raise ValueError(f"{key} row count does not match manifest row count")


def _validated_embedding(raw_embedding: Any, key: str, row_number: int) -> list[float]:
    if not isinstance(raw_embedding, list) or not raw_embedding:
        raise ValueError(f"{key} row {row_number} missing embedding")
    try:
        embedding = [float(value) for value in raw_embedding]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} row {row_number} has invalid embedding") from exc
    if any(not math.isfinite(value) for value in embedding):
        raise ValueError(f"{key} row {row_number} has non-finite embedding")
    return embedding


def _resolve_required_path(manifest_path: Path, value: Any, key: str) -> Path:
    if not value:
        raise ValueError(f"two_tower_dssm source manifest missing {key}")
    path = Path(str(value))
    resolved = path if path.is_absolute() else manifest_path.parent / path
    resolved = resolved.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    if _is_forbidden_path(resolved):
        raise ValueError(f"forbidden two_tower_dssm source path for {key}: {resolved}")
    return resolved


def _reject_forbidden_path_references(value: Any) -> None:
    matches = []
    for text in _walk_strings(value):
        if _looks_like_path(text) and _is_forbidden_path(Path(text)):
            matches.append(text)
    if matches:
        raise ValueError(f"forbidden two_tower_dssm source path references: {sorted(set(matches))}")


def _is_forbidden_path(path: Path) -> bool:
    parts = [part.lower() for part in path.parts]
    in_pytest_tmp = False
    for part in parts:
        if part.startswith("pytest-") or part.startswith("pytest_of_") or part.startswith("pytest-of-"):
            in_pytest_tmp = True
            continue
        tokens = {token for token in part.replace("-", "_").replace(".", "_").split("_") if token}
        if tokens & FORBIDDEN_PATH_TOKENS:
            if in_pytest_tmp and part.startswith("test_"):
                continue
            return True
    return False


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
