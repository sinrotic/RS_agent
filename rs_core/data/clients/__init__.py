from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rs_core.common.io import iter_jsonl, read_json
from rs_core.data.contracts import (
    ArtifactManifestContract,
    ArtifactPathContract,
    CandidatePoolContract,
    DataAdapterContract,
    DatasetContract,
    FeatureSchemaContract,
    KnowledgeChunkContract,
)


@dataclass
class DataClient:
    """Business-semantic data access facade for online/offline/agent modules."""

    project_root: Path = field(default_factory=lambda: Path.cwd())

    def resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else self.project_root / candidate

    def read_json(self, path: str | Path) -> dict[str, Any]:
        return read_json(self.resolve_path(path))

    def read_jsonl(self, path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in iter_jsonl(self.resolve_path(path)):
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
        return rows


@dataclass
class FeatureClient:
    data_client: DataClient = field(default_factory=DataClient)

    def get_feature_rows(self, path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.data_client.read_jsonl(path, limit=limit)

    def schema(self, name: str, columns: dict[str, str], version: str = "v1") -> FeatureSchemaContract:
        return FeatureSchemaContract(name=name, columns=dict(columns), version=version)

    def feature_view_contract(
        self,
        name: str,
        columns: dict[str, str],
        *,
        version: str = "v1",
        source: str = "",
    ) -> dict[str, Any]:
        return {"schema": self.schema(name, columns, version).to_dict(), "source": source, "client": "FeatureClient"}


@dataclass
class ArtifactClient:
    data_client: DataClient = field(default_factory=DataClient)

    def artifact(
        self,
        artifact_id: str,
        uri: str,
        kind: str = "generic",
        *,
        checksum: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactPathContract:
        return ArtifactPathContract(
            artifact_id=artifact_id,
            uri=str(self.data_client.resolve_path(uri)),
            kind=kind,
            checksum=checksum,
            metadata=metadata or {},
        )

    def manifest(
        self,
        manifest_id: str,
        artifacts: list[ArtifactPathContract],
        *,
        current_route: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactManifestContract:
        return ArtifactManifestContract(
            manifest_id=manifest_id,
            artifacts=artifacts,
            current_route=current_route,
            metadata=metadata or {},
        )

    def read_json_artifact(self, artifact_id: str, uri: str | Path, kind: str = "generic") -> dict[str, Any]:
        artifact = self.artifact(artifact_id, str(uri), kind)
        return self.data_client.read_json(artifact.uri)


@dataclass
class DatasetClient:
    data_client: DataClient = field(default_factory=DataClient)

    def dataset(
        self,
        name: str,
        path: str | Path,
        split: str = "train",
        *,
        schema_ref: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DatasetContract:
        return DatasetContract(
            name=name,
            split=split,
            path=str(self.data_client.resolve_path(path)),
            schema_ref=schema_ref,
            metadata=metadata or {},
        )

    def manifest(
        self,
        name: str,
        path: str | Path,
        *,
        split: str = "train",
        window: str = "",
        freshness: str = "",
    ) -> dict[str, Any]:
        metadata = {key: value for key, value in {"window": window, "freshness": freshness}.items() if value}
        return self.dataset(name, path, split=split, metadata=metadata).to_dict()


@dataclass
class KnowledgeDataClient:
    data_client: DataClient = field(default_factory=DataClient)

    def chunks_from_jsonl(self, path: str | Path, *, limit: int | None = None) -> list[KnowledgeChunkContract]:
        chunks: list[KnowledgeChunkContract] = []
        for index, row in enumerate(self.data_client.read_jsonl(path, limit=limit), start=1):
            chunks.append(KnowledgeChunkContract(
                chunk_id=str(row.get("chunk_id") or f"chunk-{index}"),
                item_id=str(row.get("item_id") or row.get("parent_asin") or ""),
                text=str(row.get("text") or row.get("description") or row.get("title") or ""),
                source=str(path),
                metadata={key: value for key, value in row.items() if key not in {"chunk_id", "item_id", "parent_asin", "text"}},
            ))
        return chunks

    def local_rag_index_adapter_contract(
        self,
        artifact_id: str,
        uri: str | Path,
        *,
        backend: str = "sqlite_bm25",
        role: str = "rag_evidence",
        metadata: dict[str, Any] | None = None,
    ) -> DataAdapterContract:
        resolved_uri = str(self.data_client.resolve_path(uri))
        return DataAdapterContract(
            adapter_id=artifact_id,
            backend=backend,
            resource_ref=resolved_uri,
            connection_ref="local_file",
            metadata={"role": role, **(metadata or {})},
        )

    def local_rag_index_artifact(
        self,
        artifact_id: str,
        uri: str | Path,
        *,
        backend: str = "sqlite_bm25",
        role: str = "rag_evidence",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactPathContract:
        adapter_contract = self.local_rag_index_adapter_contract(
            artifact_id,
            uri,
            backend=backend,
            role=role,
            metadata=metadata,
        )
        return ArtifactPathContract(
            artifact_id=artifact_id,
            uri=adapter_contract.resource_ref,
            kind="rag_index",
            metadata={
                "backend": backend,
                "role": role,
                **(metadata or {}),
                "adapter_contract": adapter_contract.to_dict(),
            },
        )

    def elasticsearch_rag_index_adapter_contract(
        self,
        index_name: str,
        *,
        role: str = "rag_evidence",
        connection_ref: str = "env:RS_ELASTICSEARCH_*",
        metadata: dict[str, Any] | None = None,
    ) -> DataAdapterContract:
        return DataAdapterContract(
            adapter_id=str(index_name),
            backend="elasticsearch_bm25",
            resource_ref=f"elasticsearch://{index_name}",
            connection_ref=connection_ref,
            metadata={"role": role, **(metadata or {})},
        )

    def elasticsearch_rag_index_artifact(
        self,
        index_name: str,
        *,
        role: str = "rag_evidence",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactPathContract:
        adapter_contract = self.elasticsearch_rag_index_adapter_contract(
            index_name,
            role=role,
            metadata=metadata,
        )
        return ArtifactPathContract(
            artifact_id=str(index_name),
            uri=adapter_contract.resource_ref,
            kind="rag_lexical_index",
            metadata={
                "backend": "elasticsearch_bm25",
                "role": role,
                **(metadata or {}),
                "adapter_contract": adapter_contract.to_dict(),
            },
        )

    def milvus_rag_collection_adapter_contract(
        self,
        collection_name: str,
        *,
        role: str = "rag_evidence",
        connection_ref: str = "env:RS_MILVUS_*",
        metadata: dict[str, Any] | None = None,
    ) -> DataAdapterContract:
        return DataAdapterContract(
            adapter_id=collection_name,
            backend="milvus",
            resource_ref=f"milvus://{collection_name}",
            connection_ref=connection_ref,
            metadata={"role": role, **(metadata or {})},
        )

    def milvus_rag_collection_artifact(
        self,
        collection_name: str,
        *,
        role: str = "rag_evidence",
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactPathContract:
        adapter_contract = self.milvus_rag_collection_adapter_contract(
            collection_name,
            role=role,
            metadata=metadata,
        )
        return ArtifactPathContract(
            artifact_id=collection_name,
            uri=adapter_contract.resource_ref,
            kind="rag_vector_collection",
            metadata={
                "backend": "milvus",
                "role": role,
                **(metadata or {}),
                "adapter_contract": adapter_contract.to_dict(),
            },
        )


@dataclass
class MemoryDataClient:
    data_client: DataClient = field(default_factory=DataClient)

    def session_memory_ref(self, session_id: str, *, backend_status: str = "") -> dict[str, str]:
        payload = {"session_id": session_id, "backend": "data-client-managed"}
        if backend_status:
            payload["backend_status"] = backend_status
        return payload


@dataclass
class CandidatePoolClient:
    data_client: DataClient = field(default_factory=DataClient)

    def from_item_ids(
        self,
        pool_id: str,
        item_ids: list[str],
        source: str = "manual",
        *,
        freshness: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> CandidatePoolContract:
        deduped_item_ids = list(dict.fromkeys(item_ids))
        return CandidatePoolContract(
            pool_id=pool_id,
            item_ids=deduped_item_ids,
            source=source,
            metadata={"size": len(deduped_item_ids), **({"freshness": freshness} if freshness else {}), **(metadata or {})},
        )


__all__ = [
    "DataClient",
    "FeatureClient",
    "ArtifactClient",
    "DatasetClient",
    "KnowledgeDataClient",
    "MemoryDataClient",
    "CandidatePoolClient",
]
