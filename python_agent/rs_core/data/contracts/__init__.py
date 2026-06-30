from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DatasetContract:
    name: str
    split: str = "train"
    path: str = ""
    schema_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactPathContract:
    artifact_id: str
    uri: str
    kind: str = "generic"
    checksum: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FeatureSchemaContract:
    name: str
    columns: dict[str, str] = field(default_factory=dict)
    version: str = "v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidatePoolContract:
    pool_id: str
    item_ids: list[str] = field(default_factory=list)
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KnowledgeChunkContract:
    chunk_id: str
    item_id: str = ""
    text: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StorageConnectionContract:
    name: str
    backend: str
    read_only: bool = True
    config_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataAdapterContract:
    adapter_id: str
    backend: str
    resource_ref: str = ""
    connection_ref: str = ""
    read_only: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactManifestContract:
    manifest_id: str
    artifacts: list[ArtifactPathContract] = field(default_factory=list)
    current_route: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = [artifact.to_dict() for artifact in self.artifacts]
        return payload


__all__ = [
    "DatasetContract",
    "ArtifactPathContract",
    "FeatureSchemaContract",
    "CandidatePoolContract",
    "KnowledgeChunkContract",
    "StorageConnectionContract",
    "DataAdapterContract",
    "ArtifactManifestContract",
]
