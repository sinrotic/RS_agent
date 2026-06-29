from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rs_core.online.recall.online_retrieval.models import ProviderReadiness, ProviderResult, RetrievalRequest
from rs_core.online.recall.online_retrieval.orchestrator import CandidateRetrievalOrchestrator
from rs_core.common.recsys_types import RecallCandidate
from rs_core.online.runtime.pool500 import _has_online_retrieval_config


@dataclass
class StubProvider:
    name: str
    role: str
    candidates: list[RecallCandidate]
    available: bool = True
    status: str = "ok"
    source_name: str = "stub"

    def readiness(self) -> ProviderReadiness:
        return ProviderReadiness(self.name, True, self.available, self.status, self.role, source_name=self.source_name)

    def retrieve(self, request: RetrievalRequest) -> ProviderResult:
        return ProviderResult(self.name, self.source_name, self.role, list(self.candidates), self.available, self.status)


def test_orchestrator_merges_filters_seen_and_uses_fallback_on_underfill() -> None:
    primary = StubProvider("primary", "primary", [RecallCandidate("seen", "a", 9.0), RecallCandidate("x", "a", 1.0), RecallCandidate("x", "b", 2.0)])
    fallback = StubProvider("fallback", "fallback_rollback_backfill", [RecallCandidate("y", "popular", 1.5)])
    orchestrator = CandidateRetrievalOrchestrator([primary, fallback], enabled=True)

    result = orchestrator.retrieve({"user_id": "u1", "recent_item_sequence": ["seen"]}, candidate_pool_size=2)

    assert [candidate.item_id for candidate in result.candidates] == ["x", "y"]
    assert result.candidates[0].sources == ["a", "b"]
    assert result.fallback_used is True
    assert result.diagnostics["underfilled_before_fallback"] is True


def test_orchestrator_skips_fallback_when_quota_filled() -> None:
    primary = StubProvider("primary", "primary", [RecallCandidate("x", "a", 2.0), RecallCandidate("y", "a", 1.0)])
    fallback = StubProvider("fallback", "fallback_rollback_backfill", [RecallCandidate("z", "popular", 1.5)])
    orchestrator = CandidateRetrievalOrchestrator([primary, fallback], enabled=True)

    result = orchestrator.retrieve({"user_id": "u1", "recent_item_sequence": []}, candidate_pool_size=1)

    assert [candidate.item_id for candidate in result.candidates] == ["x"]
    assert result.fallback_used is False
    assert result.provider_results[-1].status == "not_needed"


def test_real_serving_configs_use_method_level_candidate_store_providers(monkeypatch) -> None:
    monkeypatch.setenv("RS_CANDIDATE_STORE_BACKEND", "noop")
    for path in [Path("configs/serving/online_service.yaml"), Path("configs/serving/online_service.local_milvus.yaml")]:
        config = json.loads(path.read_text(encoding="utf-8"))
        orchestrator = CandidateRetrievalOrchestrator.from_config(config)
        provider_names = [provider.name for provider in orchestrator.providers]

        for expected in [
            "candidate_store_itemcf_strong",
            "candidate_store_itemcf_weak",
            "candidate_store_co_visit_repair",
            "candidate_store_usercf",
            "candidate_store_category",
            "candidate_store_popular",
            "pool500_fallback",
        ]:
            assert expected in provider_names
        fallback = next(provider for provider in orchestrator.providers if provider.name == "pool500_fallback")
        assert getattr(fallback, "fallback_only") is True
        assert getattr(fallback, "prefer_candidate_store") is False


def test_from_config_builds_method_level_candidate_store_providers(monkeypatch) -> None:
    monkeypatch.setenv("RS_CANDIDATE_STORE_BACKEND", "noop")
    config = {
        "online_retrieval": {
            "enabled": True,
            "providers": {
                "candidate_store_itemcf_strong": {"enabled": True, "source": "itemcf_strong"},
                "candidate_store_itemcf_weak": {"enabled": True, "source": "itemcf_weak"},
                "candidate_store_co_visit_repair": {"enabled": True, "source": "co_visit_fallback_repair"},
                "candidate_store_usercf": {"enabled": True, "source": "usercf_recall"},
                "candidate_store_category": {"enabled": True},
                "candidate_store_popular": {"enabled": True},
                "pool500_fallback": {"enabled": False},
            },
        }
    }

    orchestrator = CandidateRetrievalOrchestrator.from_config(config)

    assert [provider.name for provider in orchestrator.providers] == [
        "candidate_store_itemcf_strong",
        "candidate_store_itemcf_weak",
        "candidate_store_co_visit_repair",
        "candidate_store_usercf",
        "candidate_store_category",
        "candidate_store_popular",
        "pool500_fallback",
    ]
    assert [provider.source_name for provider in orchestrator.providers[:6]] == [
        "itemcf_strong",
        "itemcf_weak",
        "co_visit_fallback_repair",
        "usercf_recall",
        "category",
        "popular",
    ]
    assert "fallback" in orchestrator.providers[-1].role


