from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rs_core.online.recall.online_retrieval.config import provider_enabled
from rs_core.online.recall.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest


@dataclass
class SemanticVectorProvider:
    config: dict[str, Any]
    enabled: bool = False
    name: str = "semantic_vector"
    role: str = "semantic_candidate_recall"
    source_name: str = "semantic_vector"

    @classmethod
    def from_config(cls, provider_config: dict[str, Any]) -> "SemanticVectorProvider":
        return cls(config=dict(provider_config), enabled=provider_enabled(provider_config) and bool(provider_config.get("enabled", False)))

    def readiness(self) -> ProviderReadiness:
        collection = str(self.config.get("collection_name") or "")
        if collection == "rs_agent_rag_chunks_v1" or "rag_chunks" in collection:
            return ProviderReadiness(self.name, self.enabled, False, "governance_error", self.role, backend="vector", source_name=self.source_name, diagnostics={"reason": "rag_chunks_not_candidate_generation_source"})
        if not self.enabled:
            return ProviderReadiness(self.name, False, False, "disabled", self.role, backend="vector", source_name=self.source_name)
        return ProviderReadiness(self.name, True, False, "skeleton_not_implemented", self.role, backend="vector", source_name=self.source_name)

    def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        ready = self.readiness()
        return ProviderResult(self.name, self.source_name, self.role, candidates=[], available=ready.available, status=ready.status, diagnostics={"reason": ready.diagnostics.get("reason", "semantic_vector_skeleton")})
