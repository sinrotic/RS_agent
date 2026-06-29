from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rs_core.online.recall.candidate_merge import merge_candidates
from rs_core.online.recall.online_retrieval.config import clamp_int, online_retrieval_config, provider_configs
from rs_core.online.recall.online_retrieval.models import OrchestratorResult, ProviderResult, RetrievalRequest
from rs_core.online.recall.online_retrieval.provider import CandidateProvider
from rs_core.common.recsys_types import RecallCandidate


@dataclass
class CandidateRetrievalOrchestrator:
    providers: list[CandidateProvider] = field(default_factory=list)
    enabled: bool = False
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        config_path: str | None = None,
        semantic_index: dict[str, dict[str, Any]] | None = None,
    ) -> "CandidateRetrievalOrchestrator":
        retrieval = online_retrieval_config(config)
        providers: list[CandidateProvider] = []
        provider_map = provider_configs(config)
        for name, provider_config in provider_map.items():
            provider = _build_provider(name, provider_config, config, config_path=config_path, semantic_index=semantic_index)
            if provider is not None:
                providers.append(provider)
        return cls(providers=providers, enabled=bool(retrieval.get("enabled", bool(providers))), config=retrieval)

    def readiness(self) -> dict[str, Any]:
        provider_status = {provider.name: provider.readiness().to_dict() for provider in self.providers}
        available_count = sum(1 for status in provider_status.values() if status.get("available"))
        configured_count = len(provider_status)
        return {
            "enabled": self.enabled,
            "available": self.enabled and available_count > 0,
            "status": "ready" if self.enabled and available_count > 0 else "disabled" if not self.enabled else "degraded",
            "configured_provider_count": configured_count,
            "available_provider_count": available_count,
            "providers": provider_status,
        }

    def retrieve(
        self,
        user_sequence: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        seen_items: set[str] | None = None,
        prior_turn_items: set[str] | None = None,
        candidate_pool_size: int | None = None,
        retrieve_policy: dict[str, Any] | None = None,
        hints: dict[str, Any] | None = None,
    ) -> OrchestratorResult:
        request_config = dict(config or {})
        target = clamp_int(candidate_pool_size or request_config.get("candidate_pool_size"), 500, maximum=5000)
        if not self.enabled:
            return OrchestratorResult(
                candidates=[],
                provider_results=[],
                diagnostics={
                    "status": "disabled",
                    "target_pool_size": target,
                    "candidate_count_before_limit": 0,
                    "candidate_count": 0,
                    "underfilled_before_fallback": True,
                    "underfilled_after_fallback": True,
                    "fallback_used": False,
                    "provider_coverage": {},
                },
                fallback_used=False,
            )
        seen = {str(item) for item in (seen_items or set()) if str(item or "").strip()}
        seen.update(str(item) for item in (prior_turn_items or set()) if str(item or "").strip())
        seen.update(str(item) for item in user_sequence.get("recent_item_sequence", []) if str(item or "").strip())
        request = RetrievalRequest(
            user_sequence=user_sequence,
            config=request_config,
            seen_items=seen,
            candidate_pool_size=target,
            retrieve_policy=retrieve_policy or {},
            hints=hints or {},
        )
        raw_candidates: list[RecallCandidate] = []
        provider_results: list[ProviderResult] = []
        fallback_providers: list[CandidateProvider] = []
        fallback_used = False

        for provider in self.providers:
            if getattr(provider, "fallback_only", False) or "fallback" in provider.role:
                fallback_providers.append(provider)
                continue
            result = _safe_retrieve(provider, request)
            provider_results.append(result)
            raw_candidates.extend(result.candidates)

        merged = merge_candidates(raw_candidates, seen_items=seen)
        underfilled_before_fallback = len(merged) < target
        if underfilled_before_fallback:
            for provider in fallback_providers:
                before_ids = {candidate.item_id for candidate in merged}
                result = _safe_retrieve(provider, request)
                raw_count = len(result.candidates)
                raw_candidates.extend(result.candidates)
                merged = merge_candidates(raw_candidates, seen_items=seen)
                after_ids = {candidate.item_id for candidate in merged}
                net_new_count = len(after_ids - before_ids)
                result.fallback_used = net_new_count > 0
                result.diagnostics = {
                    **result.diagnostics,
                    "fallback_raw_candidate_count": raw_count,
                    "fallback_net_new_candidate_count": net_new_count,
                }
                provider_results.append(result)
                fallback_used = fallback_used or result.fallback_used
                if len(merged) >= target:
                    break
        else:
            for provider in fallback_providers:
                provider_results.append(ProviderResult(
                    provider_name=provider.name,
                    source_name=provider.source_name,
                    role=provider.role,
                    available=provider.readiness().available,
                    status="not_needed",
                    diagnostics={"reason": "quota_filled_before_fallback"},
                ))

        trimmed = merged[:target]
        diagnostics = {
            "target_pool_size": target,
            "candidate_count_before_limit": len(merged),
            "candidate_count": len(trimmed),
            "underfilled_before_fallback": underfilled_before_fallback,
            "underfilled_after_fallback": len(trimmed) < target,
            "fallback_used": fallback_used,
            "provider_coverage": _provider_coverage(provider_results),
        }
        return OrchestratorResult(candidates=trimmed, provider_results=provider_results, diagnostics=diagnostics, fallback_used=fallback_used)