def test_from_config_builds_semantic_token_and_reports_coverage_not_needed_fallback() -> None:
    semantic_index = {
        "seed": {"semantic_tokens": {"usb", "charger"}, "main_category": "Electronics"},
        "candidate": {"semantic_tokens": {"usb", "charger"}, "main_category": "Electronics"},
    }
    config = {
        "online_retrieval": {
            "enabled": True,
            "providers": {
                "semantic_token": {
                    "enabled": True,
                    "semantic_score_mode": "idf_seed_aware",
                    "semantic_per_user": 60,
                    "semantic_per_seed": 20,
                    "semantic_seed_window": 20,
                    "semantic_min_overlap": 1,
                    "semantic_max_df_ratio": 1.0,
                },
                "pool500_fallback": {"enabled": False},
            },
        }
    }

    orchestrator = CandidateRetrievalOrchestrator.from_config(config, semantic_index=semantic_index)
    result = orchestrator.retrieve({"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}, candidate_pool_size=1)

    assert [provider.name for provider in orchestrator.providers] == ["semantic_token", "pool500_fallback"]
    assert [candidate.item_id for candidate in result.candidates] == ["candidate"]
    assert result.diagnostics["provider_coverage"]["semantic_token"]["candidate_count"] == 1
    assert result.diagnostics["provider_coverage"]["pool500_fallback"]["status"] == "not_needed"
    assert result.diagnostics["underfilled_before_fallback"] is False
    assert result.fallback_used is False


def test_from_config_semantic_token_underfill_fallback_semantics() -> None:
    config = {
        "online_retrieval": {
            "enabled": True,
            "providers": {
                "semantic_token": {"enabled": True, "semantic_score_mode": "idf_seed_aware"},
                "pool500_fallback": {"enabled": False},
            },
        }
    }

    orchestrator = CandidateRetrievalOrchestrator.from_config(config, semantic_index={})
    result = orchestrator.retrieve({"user_id": "u1", "recent_item_sequence": [], "recent_positive_item_sequence": []}, candidate_pool_size=1)

    assert result.diagnostics["provider_coverage"]["semantic_token"]["status"] == "missing_semantic_index"
    assert result.diagnostics["provider_coverage"]["pool500_fallback"]["status"] == "disabled"
    assert result.diagnostics["underfilled_before_fallback"] is True
    assert result.diagnostics["underfilled_after_fallback"] is True
    assert result.fallback_used is False


def test_orchestrator_disabled_returns_no_candidates_or_provider_calls() -> None:
    provider = StubProvider("primary", "primary", [RecallCandidate("x", "a", 1.0)])
    orchestrator = CandidateRetrievalOrchestrator([provider], enabled=False)

    result = orchestrator.retrieve({"user_id": "u1", "recent_item_sequence": []}, candidate_pool_size=1)

    assert result.candidates == []
    assert result.provider_results == []
    assert result.diagnostics["status"] == "disabled"
    assert result.diagnostics["provider_coverage"] == {}
    assert result.fallback_used is False


def test_online_retrieval_config_requires_enabled_true() -> None:
    assert _has_online_retrieval_config({"online_retrieval": {"enabled": False, "providers": {"semantic_token": {"enabled": True}}}}) is False
    assert _has_online_retrieval_config({"online_retrieval": {"enabled": True, "providers": {}}}) is True


def test_fallback_used_requires_net_new_candidates() -> None:
    primary = StubProvider("primary", "primary", [RecallCandidate("x", "a", 2.0)])
    fallback = StubProvider("fallback", "fallback_rollback_backfill", [RecallCandidate("x", "popular", 1.5), RecallCandidate("seen", "popular", 1.0)])
    orchestrator = CandidateRetrievalOrchestrator([primary, fallback], enabled=True)

    result = orchestrator.retrieve({"user_id": "u1", "recent_item_sequence": ["seen"]}, candidate_pool_size=2)

    fallback_result = result.provider_results[-1]
    assert [candidate.item_id for candidate in result.candidates] == ["x"]
    assert fallback_result.fallback_used is False
    assert fallback_result.diagnostics["fallback_raw_candidate_count"] == 2
    assert fallback_result.diagnostics["fallback_net_new_candidate_count"] == 0
    assert result.fallback_used is False
    assert result.diagnostics["underfilled_after_fallback"] is True
