from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rs_core.data.adapters import LocalFileAdapter, MilvusAdapter, MinioAdapter, MysqlAdapter, RedisAdapter
from rs_core.data.clients import DataClient
from rs_core.data.engine import DataAssetEngine

pytestmark = pytest.mark.unit


class BoundClient:
    pass


class FailingStore:
    def health(self) -> dict[str, str]:
        raise RuntimeError("mysql://user:secret@host/db")


class ReadyStore:
    def health(self) -> dict[str, object]:
        return {"enabled": True, "status": "ok", "backend": "test"}


class DisabledStore:
    def health(self) -> dict[str, object]:
        return {"enabled": False, "status": "disabled", "backend": "test"}


def test_local_file_adapter_readiness_is_secret_safe(tmp_path: Path) -> None:
    adapter = LocalFileAdapter(tmp_path)

    readiness = adapter.readiness()

    assert readiness == {
        "name": "local_files",
        "backend": "local_file",
        "enabled": True,
        "status": "ok",
        "reason": "ready",
        "read_only": True,
        "config_ref": "project_root",
        "client_bound": False,
    }
    assert str(tmp_path) not in json.dumps(readiness)


def test_local_file_adapter_disabled_and_missing_root_are_public_safe(tmp_path: Path) -> None:
    disabled = LocalFileAdapter(tmp_path, enabled=False).readiness()
    missing = LocalFileAdapter(tmp_path / "missing").readiness()

    assert disabled["status"] == "disabled"
    assert disabled["reason"] == "adapter_disabled"
    assert missing["status"] == "degraded"
    assert missing["reason"] == "root_missing"
    assert str(tmp_path) not in json.dumps({"disabled": disabled, "missing": missing})


def test_remote_adapters_report_disabled_or_unbound_without_secret_leak() -> None:
    mysql = MysqlAdapter(config_ref="mysql://user:secret-mysql@example.test/db", enabled=True)
    redis = RedisAdapter(config_ref="redis://secret-token@localhost:6379/0", enabled=True)
    minio = MinioAdapter(config_ref="https://secret-minio-token@example.test", enabled=True)

    mysql_readiness = mysql.readiness()
    redis_readiness = redis.readiness()
    minio_readiness = minio.readiness()

    assert mysql_readiness["status"] == "degraded"
    assert mysql_readiness["reason"] == "client_unbound"
    assert mysql_readiness["config_ref"] == "configured"
    assert redis_readiness["status"] == "degraded"
    assert redis_readiness["reason"] == "client_unbound"
    assert redis_readiness["config_ref"] == "configured"
    assert minio_readiness["status"] == "degraded"
    assert minio_readiness["reason"] == "client_unbound"
    assert minio_readiness["config_ref"] == "configured"
    rendered = json.dumps({"mysql": mysql_readiness, "redis": redis_readiness, "minio": minio_readiness})
    assert "secret-mysql" not in rendered
    assert "secret-token" not in rendered
    assert "secret-minio-token" not in rendered


def test_mysql_adapter_uses_safe_health_without_full_summary() -> None:
    ready = MysqlAdapter(store=ReadyStore(), enabled=True).readiness()
    disabled = MysqlAdapter(store=DisabledStore(), enabled=True).readiness()
    failing = MysqlAdapter(store=FailingStore(), enabled=True).readiness()

    assert ready["status"] == "ok"
    assert ready["reason"] == "ready"
    assert ready["client_bound"] is True
    assert disabled["enabled"] is False
    assert disabled["status"] == "disabled"
    assert disabled["reason"] == "adapter_disabled"
    assert failing["status"] == "degraded"
    assert failing["reason"] == "health_failed"
    assert failing["error_type"] == "RuntimeError"
    assert "secret" not in json.dumps(failing).lower()


def test_bound_remote_adapter_reports_ok() -> None:
    adapter = RedisAdapter(client=BoundClient(), enabled=True)

    readiness = adapter.readiness()

    assert readiness["status"] == "ok"
    assert readiness["reason"] == "ready"
    assert readiness["client_bound"] is True


def test_milvus_adapter_projects_config_and_builds_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RS_MILVUS_URI", "unit.db")
    adapter = MilvusAdapter.from_config({"enabled": True, "uri": "config.db", "collection_name": "rag_chunks"})

    readiness = adapter.readiness()

    assert adapter.connection_config()["uri"] == "config.db"
    assert readiness["status"] == "degraded"
    assert readiness["reason"] == "client_unbound"
    assert readiness["config_ref"] == "env:RS_MILVUS_*"
    assert readiness["client_bound"] is False


def test_data_asset_engine_readiness_projects_adapter_statuses(tmp_path: Path) -> None:
    engine = DataAssetEngine(data_client=DataClient(project_root=tmp_path))

    readiness = engine.readiness()

    assert readiness["engine"] == "DataAssetEngine"
    assert readiness["status"] == "ok"
    assert readiness["storage"]["local_file"]["status"] == "ok"
    assert readiness["storage"]["mysql"]["status"] == "disabled"
    assert readiness["storage"]["redis"]["status"] == "disabled"
    assert readiness["storage"]["minio"]["status"] == "disabled"
    assert str(tmp_path) not in json.dumps(readiness)


def test_data_asset_engine_readiness_degrades_when_enabled_adapter_unbound(tmp_path: Path) -> None:
    engine = DataAssetEngine(
        data_client=DataClient(project_root=tmp_path),
        redis_adapter=RedisAdapter(enabled=True),
    )

    readiness = engine.readiness()

    assert readiness["status"] == "degraded"
    assert readiness["storage"]["redis"]["status"] == "degraded"
    assert readiness["storage"]["redis"]["reason"] == "client_unbound"


def test_data_worker_readiness_module_execution_is_public_safe() -> None:
    command = [sys.executable, "-m", "rs_core.data.runtime.worker", "readiness"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)

    readiness = json.loads(result.stdout)

    assert readiness["engine"] == "DataAssetEngine"
    assert readiness["storage"]["local_file"]["config_ref"] == "project_root"
    assert "RuntimeWarning" not in result.stderr
    rendered = json.dumps(readiness)
    assert "secret" not in rendered.lower()
    assert "D:" not in rendered
