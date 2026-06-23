from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rs_core.recsys.candidate_merge import load_two_tower_index, two_tower_candidates_for_user
from rs_core.recsys.online_retrieval.config import clamp_int, provider_enabled, resolve_project_path
from rs_core.recsys.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest
from rs_core.recsys.vectorstores.qdrant_client import QdrantVectorStore
from rs_core.recsys.vectorstores.qdrant_contracts import DEFAULT_TWO_TOWER_COLLECTION
from rs_core.recsys.vectorstores.qdrant_two_tower import QdrantTwoTowerIndex


@dataclass
class QdrantTwoTowerProvider:
    manifest_path: Path | None
    config: dict[str, Any]
    enabled: bool = True
    name: str = "two_tower_qdrant"
    role: str = "primary_vector_recall"
    source_name: str = "two_tower"
    _index: Any | None = None

    @classmethod
    def from_config(cls, provider_config: dict[str, Any], *, config_path: str | None = None) -> "QdrantTwoTowerProvider":
        raw_path = provider_config.get("manifest_path") or provider_config.get("path") or provider_config.get("source_index_manifest")
        return cls(manifest_path=resolve_project_path(raw_path, config_path), config=dict(provider_config), enabled=provider_enabled(provider_config))

    def readiness(self) -> ProviderReadiness:
        if not self.enabled:
            return ProviderReadiness(self.name, False, False, "disabled", self.role, backend="qdrant", source_name=self.source_name)
        if self.manifest_path is None:
            return ProviderReadiness(self.name, True, False, "missing_manifest_path", self.role, backend="qdrant", source_name=self.source_name)
        if not self.manifest_path.exists():
            return ProviderReadiness(self.name, True, False, "missing_manifest", self.role, backend="qdrant", source_name=self.source_name)
        qdrant = self._qdrant_config()
        if not qdrant.get("enabled", False):
            return ProviderReadiness(self.name, True, False, "qdrant_disabled", self.role, backend="qdrant", source_name=self.source_name)
        if not _qdrant_target_configured(qdrant):
            return ProviderReadiness(self.name, True, False, "qdrant_target_missing", self.role, backend="qdrant", source_name=self.source_name)
        return ProviderReadiness(self.name, True, True, "configured", self.role, backend="qdrant", source_name=self.source_name)

    def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        ready = self.readiness()
        if not ready.available:
            return ProviderResult(self.name, self.source_name, self.role, available=False, status=ready.status)
        try:
            source_config = dict(request.config) | {
                "two_tower_enabled": True,
                "two_tower_per_user": clamp_int(self.config.get("per_user", request.candidate_pool_size), request.candidate_pool_size, maximum=request.candidate_pool_size),
            }
            candidates = two_tower_candidates_for_user(request.user_sequence, self._get_index(), source_config)
        except Exception as exc:
            return ProviderResult(self.name, self.source_name, self.role, available=False, status="degraded", diagnostics={"error_type": type(exc).__name__})
        return ProviderResult(self.name, self.source_name, self.role, candidates=candidates, available=True, status="ok")

    def _get_index(self) -> Any:
        if self._index is not None:
            return self._index
        if self.manifest_path is None:
            raise ValueError("two_tower manifest_path is not configured")
        local_index = load_two_tower_index(self.manifest_path)
        qdrant = self._qdrant_config()
        self._index = QdrantTwoTowerIndex(
            store=QdrantVectorStore.from_config(qdrant),
            collection_name=str(qdrant.get("collection_name") or DEFAULT_TWO_TOWER_COLLECTION),
            items=dict(getattr(local_index, "items", {}) or {}),
            user_embeddings=dict(getattr(local_index, "user_embeddings", {}) or {}),
            source_name=str(getattr(local_index, "source_name", self.source_name) or self.source_name),
            model_metadata=dict(getattr(local_index, "model_metadata", {}) or {}),
        )
        return self._index

    def _qdrant_config(self) -> dict[str, Any]:
        qdrant = self.config.get("qdrant") if isinstance(self.config.get("qdrant"), dict) else {}
        return dict(qdrant)


def _qdrant_target_configured(qdrant: dict[str, Any]) -> bool:
    return any(qdrant.get(key) not in (None, "") for key in ("location", "path", "url", "host"))
