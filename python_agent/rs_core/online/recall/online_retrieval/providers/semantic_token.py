from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rs_core.online.recall.candidate_merge import semantic_candidates_for_user
from rs_core.online.recall.online_retrieval.config import provider_enabled
from rs_core.online.recall.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest


@dataclass
class SemanticTokenProvider:
    config: dict[str, Any]
    semantic_index: dict[str, dict[str, Any]] | None = None
    enabled: bool = True
    name: str = "semantic_token"
    role: str = "semantic_token_recall"
    source_name: str = "semantic"

    @classmethod
    def from_config(cls, provider_config: dict[str, Any], semantic_index: dict[str, dict[str, Any]] | None = None) -> "SemanticTokenProvider":
        return cls(config=dict(provider_config), semantic_index=semantic_index, enabled=provider_enabled(provider_config))

    def readiness(self) -> ProviderReadiness:
        if not self.enabled:
            return ProviderReadiness(self.name, False, False, "disabled", self.role, backend="local_semantic_index", source_name=self.source_name)
        if not self.semantic_index:
            return ProviderReadiness(self.name, True, False, "missing_semantic_index", self.role, backend="local_semantic_index", source_name=self.source_name)
        return ProviderReadiness(self.name, True, True, "ready", self.role, backend="local_semantic_index", source_name=self.source_name, diagnostics={"semantic_index_size": len(self.semantic_index)})

    def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        ready = self.readiness()
        if not ready.available:
            return ProviderResult(
                self.name,
                self.source_name,
                self.role,
                candidates=[],
                available=ready.available,
                status=ready.status,
                diagnostics=self._diagnostics({}, 0),
            )
        merged_config = dict(request.config)
        merged_config.update(self.config)
        merged_config["semantic_enabled"] = True
        candidates = semantic_candidates_for_user(request.user_sequence, self.semantic_index or {}, merged_config)
        return ProviderResult(
            self.name,
            self.source_name,
            self.role,
            candidates=candidates,
            available=True,
            status="ok" if candidates else "empty",
            diagnostics=self._diagnostics(merged_config, len(candidates)),
        )

    def _diagnostics(self, config: dict[str, Any], candidate_count: int) -> dict[str, Any]:
        source = config or self.config
        return {
            "semantic_score_mode": source.get("semantic_score_mode"),
            "semantic_seed_window": source.get("semantic_seed_window"),
            "semantic_per_seed": source.get("semantic_per_seed"),
            "semantic_per_user": source.get("semantic_per_user"),
            "semantic_min_overlap": source.get("semantic_min_overlap"),
            "semantic_max_df_ratio": source.get("semantic_max_df_ratio"),
            "semantic_index_size": len(self.semantic_index or {}),
            "candidate_count": candidate_count,
        }
