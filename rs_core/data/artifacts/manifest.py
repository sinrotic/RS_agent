from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_PUBLIC_ARTIFACT_STORE_KEYS = {
    "storage_backend",
    "artifact_uri",
    "minio_uri",
    "sha256",
    "size_bytes",
    "cache_policy",
    "uploaded_at",
}


def read_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    text = manifest_path.read_text(encoding="utf-8")
    if manifest_path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError(f"Manifest must be a mapping: {manifest_path}")
    return payload


def write_manifest(path: str | Path, payload: dict[str, Any]) -> None:
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.suffix.lower() == ".json":
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        manifest_path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def public_safe_status(manifest: dict[str, Any]) -> dict[str, Any]:
    store = manifest.get("artifact_store")
    safe_store = {
        key: value
        for key, value in (store if isinstance(store, dict) else {}).items()
        if key in _PUBLIC_ARTIFACT_STORE_KEYS
    }
    return {
        "schema_version": manifest.get("schema_version"),
        "artifact_id": manifest.get("artifact_id"),
        "artifact_type": manifest.get("artifact_type"),
        "stage": manifest.get("stage"),
        "artifact_store": safe_store,
    }


def file_digest(path: str | Path, chunk_size: int = 1024 * 1024) -> dict[str, Any]:
    artifact_path = Path(path)
    digest = hashlib.sha256()
    size = 0
    with artifact_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            size += len(chunk)
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def find_local_artifact_path(manifest: dict[str, Any]) -> str | None:
    store = manifest.get("artifact_store")
    if isinstance(store, dict) and store.get("local_path"):
        return str(store["local_path"])
    for key in ("path", "model_path", "bm25_index_path", "artifact_report_path"):
        if manifest.get(key):
            return str(manifest[key])
    return None


def build_artifact_store_patch(
    manifest: dict[str, Any],
    *,
    local_path: str | Path | None = None,
    bucket: str | None = None,
    object_name: str | None = None,
    minio_uri: str | None = None,
    artifact_uri: str | None = None,
    storage_backend: str = "minio",
    cache_policy: str = "local_trial_cache",
    uploaded_at: str | None = None,
    compute_hash: bool = True,
) -> dict[str, Any]:
    chosen_local_path = str(local_path) if local_path is not None else find_local_artifact_path(manifest)
    patch: dict[str, Any] = {
        "storage_backend": storage_backend,
        "local_path": chosen_local_path,
        "artifact_uri": artifact_uri,
        "minio_uri": minio_uri,
        "sha256": None,
        "size_bytes": None,
        "cache_policy": cache_policy,
        "uploaded_at": uploaded_at,
    }
    if minio_uri is None and bucket and object_name:
        patch["minio_uri"] = f"minio://{bucket}/{object_name.lstrip('/')}"
    if artifact_uri is None:
        patch["artifact_uri"] = patch["minio_uri"] or chosen_local_path
    if compute_hash and chosen_local_path and Path(chosen_local_path).exists():
        patch.update(file_digest(chosen_local_path))
    return {"artifact_store": patch}


def apply_artifact_store_patch(manifest: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    updated = dict(manifest)
    current_store = updated.get("artifact_store") if isinstance(updated.get("artifact_store"), dict) else {}
    updated["artifact_store"] = {**current_store, **patch.get("artifact_store", {})}
    return updated


def uploaded_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
