from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rs_core.artifacts.manifest import file_digest


@dataclass(frozen=True)
class ArtifactReference:
    scheme: str
    bucket: str | None
    object_name: str | None
    local_path: Path | None


@dataclass(frozen=True)
class ResolveResult:
    path: Path | None
    diagnostics: dict[str, Any]
    fallback_used: bool = False
    fallback_reason: str | None = None


class ArtifactResolveError(RuntimeError):
    pass


def parse_artifact_uri(uri: str) -> ArtifactReference:
    parsed = urlparse(uri)
    if parsed.scheme in ("s3", "minio"):
        object_name = parsed.path.lstrip("/")
        if not parsed.netloc or not object_name:
            raise ValueError(f"Invalid {parsed.scheme} artifact URI")
        return ArtifactReference(parsed.scheme, parsed.netloc, object_name, None)
    if parsed.scheme == "file":
        return ArtifactReference("file", None, None, Path(parsed.path))
    if parsed.scheme and not (len(parsed.scheme) == 1 and ":" in uri):
        raise ValueError(f"Unsupported artifact URI scheme: {parsed.scheme}")
    return ArtifactReference("local", None, None, Path(uri))


def resolve_artifact(
    uri: str,
    *,
    cache_dir: str | Path | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    client: Any | None = None,
    endpoint: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    secure: bool = False,
    allow_local_fallback: bool = False,
    local_fallback_path: str | Path | None = None,
) -> ResolveResult:
    ref = parse_artifact_uri(uri)
    diagnostics: dict[str, Any] = {"uri_scheme": ref.scheme, "cache_hit": False}
    try:
        if ref.scheme in ("local", "file"):
            path = ref.local_path
            if path is None:
                raise ArtifactResolveError("Local artifact path is missing")
            _verify_file(path, sha256=sha256, size_bytes=size_bytes)
            diagnostics.update({"resolved_from": "local", "path": str(path)})
            return ResolveResult(path=path, diagnostics=diagnostics)
        path = _resolve_remote(
            ref,
            cache_dir=Path(cache_dir) if cache_dir is not None else Path(".cache") / "rs_artifacts",
            sha256=sha256,
            size_bytes=size_bytes,
            client=client,
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            diagnostics=diagnostics,
        )
        return ResolveResult(path=path, diagnostics=diagnostics)
    except Exception as exc:
        if allow_local_fallback and local_fallback_path:
            fallback_path = Path(local_fallback_path)
            _verify_file(fallback_path, sha256=sha256, size_bytes=size_bytes)
            reason = _safe_error(exc)
            diagnostics.update({"resolved_from": "local_fallback", "path": str(fallback_path)})
            return ResolveResult(
                path=fallback_path,
                diagnostics=diagnostics,
                fallback_used=True,
                fallback_reason=reason,
            )
        if isinstance(exc, ArtifactResolveError):
            raise
        raise ArtifactResolveError(_safe_error(exc)) from exc


def _resolve_remote(
    ref: ArtifactReference,
    *,
    cache_dir: Path,
    sha256: str | None,
    size_bytes: int | None,
    client: Any | None,
    endpoint: str | None,
    access_key: str | None,
    secret_key: str | None,
    secure: bool,
    diagnostics: dict[str, Any],
) -> Path:
    if not ref.bucket or not ref.object_name:
        raise ArtifactResolveError("Remote artifact URI is missing bucket or object name")
    cache_path = cache_dir / ref.bucket / ref.object_name
    if cache_path.exists():
        _verify_file(cache_path, sha256=sha256, size_bytes=size_bytes)
        diagnostics.update({"cache_hit": True, "resolved_from": "cache", "path": str(cache_path)})
        return cache_path
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    remote_client = client or _build_minio_client(endpoint, access_key, secret_key, secure)
    try:
        remote_client.fget_object(ref.bucket, ref.object_name, str(cache_path))
    except AttributeError as exc:
        raise ArtifactResolveError("MinIO client must provide fget_object(bucket, object_name, file_path)") from exc
    except Exception as exc:
        if cache_path.exists():
            cache_path.unlink()
        raise ArtifactResolveError(_safe_error(exc)) from exc
    _verify_file(cache_path, sha256=sha256, size_bytes=size_bytes)
    diagnostics.update({"resolved_from": ref.scheme, "path": str(cache_path)})
    return cache_path


def _build_minio_client(
    endpoint: str | None,
    access_key: str | None,
    secret_key: str | None,
    secure: bool,
) -> Any:
    if not endpoint:
        raise ArtifactResolveError("MinIO endpoint is required for remote artifact resolution")
    if not access_key or not secret_key:
        raise ArtifactResolveError("MinIO credentials are required for remote artifact resolution")
    try:
        from minio import Minio
    except ImportError as exc:
        raise ArtifactResolveError("MinIO SDK is not installed; install optional dependency rs-agent[artifacts]") from exc
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


def _verify_file(path: Path, *, sha256: str | None, size_bytes: int | None) -> None:
    if not path.exists():
        raise ArtifactResolveError(f"Artifact file does not exist: {path}")
    observed = file_digest(path)
    if sha256 and observed["sha256"] != sha256:
        raise ArtifactResolveError("Artifact sha256 mismatch")
    if size_bytes is not None and observed["size_bytes"] != size_bytes:
        raise ArtifactResolveError("Artifact size mismatch")


def _safe_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    for marker in ("secret_key=", "access_key=", "password="):
        if marker in text:
            return exc.__class__.__name__
    return text


def copy_to_cache(source: str | Path, cache_path: str | Path) -> Path:
    target = Path(cache_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
