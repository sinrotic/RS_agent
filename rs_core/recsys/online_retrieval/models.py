from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rs_core.recsys.types import MergedCandidate, RecallCandidate


@dataclass(frozen=True)
class RetrievalRequest:
    user_sequence: dict[str, Any]
    config: dict[str, Any]
    seen_items: set[str] = field(default_factory=set)
    candidate_pool_size: int = 500
    retrieve_policy: dict[str, Any] = field(default_factory=dict)
    hints: dict[str, Any] = field(default_factory=dict)

    @property
    def user_id(self) -> str:
        return str(self.user_sequence.get("user_id") or "")


@dataclass
class ProviderResult:
    provider_name: str
    source_name: str
    role: str
    candidates: list[RecallCandidate] = field(default_factory=list)
    available: bool = True
    status: str = "ok"
    fallback_used: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorResult:
    candidates: list[MergedCandidate]
    provider_results: list[ProviderResult]
    diagnostics: dict[str, Any]
    fallback_used: bool = False


@dataclass(frozen=True)
class ProviderReadiness:
    provider_name: str
    enabled: bool
    available: bool
    status: str
    role: str
    backend: str = "unknown"
    source_name: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
            "available": self.available,
            "status": self.status,
            "role": self.role,
            "backend": self.backend,
        }
        if self.source_name:
            payload["source"] = self.source_name
        payload.update({key: value for key, value in self.diagnostics.items() if key not in payload})
        return payload
