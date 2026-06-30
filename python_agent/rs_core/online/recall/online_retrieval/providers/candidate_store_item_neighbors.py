from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rs_core.online.recall.candidate_store.factory import build_candidate_store_from_env
from rs_core.online.recall.candidate_store.base import CandidateStore
from rs_core.online.recall.online_retrieval.config import clamp_int, provider_enabled
from rs_core.online.recall.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest


@dataclass
class CandidateStoreItemNeighborsProvider:
    config: dict[str, Any]
    store: CandidateStore
    enabled: bool = True
    name: str = "candidate_store_item_neighbors"
    role: str = "online_item_neighbor_recall"
    source_name: str = "item_neighbors"

    @classmethod
    def from_config(cls, provider_config: dict[str, Any], *, provider_name: str | None = None) -> "CandidateStoreItemNeighborsProvider":
        config = dict(provider_config)
        source = str(config.get("source", "item_neighbors"))
        return cls(
            config=config,
            store=build_candidate_store_from_env(),
            enabled=provider_enabled(provider_config),
            name=provider_name or str(config.get("name", "candidate_store_item_neighbors")),
            role=str(config.get("role", "online_item_neighbor_recall")),
            source_name=str(config.get("source_name", source)),
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
        seeds = _seed_items(request.user_sequence, clamp_int(self.config.get("seed_window"), 20, maximum=100))
        per_seed = clamp_int(self.config.get("limit_per_seed"), 20, maximum=100)
        source = str(self.config.get("source", "item_neighbors"))
        candidates = self.store.item_neighbors(source=source, seed_items=seeds, limit_per_seed=per_seed)
        return ProviderResult(self.name, self.source_name, self.role, candidates=candidates, available=bool(self.store.health().get("enabled")), status="ok" if candidates else "empty")


def _seed_items(user_sequence: dict[str, Any], window: int) -> list[str]:
    values = user_sequence.get("recent_positive_item_sequence", []) or user_sequence.get("recent_item_sequence", [])
    rows: list[str] = []
    seen: set[str] = set()
    for value in reversed(values[-window:] if isinstance(values, list) else []):
        item_id = str(value or "").strip()
        if item_id and item_id not in seen:
            rows.append(item_id)
            seen.add(item_id)
    return rows
