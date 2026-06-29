from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rs_core.common.milvus_config import (
    merge_milvus_config as merge_milvus_config,
    milvus_config_from_args as milvus_config_from_args,
    milvus_config_from_env as milvus_config_from_env,
)
from rs_core.data.contracts import StorageConnectionContract


def _public_error(exc: Exception) -> dict[str, str]:
    return {"error_type": type(exc).__name__}


def _public_config_ref(config_ref: str) -> str:
    if not config_ref or config_ref.startswith("env:") or config_ref == "project_root":
        return config_ref
    return "configured"


@dataclass(frozen=True)
class StorageClientHandle:
    """Lazy infrastructure client handle managed by the data module."""

    contract: StorageConnectionContract
    client: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = self.contract.to_dict()
        payload["client_bound"] = self.client is not None
        return payload

    def readiness(self) -> dict[str, Any]:
        if self.contract.metadata.get("enabled") is False:
            return _adapter_readiness(
                self.contract,
                status="disabled",
                reason="adapter_disabled",
                client_bound=self.client is not None,
            )
        if self.client is None:
            return _adapter_readiness(
                self.contract,
                status="degraded",
                reason="client_unbound",
                client_bound=False,
            )
        return _adapter_readiness(self.contract, status="ok", client_bound=True)


@dataclass
class LocalFileAdapter:
    root: Path = field(default_factory=lambda: Path.cwd())
    enabled: bool = True

    def contract(self, name: str = "local_files") -> StorageConnectionContract:
        return StorageConnectionContract(
            name=name,
            backend="local_file",
            read_only=True,
            config_ref="project_root",
            metadata={"enabled": self.enabled, "root_ref": "project_root"},
        )

    def readiness(self) -> dict[str, Any]:
        contract = self.contract()
        if not self.enabled:
            return _adapter_readiness(contract, status="disabled", reason="adapter_disabled", client_bound=False)
        try:
            exists = self.root.exists()
        except OSError as exc:
            return _adapter_readiness(
                contract,
                status="degraded",
                reason="root_check_failed",
                client_bound=False,
                error=_public_error(exc),
            )
        return _adapter_readiness(
            contract,
            status="ok" if exists else "degraded",
            reason="root_missing" if not exists else "ready",
            client_bound=False,
        )

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else self.root / candidate


@dataclass
class MysqlAdapter:
    config_ref: str = "env:RS_MYSQL_*"
    store: Any | None = None
    enabled: bool = False

    def handle(self) -> StorageClientHandle:
        return StorageClientHandle(
            StorageConnectionContract(
                name="mysql_dataset",
                backend="mysql_dataset",
                read_only=True,
                config_ref=self.config_ref,
                metadata={"enabled": self.enabled},
            ),
            self.store,
        )

    def readiness(self) -> dict[str, Any]:
        handle = self.handle()
        if not self.enabled:
            return handle.readiness()
        if self.store is None:
            return _adapter_readiness(
                handle.contract,
                status="degraded",
                reason="client_unbound",
                client_bound=False,
            )
        try:
            health = self.store.health()
        except Exception as exc:
            return _adapter_readiness(
                handle.contract,
                status="degraded",
                reason="health_failed",
                client_bound=True,
                error=_public_error(exc),
            )
        status = str(health.get("status") or "degraded")
        enabled = health.get("enabled", self.enabled)
        reason = str(health.get("reason") or ("ready" if status == "ok" else status))
        return _adapter_readiness(
            handle.contract,
            status="disabled" if enabled is False else status,
            reason="adapter_disabled" if enabled is False else reason,
            client_bound=True,
            enabled=bool(enabled),
        )


@dataclass
class RedisAdapter:
    config_ref: str = "env:RS_REDIS_URL"
    client: Any | None = None
    enabled: bool = False

    def handle(self) -> StorageClientHandle:
        return StorageClientHandle(
            StorageConnectionContract(
                name="redis",
                backend="redis",
                read_only=False,
                config_ref=self.config_ref,
                metadata={"enabled": self.enabled},
            ),
            self.client,
        )

    def readiness(self) -> dict[str, Any]:
        return self.handle().readiness()


@dataclass
class MinioAdapter:
    config_ref: str = "env:RS_MINIO_*"
    client: Any | None = None
    enabled: bool = False

    def handle(self) -> StorageClientHandle:
        return StorageClientHandle(
            StorageConnectionContract(
                name="minio",
                backend="minio",
                read_only=False,
                config_ref=self.config_ref,
                metadata={"enabled": self.enabled},
            ),
            self.client,
        )

    def readiness(self) -> dict[str, Any]:
        return self.handle().readiness()


@dataclass
class MilvusAdapter:
    config_ref: str = "env:RS_MILVUS_*"
    client: Any | None = None
    enabled: bool = False
    config: Mapping[str, Any] | None = None

    @classmethod
    def from_config(
        cls,
        config: Mapping[str, Any] | None,
        *,
        enabled: bool | None = None,
        config_ref: str = "env:RS_MILVUS_*",
    ) -> "MilvusAdapter":
        effective_config = dict(config or {})
        return cls(
            config_ref=config_ref,
            enabled=bool(effective_config.get("enabled", False) if enabled is None else enabled),
            config=effective_config,
        )

    def connection_config(self) -> dict[str, Any]:
        return merge_milvus_config(milvus_config_from_env(), self.config)

    def handle(self) -> StorageClientHandle:
        return StorageClientHandle(
            StorageConnectionContract(
                name="milvus",
                backend="milvus",
                read_only=True,
                config_ref=self.config_ref,
                metadata={"enabled": self.enabled, "managed_by": "MilvusAdapter"},
            ),
            self.client,
        )

    def readiness(self) -> dict[str, Any]:
        return self.handle().readiness()

    def build_vector_store(self) -> Any:
        from rs_core.recsys.vectorstores.milvus_client import MilvusVectorStore

        return MilvusVectorStore.from_config(self.connection_config())


def _adapter_readiness(
    contract: StorageConnectionContract,
    *,
    status: str,
    reason: str = "ready",
    client_bound: bool,
    error: dict[str, str] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": contract.name,
        "backend": contract.backend,
        "enabled": contract.metadata.get("enabled", True) if enabled is None else enabled,
        "status": status,
        "reason": reason,
        "read_only": contract.read_only,
        "config_ref": _public_config_ref(contract.config_ref),
        "client_bound": client_bound,
    }
    if error:
        payload.update(error)
    return payload


__all__ = [
    "StorageClientHandle",
    "LocalFileAdapter",
    "MysqlAdapter",
    "RedisAdapter",
    "MinioAdapter",
    "MilvusAdapter",
    "merge_milvus_config",
    "milvus_config_from_args",
    "milvus_config_from_env",
]
