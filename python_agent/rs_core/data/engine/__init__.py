from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rs_core.data.adapters import LocalFileAdapter, MinioAdapter, MysqlAdapter, RedisAdapter
from rs_core.data.clients import (
    ArtifactClient,
    CandidatePoolClient,
    DataClient,
    DatasetClient,
    FeatureClient,
    KnowledgeDataClient,
    MemoryDataClient,
)


@dataclass
class DataAssetEngine:
    """Data asset orchestration entrypoint for worker/CLI callers."""

    data_client: DataClient = field(default_factory=DataClient)
    feature_client: FeatureClient | None = None
    artifact_client: ArtifactClient | None = None
    dataset_client: DatasetClient | None = None
    knowledge_client: KnowledgeDataClient | None = None
    memory_client: MemoryDataClient | None = None
    candidate_pool_client: CandidatePoolClient | None = None
    local_file_adapter: LocalFileAdapter | None = None
    mysql_adapter: MysqlAdapter | None = None
    redis_adapter: RedisAdapter | None = None
    minio_adapter: MinioAdapter | None = None

    def __post_init__(self) -> None:
        self.feature_client = self.feature_client or FeatureClient(self.data_client)
        self.artifact_client = self.artifact_client or ArtifactClient(self.data_client)
        self.dataset_client = self.dataset_client or DatasetClient(self.data_client)
        self.knowledge_client = self.knowledge_client or KnowledgeDataClient(self.data_client)
        self.memory_client = self.memory_client or MemoryDataClient(self.data_client)
        self.candidate_pool_client = self.candidate_pool_client or CandidatePoolClient(self.data_client)
        self.local_file_adapter = self.local_file_adapter or LocalFileAdapter(self.data_client.project_root)
        self.mysql_adapter = self.mysql_adapter or MysqlAdapter()
        self.redis_adapter = self.redis_adapter or RedisAdapter()
        self.minio_adapter = self.minio_adapter or MinioAdapter()

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "engine": "DataAssetEngine",
            "clients": ["data", "feature", "artifact", "dataset", "knowledge", "memory", "candidate_pool"],
            "storage": self.storage_connections(),
        }

    def readiness(self) -> dict[str, Any]:
        storage = self.storage_readiness()
        active_statuses = [payload["status"] for payload in storage.values() if payload.get("enabled") is not False]
        status = "ok" if active_statuses and all(value == "ok" for value in active_statuses) else "degraded"
        return {
            "status": status,
            "engine": "DataAssetEngine",
            "clients": ["data", "feature", "artifact", "dataset", "knowledge", "memory", "candidate_pool"],
            "storage": storage,
        }

    def storage_connections(self) -> dict[str, dict[str, Any]]:
        assert self.local_file_adapter is not None
        assert self.mysql_adapter is not None
        assert self.redis_adapter is not None
        assert self.minio_adapter is not None
        return {
            "local_file": self.local_file_adapter.contract().to_dict(),
            "mysql": self.mysql_adapter.handle().to_dict(),
            "redis": self.redis_adapter.handle().to_dict(),
            "minio": self.minio_adapter.handle().to_dict(),
        }

    def storage_readiness(self) -> dict[str, dict[str, Any]]:
        assert self.local_file_adapter is not None
        assert self.mysql_adapter is not None
        assert self.redis_adapter is not None
        assert self.minio_adapter is not None
        return {
            "local_file": self.local_file_adapter.readiness(),
            "mysql": self.mysql_adapter.readiness(),
            "redis": self.redis_adapter.readiness(),
            "minio": self.minio_adapter.readiness(),
        }

    def import_dataset(self, name: str, path: str | Path, split: str = "train") -> dict[str, Any]:
        assert self.dataset_client is not None
        return self.dataset_client.dataset(name, path, split=split).to_dict()

    def build_window_dataset(self, name: str, path: str | Path, *, window: str) -> dict[str, Any]:
        dataset = self.import_dataset(name, path, split="window")
        dataset.setdefault("metadata", {})["window"] = window
        return dataset

    def register_artifact(self, artifact_id: str, uri: str, kind: str = "generic") -> dict[str, Any]:
        assert self.artifact_client is not None
        return self.artifact_client.artifact(artifact_id, uri, kind).to_dict()

    def build_candidate_pool(self, pool_id: str, item_ids: list[str], source: str = "manual") -> dict[str, Any]:
        assert self.candidate_pool_client is not None
        return self.candidate_pool_client.from_item_ids(pool_id, item_ids, source).to_dict()

    def build_knowledge_chunks(self, path: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        assert self.knowledge_client is not None
        return [chunk.to_dict() for chunk in self.knowledge_client.chunks_from_jsonl(path, limit=limit)]


__all__ = ["DataAssetEngine"]
