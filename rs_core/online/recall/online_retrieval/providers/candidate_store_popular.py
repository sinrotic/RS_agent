from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rs_core.online.recall.candidate_store.factory import build_candidate_store_from_env
from rs_core.online.recall.candidate_store.base import CandidateStore
from rs_core.online.recall.online_retrieval.config import clamp_int, provider_enabled
from rs_core.online.recall.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest


@dataclass
class CandidateStorePopularProvider:
    config: dict[str, Any]
    store: CandidateStore
    enabled: bool = True
    name: str = "candidate_store_popular"
    role: str = "online_popular_recall"
    source_name: str = "popular"

    @classmethod
    def from_config(cls, provider_config: dict[str, Any], *, provider_name: str | None = None) -> "CandidateStorePopularProvider":
        config = dict(provider_config)
        return cls(
            config=config,
            store=build_candidate_store_from_env(),
            enabled=provider_enabled(provider_config),
            name=provider_name or str(config.get("name", "candidate_store_popular")),
            role=str(config.get("role", "online_popular_recall")),
            source_name=str(config.get("source_name", "popular")),
        )

    def readiness(self) -> ProviderReadiness:
        if not self.enabled:
            return ProviderReadiness(self.name, False, False, "disabled", self.role, backend="candidate_store", source_name=self.source_name)
        health = self.store.health()
        available = bool(health.get("enabled")) and health.get("status") in {"ok", "ready"}
        return ProviderReadiness(self.name, True, available, str(health.get("status", "degraded")), self.role, backend=str(health.get("backend", "candidate_store")), source_name=self.source_name)

    def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        if not self.enabled:
            return ProviderResult(self.name, self.source_name, self.role, available=False, status="disabled")
        limit = clamp_int(self.config.get("limit"), request.candidate_pool_size, maximum=request.candidate_pool_size)
        candidates = self.store.popular_candidates(scope=str(self.config.get("scope", "global")), bucket=str(self.config.get("bucket", "")), limit=limit)
        return ProviderResult(self.name, self.source_name, self.role, candidates=candidates, available=bool(self.store.health().get("enabled")), status="ok" if candidates else "empty")
