from __future__ import annotations

from pathlib import Path

import pytest

from rs_core.serving.domain.adapter_contracts import (
    AdapterConfig,
    ArtifactRef,
    CacheAdapter,
    KnowledgeQuery,
    MockArtifactAdapter,
    MockCacheAdapter,
    MockKnowledgeAdapter,
    MockStoreAdapter,
    MockTaskAdapter,
    StoreAdapter,
    TaskAdapter,
    validate_adapter_contract,
    validate_standard_adapters,
)

pytestmark = [pytest.mark.unit, pytest.mark.serving]


def test_mock_adapters_satisfy_protocol_contracts(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact.json"
    artifact_path.write_text("{}", encoding="utf-8")
    artifact = MockArtifactAdapter(tmp_path)
    artifact.register(ArtifactRef(artifact_id="a1", artifact_type="candidate_pool", path="artifact.json"))

    result = validate_standard_adapters(
        store=MockStoreAdapter(),
        cache=MockCacheAdapter(),
        artifact=artifact,
        knowledge=MockKnowledgeAdapter(),
        task=MockTaskAdapter(),
    )

    assert result.valid is True
    assert isinstance(MockStoreAdapter(), StoreAdapter)
    assert isinstance(MockCacheAdapter(), CacheAdapter)
    assert isinstance(MockTaskAdapter(), TaskAdapter)


def test_store_and_cache_mocks_roundtrip_values() -> None:
    store = MockStoreAdapter()
    fact_id = store.write_fact("session_started", {"session_id": "s1"})
    cache = MockCacheAdapter()

    cache.set("fact", fact_id, ttl_seconds=60)

    assert store.read_fact(fact_id) == {"fact_type": "session_started", "session_id": "s1"}
    assert cache.get("fact") == fact_id
    cache.delete("fact")
    assert cache.get("fact") is None


def test_knowledge_adapter_keeps_query_sync_and_refresh_async() -> None:
    adapter = MockKnowledgeAdapter()

    result = adapter.query(KnowledgeQuery(query="wireless headphones", top_k=3, timeout_seconds=5.0))
    task = adapter.request_index_refresh(reason="catalog_update")

    assert result.documents[0]["text"] == "wireless headphones"
    assert adapter.config.sync_path is True
    assert adapter.config.async_path is True
    assert task.status == "queued"
    assert task.task_type == "rag_index_refresh"
    assert "online_rag_query" in adapter.config.governance_tags
    assert "no_ranking_replacement" in adapter.config.governance_tags


def test_task_adapter_represents_async_work_boundary() -> None:
    adapter = MockTaskAdapter()

    task = adapter.enqueue("session_summary", {"session_id": "s1"})

    assert adapter.config.sync_path is False
    assert adapter.config.async_path is True
    assert adapter.status(task.task_id) == task


def test_contract_validator_reports_missing_methods_and_bad_config() -> None:
    class BrokenAdapter:
        config = AdapterConfig(name="", backend="", sync_path=False, async_path=False)

    result = validate_adapter_contract(BrokenAdapter(), ("missing",))

    assert result.valid is False
    assert "adapter name is required" in result.errors
    assert "missing callable method: missing" in result.errors
