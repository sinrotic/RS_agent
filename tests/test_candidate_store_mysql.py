from __future__ import annotations

import json
import subprocess

import pytest

from rs_core.online.recall.candidate_store.base import NoopCandidateStore, SafeCandidateStore
from rs_core.online.recall.candidate_store.factory import build_candidate_store_from_env
from rs_core.online.recall.candidate_store.mysql import MysqlCandidateStore, _ensure_select_only

pytestmark = pytest.mark.unit


def test_mysql_candidate_store_rejects_non_readonly_sql() -> None:
    with pytest.raises(ValueError, match="read-only|SELECT"):
        _ensure_select_only("DELETE FROM usercf_candidates")


@pytest.mark.parametrize("backend", ["", "mysql"])
def test_factory_backend_mysql_returns_noop_when_mysql_disabled(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    monkeypatch.setenv("RS_CANDIDATE_STORE_BACKEND", backend)
    monkeypatch.delenv("RS_MYSQL_CANDIDATE_STORE_ENABLED", raising=False)

    store = build_candidate_store_from_env()

    assert isinstance(store, NoopCandidateStore)
    assert store.health()["status"] == "disabled"


def test_factory_unknown_legacy_backend_returns_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_CANDIDATE_STORE_BACKEND", "legacy_backend")

    store = build_candidate_store_from_env()

    assert isinstance(store, NoopCandidateStore)
    assert store.health()["status"] == "disabled"


def test_safe_candidate_store_fails_open_without_secret_leak() -> None:
    class FailingStore:
        def health(self) -> dict[str, object]:
            return {"status": "degraded", "password": "secret", "url": "mysql://secret", "stderr": "secret", "command": "mysql -psecret"}

        def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[object]:
            raise RuntimeError("secret")

        def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[object]:
            raise RuntimeError("secret")

        def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[object]:
            raise RuntimeError("secret")

        def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[object]:
            raise RuntimeError("secret")

        def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
            raise RuntimeError("secret")

        def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[object]:
            raise RuntimeError("secret")

    store = SafeCandidateStore(FailingStore())
    health = store.health()

    assert health == {"status": "degraded"}
    leaked = json.dumps(health, ensure_ascii=False)
    assert "secret" not in leaked
    assert "password" not in leaked
    assert "mysql://" not in leaked
    assert "stderr" not in leaked
    assert "command" not in leaked
    assert store.user_candidates(user_id="u1", source="usercf", limit=10) == []


def test_item_neighbors_uses_mysql_json_table_and_json_object() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        payload = {"source": "itemcf", "src_item_id": "s1", "parent_asin": "i1", "score": 0.9, "rank": 1}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = MysqlCandidateStore(runner=runner)
    rows = store.item_neighbors(source="itemcf", seed_items=["s1", "s2"], limit_per_seed=999)

    assert rows[0].item_id == "i1"
    command, sql = calls[0]
    assert "JSON_TABLE" in sql
    assert "JSON_OBJECT" in sql
    assert "LIMIT" not in sql
    assert "rn <= 500" in sql
    assert "MYSQL_PWD=\"$MYSQL_PASSWORD\" mysql" in command[-1]
    assert "rs_agent_dev_only" not in " ".join(command)


def test_category_candidates_uses_json_merge_patch_bucket_metadata() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        payload = {"source": "category", "parent_asin": "i1", "score": 1.0, "metadata": {"category_bucket": "Books"}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = MysqlCandidateStore(runner=runner)
    rows = store.category_candidates(buckets=["Books"], limit_per_bucket=2)

    assert rows[0].item_id == "i1"
    assert "JSON_TABLE" in calls[0][1]
    assert "JSON_MERGE_PATCH" in calls[0][1]


def test_pool_candidates_checks_optional_table_before_query() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        if "information_schema.tables" in sql:
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"exists": False}) + "\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"parent_asin": "i1"}) + "\n", stderr="")

    store = MysqlCandidateStore(runner=runner)

    assert store.pool_candidates(user_id="u1") == []
    assert len(calls) == 1
    assert "pool_candidates" in calls[0][1]