def _safe_retrieve(provider: CandidateProvider, request: RetrievalRequest) -> ProviderResult:
    try:
        return provider.retrieve(request)
    except Exception as exc:  # pragma: no cover - provider boundary must fail open
        return ProviderResult(
            provider_name=provider.name,
            source_name=provider.source_name,
            role=provider.role,
            candidates=[],
            available=False,
            status="degraded",
            diagnostics={"reason": "provider_exception", "error_type": type(exc).__name__},
        )


def _provider_coverage(results: list[ProviderResult]) -> dict[str, Any]:
    return {
        result.provider_name: {
            "status": result.status,
            "available": result.available,
            "candidate_count": len(result.candidates),
            "fallback_used": result.fallback_used,
        }
        for result in results
    }


def _build_provider(
    name: str,
    provider_config: dict[str, Any],
    root_config: dict[str, Any],
    *,
    config_path: str | None,
    semantic_index: dict[str, dict[str, Any]] | None = None,
) -> CandidateProvider | None:
    if name == "pool500_fallback":
        from rs_core.online.recall.online_retrieval.providers.pool500_fallback import Pool500FallbackProvider

        return Pool500FallbackProvider.from_config(provider_config, root_config, config_path=config_path)
    if name in {"candidate_store_item_neighbors", "candidate_store_itemcf_strong", "candidate_store_itemcf_weak", "candidate_store_co_visit_repair"}:
        from rs_core.online.recall.online_retrieval.providers.candidate_store_item_neighbors import CandidateStoreItemNeighborsProvider

        default_sources = {
            "candidate_store_itemcf_strong": "itemcf_strong",
            "candidate_store_itemcf_weak": "itemcf_weak",
            "candidate_store_co_visit_repair": "co_visit_fallback_repair",
        }
        config_with_source = dict(provider_config)
        config_with_source.setdefault("source", default_sources.get(name, "item_neighbors"))
        return CandidateStoreItemNeighborsProvider.from_config(config_with_source, provider_name=name)
    if name == "candidate_store_usercf":
        from rs_core.online.recall.online_retrieval.providers.candidate_store_usercf import CandidateStoreUserCFProvider

        config_with_source = dict(provider_config)
        config_with_source.setdefault("source", "usercf_recall")
        return CandidateStoreUserCFProvider.from_config(config_with_source, provider_name=name)
    if name == "candidate_store_popular":
        from rs_core.online.recall.online_retrieval.providers.candidate_store_popular import CandidateStorePopularProvider

        return CandidateStorePopularProvider.from_config(provider_config, provider_name=name)
    if name == "candidate_store_category":
        from rs_core.online.recall.online_retrieval.providers.candidate_store_category import CandidateStoreCategoryProvider

        return CandidateStoreCategoryProvider.from_config(provider_config, provider_name=name)
    if name == "semantic_token":
        from rs_core.online.recall.online_retrieval.providers.semantic_token import SemanticTokenProvider

        return SemanticTokenProvider.from_config(provider_config, semantic_index=semantic_index)
    if name == "semantic_vector":
        from rs_core.online.recall.online_retrieval.providers.semantic_vector import SemanticVectorProvider

        return SemanticVectorProvider.from_config(provider_config)
    return None
