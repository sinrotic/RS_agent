from __future__ import annotations

from typing import Protocol

from rs_core.online.recall.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest


class CandidateProvider(Protocol):
    name: str
    role: str
    source_name: str

    def readiness(self) -> ProviderReadiness: ...

    def retrieve(self, request: RetrievalRequest) -> ProviderResult: ...
