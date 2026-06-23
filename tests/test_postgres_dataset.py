from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from rs_core.common.io import write_jsonl
from rs_core.data.postgres_dataset import (
    DockerPsqlPostgresDatasetStore,
    NoopPostgresDatasetStore,
    SafePostgresDatasetStore,
    build_postgres_dataset_store_from_env,
    ensure_safe_postgres_dataset_store,
)
from rs_core.serving.application.recommendation_service import RecommendationService
from rs_core.serving.schemas import ReadinessResponse

pytestmark = pytest.mark.unit


class FailingStore:
    def health(self) -> dict[str, Any]:
        raise RuntimeError("postgresql://user:secret@host/db")

    def summary(self) -> dict[str, Any]:
        raise RuntimeError("secret")

    def get_product(self, parent_asin: str) -> dict[str, Any] | None:
        raise RuntimeError("secret")

    def get_user_sequence(self, user_id: str, window_name: str = "recent_2y") -> dict[str, Any] | None:
        raise RuntimeError("secret")

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        raise RuntimeError("secret")


class ReadyStore:
    def health(self) -> dict[str, Any]:
        return {"enabled": True, "status": "ok", "backend": "test"}

    def summary(self) -> dict[str, Any]:
        return {"enabled": True, "status": "ok", "backend": "test", "tables": {}}

    def get_product(self, parent_asin: str) -> dict[str, Any] | None:
        return None

    def get_user_sequence(self, user_id: str, window_name: str = "recent_2y") -> dict[str, Any] | None:
        return None

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return []


def test_env_factory_disabled_returns_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RS_POSTGRES_DATASET_ENABLED", raising=False)

    store = build_postgres_dataset_store_from_env()

    assert isinstance(store, NoopPostgresDatasetStore)
    assert store.health()["status"] == "disabled"


def test_safe_store_fails_open_without_secret_leak() -> None:
    store = SafePostgresDatasetStore(FailingStore())

    assert store.health() == {
        "enabled": True,
        "status": "degraded",
        "backend": "postgres_dataset",
        "reason": "health_failed",
        "error_type": "RuntimeError",
    }
    assert store.summary()["status"] == "degraded"
    assert store.get_product("B001") is None
    assert store.get_user_sequence("u1") is None
    assert store.get_user_recent_interactions("u1") == []


def test_docker_store_parses_json_and_clamps_limit() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        payload = {"user_id": "u1", "parent_asin": "B001"}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = DockerPsqlPostgresDatasetStore(runner=runner)

    rows = store.get_user_recent_interactions("u1", limit=999)

    assert rows == [{"user_id": "u1", "parent_asin": "B001"}]
    command, sql = calls[0]
    assert "SELECT" in sql
    assert "LIMIT :'limit'" in sql
    assert "limit=200" in command


def test_docker_store_uses_psql_literals_for_user_controlled_values() -> None:
    calls: list[tuple[list[str], str]] = []

    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        calls.append((command, sql))
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"parent_asin": "x"}) + "\n", stderr="")

    malicious = "B001'; DROP TABLE products; --"
    store = DockerPsqlPostgresDatasetStore(runner=runner)

    assert store.get_product(malicious) == {"parent_asin": "x"}

    command, sql = calls[0]
    assert "WHERE parent_asin = :'parent_asin'" in sql
    assert malicious not in sql
    assert f"parent_asin={malicious}" in command


def test_docker_store_rejects_multi_statement_sql() -> None:
    store = DockerPsqlPostgresDatasetStore(runner=lambda command, sql: subprocess.CompletedProcess(command, 0, stdout="", stderr=""))

    with pytest.raises(ValueError, match="single SELECT"):
        store._json_query("SELECT json_build_object('ok', true); SELECT pg_sleep(10)")


def test_ensure_safe_postgres_dataset_store_wraps_raw_injected_store() -> None:
    store = ensure_safe_postgres_dataset_store(FailingStore())

    assert store.health()["status"] == "degraded"


def test_docker_store_summary_uses_table_presence_not_counts() -> None:
    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        assert "to_regclass" in sql
        assert "count(" not in sql.lower()
        payload = {"ok": True, "tables": {"products": True, "interactions": True, "user_sequences": False}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = DockerPsqlPostgresDatasetStore(runner=runner)

    assert store.summary()["tables"] == {"products": True, "interactions": True, "user_sequences": False}


def test_product_and_sequence_parse_json_output() -> None:
    def runner(command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        if "FROM products" in sql:
            payload = {"parent_asin": "B001", "title": "Desk lamp"}
        else:
            payload = {"user_id": "u1", "window_name": "recent_2y", "recent_item_sequence": ["B001"]}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload) + "\n", stderr="")

    store = DockerPsqlPostgresDatasetStore(runner=runner)

    assert store.get_product("B001") == {"parent_asin": "B001", "title": "Desk lamp"}
    assert store.get_user_sequence("u1") == {"user_id": "u1", "window_name": "recent_2y", "recent_item_sequence": ["B001"]}


def test_readiness_schema_accepts_postgres_dataset() -> None:
    payload = {
        "status": "ready",
        "service": "rs-agent-serving",
        "mode": "demo-compatible",
        "session_state": "single_process_in_memory",
        "online_route": {},
        "postgres_dataset": {"enabled": True, "status": "ok", "backend": "test"},
    }

    response = ReadinessResponse(**payload)

    assert response.postgres_dataset == {"enabled": True, "status": "ok", "backend": "test"}


def test_recommendation_service_readiness_injects_postgres_dataset(tmp_path: Path) -> None:
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1, postgres_dataset_store=ReadyStore())

    readiness = service.readiness()

    assert readiness["postgres_dataset"] == {"enabled": True, "status": "ok", "backend": "test"}


def test_recommendation_service_readiness_fails_open_for_injected_store(tmp_path: Path) -> None:
    service = RecommendationService(str(_write_serving_fixture(tmp_path)), limit_users=1, postgres_dataset_store=FailingStore())

    readiness = service.readiness()

    assert readiness["postgres_dataset"]["status"] == "degraded"
    assert "secret" not in json.dumps(readiness["postgres_dataset"])


def _write_serving_fixture(root: Path) -> Path:
    clean = root / "clean"
    views = root / "views"
    clean.mkdir()
    views.mkdir()
    write_jsonl(clean / "user_sequences.train.jsonl", [{"user_id": "u1", "recent_item_sequence": ["seed"], "recent_positive_item_sequence": ["seed"]}])
    write_jsonl(clean / "canonical_interactions.valid.jsonl", [{"user_id": "u1", "parent_asin": "item_1", "label_binary": 1}])
    write_jsonl(views / "popular_recall.jsonl", [{"parent_asin": "item_1", "category": "Office", "pop_score": 1}])
    write_jsonl(views / "itemcf_recall_weak.jsonl", [])
    write_jsonl(views / "itemcf_recall_strong.jsonl", [])
    write_jsonl(views / "category_recall_items.jsonl", [{"parent_asin": "seed", "main_category": "Office"}])
    write_jsonl(views / "category_top_items.jsonl", [])
    config = root / "config.yaml"
    config.write_text(json.dumps({
        "clean_dir": str(clean),
        "views_dir": str(views),
        "output_dir": str(root / "out"),
        "report_path": str(root / "report.md"),
        "top_k": 3,
        "candidate_pool_size": 10,
        "popular_fallback_count": 3,
        "rank_weights": {"popular": 1.0, "itemcf_weak": 1.0, "category": 1.0},
    }), encoding="utf-8")
    return config
