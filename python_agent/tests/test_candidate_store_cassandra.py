from __future__ import annotations

from typing import Any

from rs_core.online.recall.candidate_store.cassandra import CassandraCandidateStore, CassandraSettings
from rs_core.online.recall.candidate_store.factory import build_candidate_store_from_env
from rs_core.online.recall.candidate_store.base import NoopCandidateStore, SafeCandidateStore


class FakeSession:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Any]] = []

    def execute(self, statement: Any, parameters: Any | None = None) -> list[Any]:
        sql = str(statement)
        self.calls.append((sql, parameters))
        for key, rows in self.responses.items():
            if key in sql:
                return rows
        return []


def test_factory_returns_noop_for_explicit_noop(monkeypatch) -> None:
    monkeypatch.setenv("RS_CANDIDATE_STORE_BACKEND", "noop")

    assert isinstance(build_candidate_store_from_env(), NoopCandidateStore)


def test_cassandra_health_reports_tables_without_secrets() -> None:
    session = FakeSession({"system_schema.tables": [{"table_name": "item_neighbors_by_seed"}]})
    store = CassandraCandidateStore(settings=CassandraSettings(password="secret", store_version="v1"), session=session)

    health = store.health()

    assert health["backend"] == "cassandra"
    assert health["store_version"] == "v1"
    assert health["tables"]["item_neighbors_by_seed"] is True
    assert "password" not in health
    assert health["status"] == "degraded"


def test_cassandra_item_neighbors_queries_each_seed_and_maps_candidates() -> None:
    session = FakeSession({
        "FROM item_neighbors_by_seed": [
            {"source": "itemcf", "dst_item_id": "i1", "score": 0.7, "rank": 2, "category": "books", "artifact_id": "a1", "metadata": '{"x": 1}'},
        ]
    })
    store = CassandraCandidateStore(settings=CassandraSettings(store_version="v1"), session=session)

    candidates = store.item_neighbors(source="itemcf", seed_items=["seed1", "seed1", "seed2"], limit_per_seed=5)

    assert [call[1][2] for call in session.calls] == ["seed1", "seed2"]
    assert candidates[0].item_id == "i1"
    assert candidates[0].source == "itemcf"
    assert candidates[0].metadata["seed_item_id"] == "seed1"
    assert candidates[0].metadata["candidate_store_artifact_id"] == "a1"


def test_cassandra_user_and_category_paths_map_metadata() -> None:
    session = FakeSession({
        "FROM user_candidates_by_user": [
            {"source": "usercf_recall", "parent_asin": "u_item", "score": 1.0, "rank": 1, "metadata": "{}"},
        ],
        "FROM user_category_buckets_by_user": [{"bucket": "c1"}],
        "FROM category_candidates_by_bucket": [
            {"source": "category", "parent_asin": "c_item", "score": 0.5, "rank": 1, "metadata": "{}"},
        ],
    })
    store = CassandraCandidateStore(settings=CassandraSettings(store_version="v1"), session=session)

    user_candidates = store.user_candidates(user_id="u1", source="usercf_recall", limit=10)
    buckets = store.user_category_buckets(user_id="u1", limit=5)
    category_candidates = store.category_candidates(buckets=buckets, limit_per_bucket=5)

    assert user_candidates[0].item_id == "u_item"
    assert buckets == ["c1"]
    assert category_candidates[0].item_id == "c_item"
    assert category_candidates[0].metadata["category_bucket"] == "c1"


def test_cassandra_pool_candidates_queries_by_user_and_maps_candidates() -> None:
    session = FakeSession({
        "FROM pool_candidates_by_user": [
            {"source": "pool500_fallback", "parent_asin": "p_item", "score": 0.9, "rank": 1, "category": "books", "artifact_id": "pool_a1", "metadata": '{"x": 1}'},
        ]
    })
    store = CassandraCandidateStore(settings=CassandraSettings(store_version="v1"), session=session)

    candidates = store.pool_candidates(user_id="u1", limit=5)

    assert session.calls[0][1] == ("v1", "u1", 5)
    assert candidates[0].item_id == "p_item"
    assert candidates[0].source == "pool500_fallback"
    assert candidates[0].category == "books"
    assert candidates[0].metadata["candidate_store_artifact_id"] == "pool_a1"


def test_safe_cassandra_store_fails_open_on_query_exception() -> None:
    class BrokenStore:
        def health(self) -> dict[str, Any]:
            raise RuntimeError("boom")

        def item_neighbors(self, **kwargs: Any) -> list[Any]:
            raise RuntimeError("boom")

        def user_candidates(self, **kwargs: Any) -> list[Any]:
            raise RuntimeError("boom")

        def popular_candidates(self, **kwargs: Any) -> list[Any]:
            raise RuntimeError("boom")

        def category_candidates(self, **kwargs: Any) -> list[Any]:
            raise RuntimeError("boom")

        def user_category_buckets(self, **kwargs: Any) -> list[str]:
            raise RuntimeError("boom")

        def pool_candidates(self, **kwargs: Any) -> list[Any]:
            raise RuntimeError("boom")

    store = SafeCandidateStore(BrokenStore())

    assert store.health()["status"] == "degraded"
    assert store.user_candidates(user_id="u1", source="usercf_recall", limit=10) == []
    assert store.category_candidates(buckets=["c1"], limit_per_bucket=5) == []
    assert store.pool_candidates(user_id="u1", limit=10) == []
