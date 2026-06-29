from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rs_core.online.recall.candidate_store.factory import build_candidate_store_from_env
from rs_core.online.recall.candidate_store.base import CandidateStore, NoopCandidateStore
from rs_core.online.recall.online_retrieval.config import provider_enabled, resolve_project_path
from rs_core.online.recall.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest
from rs_core.online.recall.pool500_artifacts import Pool500ArtifactIndex, load_pool500_artifact_index
from rs_core.common.recsys_types import RecallCandidate


@dataclass
class Pool500FallbackProvider:
    candidates_path: Path | None
    allowed_sources: set[str] | None = None
    store: CandidateStore | None = None
    prefer_candidate_store: bool = False
    fallback_only: bool = True
    enabled: bool = True
    name: str = "pool500_fallback"
    role: str = "fallback_rollback_backfill"
    source_name: str = "pool500_fallback"
    _index: Pool500ArtifactIndex | None = None
    _error: str | None = None

    @classmethod
    def from_config(cls, provider_config: dict[str, Any], root_config: dict[str, Any], *, config_path: str | None = None) -> "Pool500FallbackProvider":
        route = root_config.get("online_route") if isinstance(root_config.get("online_route"), dict) else {}
        artifact = root_config.get("pool500_artifact") if isinstance(root_config.get("pool500_artifact"), dict) else {}
        raw_path = provider_config.get("candidates_path") or route.get("pool500_candidates_path") or artifact.get("candidates_path") or root_config.get("pool500_candidates_path")
        allowed = provider_config.get("allowed_sources") or route.get("allowed_sources") or root_config.get("pool500_allowed_sources")
        allowed_sources = {str(value) for value in allowed if str(value or "").strip()} if isinstance(allowed, list) else None
        prefer_candidate_store = _bool_config(provider_config.get("prefer_candidate_store", route.get("pool500_prefer_candidate_store", root_config.get("pool500_prefer_candidate_store"))))
        fallback_only = _bool_config(provider_config.get("fallback_only", route.get("pool500_fallback_only", root_config.get("pool500_fallback_only", True))))
        store: CandidateStore | None = build_candidate_store_from_env() if prefer_candidate_store else None
        return cls(
            candidates_path=resolve_project_path(raw_path, config_path),
            allowed_sources=allowed_sources,
            store=store,
            prefer_candidate_store=prefer_candidate_store,
            fallback_only=fallback_only,
            enabled=provider_enabled(provider_config),
        )

    def readiness(self) -> ProviderReadiness:
        backend = "candidate_store+jsonl" if self.prefer_candidate_store else "jsonl"
        if not self.enabled:
            return ProviderReadiness(self.name, False, False, "disabled", self.role, backend=backend, source_name=self.source_name)
        if self.prefer_candidate_store:
            health = self._store().health()
            if bool(health.get("enabled")) and health.get("status") in {"ok", "ready"}:
                return ProviderReadiness(self.name, True, True, "ready", self.role, backend=str(health.get("backend", "candidate_store")), source_name=self.source_name)
            if self.candidates_path is None:
                return ProviderReadiness(self.name, True, False, str(health.get("status", "not_configured")), self.role, backend=str(health.get("backend", "candidate_store")), source_name=self.source_name)
        if self.candidates_path is None:
            return ProviderReadiness(self.name, True, False, "not_configured", self.role, backend=backend, source_name=self.source_name)
        if not self.candidates_path.exists() and not self.prefer_candidate_store:
            return ProviderReadiness(self.name, True, False, "missing_artifact", self.role, backend="jsonl", source_name=self.source_name)
        try:
            index = self._get_index()
        except Exception as exc:  # pragma: no cover - defensive readiness
            return ProviderReadiness(self.name, True, False, "degraded", self.role, backend=backend, source_name=self.source_name, diagnostics={"error_type": type(exc).__name__})
        return ProviderReadiness(
            self.name,
            True,
            True,
            "ready",
            self.role,
            backend=backend,
            source_name=self.source_name,
            diagnostics={"row_count": index.row_count, "user_count": index.user_count},
        )

    def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        if not self.enabled:
            return ProviderResult(self.name, self.source_name, self.role, available=False, status="disabled")
        diagnostics: dict[str, Any] = {}
        if self.prefer_candidate_store:
            try:
                candidates = self._store().pool_candidates(user_id=request.user_id, limit=request.candidate_pool_size)
            except Exception as exc:
                diagnostics["candidate_store_error_type"] = type(exc).__name__
            else:
                if candidates:
                    return ProviderResult(
                        self.name,
                        self.source_name,
                        self.role,
                        candidates=candidates[: request.candidate_pool_size],
                        available=True,
                        status="ok",
                        diagnostics={"backend": "candidate_store"},
                    )
                diagnostics["candidate_store_status"] = "empty"
        if self.candidates_path is None:
            return ProviderResult(self.name, self.source_name, self.role, available=False, status="not_configured", diagnostics=diagnostics)
        try:
            candidates = [_merged_to_recall(candidate) for candidate in self._get_index().candidates_for_user(request.user_id, seen_items=request.seen_items)]
        except Exception as exc:
            return ProviderResult(self.name, self.source_name, self.role, available=False, status="degraded", diagnostics=diagnostics | {"error_type": type(exc).__name__})
        return ProviderResult(self.name, self.source_name, self.role, candidates=candidates[: request.candidate_pool_size], available=True, status="ok", diagnostics=diagnostics | {"backend": "jsonl"})

    def _get_index(self) -> Pool500ArtifactIndex:
        if self._index is not None:
            return self._index
        if self.candidates_path is None:
            raise ValueError("pool500 fallback candidates_path is not configured")
        self._index = load_pool500_artifact_index(self.candidates_path, allowed_sources=self.allowed_sources)
        return self._index

    def _store(self) -> CandidateStore:
        if self.store is None:
            self.store = build_candidate_store_from_env() if self.prefer_candidate_store else NoopCandidateStore()
        return self.store


def _bool_config(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _merged_to_recall(candidate: Any) -> RecallCandidate:
    score = max(candidate.source_scores.values()) if candidate.source_scores else 0.0
    source = candidate.sources[0] if candidate.sources else "pool500_fallback"
    return RecallCandidate(
        item_id=candidate.item_id,
        source=source,
        score=float(score),
        category=candidate.category,
        metadata=dict(candidate.metadata) | {"pool500_fallback_used": True},
    )
