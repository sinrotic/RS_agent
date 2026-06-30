from __future__ import annotations

import json
from pathlib import Path

from typing import Any

from rs_core.online.recall.online_retrieval.models import RetrievalRequest
from rs_core.online.recall.online_retrieval.providers.pool500_fallback import Pool500FallbackProvider
from rs_core.common.recsys_types import RecallCandidate
from rs_core.online.recall.online_retrieval.providers.candidate_store_usercf import CandidateStoreUserCFProvider
from rs_core.online.recall.online_retrieval.providers.semantic_token import SemanticTokenProvider
from rs_core.online.recall.online_retrieval.providers.semantic_vector import SemanticVectorProvider


def test_pool500_fallback_reads_fallback_only_config(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0}) + "\n", encoding="utf-8")

    provider = Pool500FallbackProvider.from_config({"enabled": True, "fallback_only": True}, {"online_route": {"pool500_candidates_path": str(path)}})

    assert provider.fallback_only is True
    assert "fallback" in provider.role


def test_pool500_fallback_loads_legacy_online_route_path(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "i1", "source": "popular", "score": 1.0, "metadata": {}}) + "\n", encoding="utf-8")
    provider = Pool500FallbackProvider.from_config({}, {"online_route": {"pool500_candidates_path": str(path)}})

    result = provider.retrieve(RetrievalRequest({"user_id": "u1"}, {}, candidate_pool_size=10))

    assert result.status == "ok"
    assert [candidate.item_id for candidate in result.candidates] == ["i1"]
    assert result.candidates[0].metadata["pool500_fallback_used"] is True


class FakePoolStore:
    def __init__(self, candidates: list[RecallCandidate] | None = None, *, fail: bool = False) -> None:
        self.candidates = candidates or []
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def health(self) -> dict[str, Any]:
        return {"enabled": True, "status": "ok", "backend": "fake"}

    def pool_candidates(self, *, user_id: str, limit: int) -> list[RecallCandidate]:
        self.calls.append({"user_id": user_id, "limit": limit})
        if self.fail:
            raise RuntimeError("boom")
        return self.candidates[:limit]


class EmptyPoolStore(FakePoolStore):
    pass


def test_pool500_fallback_prefers_candidate_store_when_configured(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "json_item", "source": "popular", "score": 1.0, "metadata": {}}) + "\n", encoding="utf-8")
    store = FakePoolStore([RecallCandidate(item_id="db_item", source="pool500_fallback", score=2.0)])
    provider = Pool500FallbackProvider(candidates_path=path, store=store, prefer_candidate_store=True)

    result = provider.retrieve(RetrievalRequest({"user_id": "u1"}, {}, candidate_pool_size=10))

    assert result.status == "ok"
    assert result.diagnostics["backend"] == "candidate_store"
    assert [candidate.item_id for candidate in result.candidates] == ["db_item"]
    assert store.calls == [{"user_id": "u1", "limit": 10}]


def test_pool500_fallback_readiness_uses_candidate_store_when_jsonl_missing(tmp_path: Path) -> None:
    provider = Pool500FallbackProvider(candidates_path=tmp_path / "missing.jsonl", store=FakePoolStore(), prefer_candidate_store=True)

    readiness = provider.readiness()

    assert readiness.available is True
    assert readiness.status == "ready"
    assert readiness.backend == "fake"


def test_pool500_fallback_uses_jsonl_when_candidate_store_empty_or_fails(tmp_path: Path) -> None:
    path = tmp_path / "pool500.jsonl"
    path.write_text(json.dumps({"user_id": "u1", "item_id": "json_item", "source": "popular", "score": 1.0, "metadata": {}}) + "\n", encoding="utf-8")

    empty_result = Pool500FallbackProvider(candidates_path=path, store=EmptyPoolStore(), prefer_candidate_store=True).retrieve(RetrievalRequest({"user_id": "u1"}, {}, candidate_pool_size=10))
    failed_result = Pool500FallbackProvider(candidates_path=path, store=FakePoolStore(fail=True), prefer_candidate_store=True).retrieve(RetrievalRequest({"user_id": "u1"}, {}, candidate_pool_size=10))

    assert empty_result.diagnostics["candidate_store_status"] == "empty"
    assert empty_result.diagnostics["backend"] == "jsonl"
    assert [candidate.item_id for candidate in empty_result.candidates] == ["json_item"]
    assert failed_result.diagnostics["candidate_store_error_type"] == "RuntimeError"
    assert failed_result.diagnostics["backend"] == "jsonl"
    assert [candidate.item_id for candidate in failed_result.candidates] == ["json_item"]


def test_candidate_store_named_provider_can_report_cassandra_backend(monkeypatch) -> None:
    monkeypatch.setenv("RS_CANDIDATE_STORE_BACKEND", "cassandra")
    monkeypatch.setenv("RS_CASSANDRA_STORE_VERSION", "test_v1")
    provider = CandidateStoreUserCFProvider.from_config({"enabled": True})

    readiness = provider.readiness()

    assert readiness.provider_name == "candidate_store_usercf"
    assert readiness.backend == "cassandra"
    assert readiness.available is False
    assert readiness.status == "degraded"


def test_semantic_vector_rejects_rag_chunk_collection() -> None:
    provider = SemanticVectorProvider.from_config({"enabled": True, "collection_name": "rs_agent_rag_chunks_v1"})

    readiness = provider.readiness()

    assert readiness.status == "governance_error"
    assert readiness.available is False


def test_semantic_token_readiness_states() -> None:
    disabled = SemanticTokenProvider.from_config({"enabled": False}, semantic_index={"seed": {}})
    missing = SemanticTokenProvider.from_config({"enabled": True}, semantic_index=None)
    ready = SemanticTokenProvider.from_config({"enabled": True}, semantic_index={"seed": {"semantic_tokens": {"usb"}}})

    assert disabled.readiness().status == "disabled"
    assert missing.readiness().status == "missing_semantic_index"
    assert ready.readiness().status == "ready"
    assert ready.readiness().available is True


def test_semantic_token_retrieve_returns_candidates_and_diagnostics() -> None:
    semantic_index = {
        "seed": {"semantic_tokens": {"usb", "charger"}, "main_category": "Electronics"},
        "candidate": {"semantic_tokens": {"usb", "charger"}, "main_category": "Electronics"},
        "other": {"semantic_tokens": {"case"}, "main_category": "Accessories"},
    }
    provider = SemanticTokenProvider.from_config(
        {
            "enabled": True,
            "semantic_score_mode": "idf_seed_aware",
            "semantic_seed_window": 20,
            "semantic_per_seed": 20,
            "semantic_per_user": 60,
            "semantic_min_overlap": 1,
            "semantic_max_df_ratio": 1.0,
        },
        semantic_index=semantic_index,
    )

    result = provider.retrieve(RetrievalRequest({"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}, {}))

    assert result.provider_name == "semantic_token"
    assert result.source_name == "semantic"
    assert result.role == "semantic_token_recall"
    assert result.status == "ok"
    assert [candidate.item_id for candidate in result.candidates] == ["candidate"]
    assert result.candidates[0].source == "semantic"
    assert result.diagnostics["semantic_score_mode"] == "idf_seed_aware"
    assert result.diagnostics["semantic_seed_window"] == 20
    assert result.diagnostics["semantic_per_seed"] == 20
    assert result.diagnostics["semantic_per_user"] == 60
    assert result.diagnostics["semantic_min_overlap"] == 1
    assert result.diagnostics["semantic_max_df_ratio"] == 1.0
    assert result.diagnostics["semantic_index_size"] == 3
    assert result.diagnostics["candidate_count"] == 1
