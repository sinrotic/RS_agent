from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from rs_core.data.mysql_dataset import (
    DockerMysqlDatasetStore,
    NoopMysqlDatasetStore,
    SafeMysqlDatasetStore,
    build_mysql_dataset_store_from_env,
    ensure_safe_mysql_dataset_store,
)

pytestmark = pytest.mark.unit


class FailingStore:
    def health(self) -> dict[str, Any]:
        raise RuntimeError("mysql://user:secret@host/db command stderr password")

    def summary(self) -> dict[str, Any]:
        raise RuntimeError("secret")

    def get_product(self, parent_asin: str) -> dict[str, Any] | None:
        raise RuntimeError("secret")

    def get_user_sequence(self, user_id: str, window_name: str = "recent_2y") -> dict[str, Any] | None:
        raise RuntimeError("secret")

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        raise RuntimeError("secret")


def test_env_factory_disabled_returns_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_MYSQL_DATASET_ENABLED", raising=False)

    store = build_mysql_dataset_store_from_env()

    assert isinstance(store, NoopMysqlDatasetStore)
    assert store.health()["status"] == "disabled"


def test_safe_store_fails_open_without_secret_leak() -> None:
    store = SafeMysqlDatasetStore(FailingStore())

    health = store.health()
    summary = store.summary()

    assert health == {
        "enabled": True,
        "status": "degraded",
        "backend": "mysql_dataset",
        "reason": "health_failed",
        "error_type": "RuntimeError",
    }
    assert summary["status"] == "degraded"
    assert store.get_product("B001") is None
    assert store.get_user_sequence("u1") is None
    assert store.get_user_recent_interactions("u1") == []
    leaked = json.dumps({"health": health, "summary": summary}, ensure_ascii=False)
    assert "secret" not in leaked
    assert "password" not in leaked
    assert "mysql://" not in leaked
    assert "stderr" not in leaked
    assert "command" not in leaked


def test_docker_store_uses_mysql_json_sql_and_clamps_limit() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        payload = {"user_id": "u1", "parent_asin": "B001"}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = DockerMysqlDatasetStore(runner=runner)

    rows = store.get_user_recent_interactions("u1", limit=999)

    assert rows == [{"user_id": "u1", "parent_asin": "B001"}]
    command, sql = calls[0]
    assert "JSON_OBJECT" in sql
    assert "LIMIT 200" in sql
    assert "MYSQL_PWD=\"$MYSQL_PASSWORD\" mysql" in command[-1]
    assert "rs_agent_dev_only" not in " ".join(command)


def test_docker_store_escapes_user_controlled_values_in_sql_literals() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"parent_asin": "x"}) + "\n", stderr="")

    malicious = "B001'; DROP TABLE products; --"
    store = DockerMysqlDatasetStore(runner=runner)

    assert store.get_product(malicious) == {"parent_asin": "x"}

    _command, sql = calls[0]
    assert "WHERE parent_asin = 'B001''; DROP TABLE products; --'" in sql


def test_docker_store_rejects_multi_statement_sql() -> None:
    store = DockerMysqlDatasetStore(runner=lambda command, sql: subprocess.CompletedProcess(command, 0, stdout="", stderr=""))

    with pytest.raises(ValueError, match="single SELECT"):
        store._json_query("SELECT JSON_OBJECT('ok', TRUE); SELECT SLEEP(10)")


def test_ensure_safe_mysql_dataset_store_wraps_raw_injected_store() -> None:
    store = ensure_safe_mysql_dataset_store(FailingStore())

    assert store.health()["status"] == "degraded"


def test_docker_store_summary_uses_information_schema_not_counts() -> None:
    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        assert "information_schema.tables" in sql
        assert "count(" not in sql.lower()
        payload = {"ok": True, "tables": {"products": True, "interactions": True, "user_sequences": False}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = DockerMysqlDatasetStore(runner=runner)

    assert store.summary()["tables"] == {"products": True, "interactions": True, "user_sequences": False}


def test_product_and_sequence_parse_json_output() -> None:
    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        if "FROM products" in sql:
            payload = {"parent_asin": "B001", "title": "Desk lamp"}
        else:
            payload = {"user_id": "u1", "window_name": "recent_2y", "recent_item_sequence": ["B001"]}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = DockerMysqlDatasetStore(runner=runner)

    assert store.get_product("B001") == {"parent_asin": "B001", "title": "Desk lamp"}
    assert store.get_user_sequence("u1") == {"user_id": "u1", "window_name": "recent_2y", "recent_item_sequence": ["B001"]}
