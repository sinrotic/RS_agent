from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.data.artifacts.manifest import file_digest
from rs_core.data.artifacts.resolver import ArtifactResolveError, parse_artifact_uri, resolve_artifact

pytestmark = pytest.mark.unit


class FakeMinioClient:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.calls: list[tuple[str, str, str]] = []

    def fget_object(self, bucket: str, object_name: str, file_path: str) -> None:
        self.calls.append((bucket, object_name, file_path))
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.source.read_bytes())


def test_resolve_local_path_and_hash(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("local artifact", encoding="utf-8")
    digest = file_digest(artifact)

    result = resolve_artifact(str(artifact), sha256=digest["sha256"], size_bytes=digest["size_bytes"])

    assert result.path == artifact
    assert result.fallback_used is False
    assert result.diagnostics["resolved_from"] == "local"


def test_resolve_hash_mismatch_raises(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("local artifact", encoding="utf-8")

    with pytest.raises(ArtifactResolveError, match="sha256 mismatch"):
        resolve_artifact(str(artifact), sha256="0" * 64)


def test_minio_cache_hit_skips_client(tmp_path: Path) -> None:
    cached = tmp_path / "cache" / "bucket" / "models" / "artifact.bin"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cached")
    digest = file_digest(cached)
    client = FakeMinioClient(cached)

    result = resolve_artifact(
        "minio://bucket/models/artifact.bin",
        cache_dir=tmp_path / "cache",
        sha256=digest["sha256"],
        size_bytes=digest["size_bytes"],
        client=client,
    )

    assert result.path == cached
    assert result.diagnostics["cache_hit"] is True
    assert client.calls == []


def test_parse_minio_uri() -> None:
    ref = parse_artifact_uri("minio://bucket/path/to/file.json")

    assert ref.scheme == "minio"
    assert ref.bucket == "bucket"
    assert ref.object_name == "path/to/file.json"


def test_remote_failure_can_use_local_fallback(tmp_path: Path) -> None:
    fallback = tmp_path / "fallback.txt"
    fallback.write_text("fallback", encoding="utf-8")
    digest = file_digest(fallback)

    result = resolve_artifact(
        "minio://bucket/missing.txt",
        cache_dir=tmp_path / "cache",
        endpoint="127.0.0.1:9000",
        allow_local_fallback=True,
        local_fallback_path=fallback,
        sha256=digest["sha256"],
        size_bytes=digest["size_bytes"],
    )

    assert result.path == fallback
    assert result.fallback_used is True
    assert result.fallback_reason
