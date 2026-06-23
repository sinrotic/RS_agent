from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Protocol

DEFAULT_COMPOSE_FILE = "deploy/local/docker-compose.yml"
DEFAULT_POSTGRES_SERVICE = "postgres"
DEFAULT_DB_USER = "rs_agent"
DEFAULT_DB_NAME = "rs_agent"
DEFAULT_WINDOW_NAME = "recent_2y"
MAX_RECENT_INTERACTION_LIMIT = 200
ENABLE_ENV = "RS_POSTGRES_DATASET_ENABLED"

Runner = Callable[[list[str], str], subprocess.CompletedProcess[str]]


class PostgresDatasetStore(Protocol):
    def health(self) -> dict[str, Any]: ...

    def summary(self) -> dict[str, Any]: ...

    def get_product(self, parent_asin: str) -> dict[str, Any] | None: ...

    def get_user_sequence(self, user_id: str, window_name: str = DEFAULT_WINDOW_NAME) -> dict[str, Any] | None: ...

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]: ...


class NoopPostgresDatasetStore:
    def health(self) -> dict[str, Any]:
        return {"enabled": False, "status": "disabled", "backend": "noop"}

    def summary(self) -> dict[str, Any]:
        return {"enabled": False, "status": "disabled", "backend": "noop", "tables": {}}

    def get_product(self, parent_asin: str) -> dict[str, Any] | None:
        return None

    def get_user_sequence(self, user_id: str, window_name: str = DEFAULT_WINDOW_NAME) -> dict[str, Any] | None:
        return None

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return []


@dataclass
class SafePostgresDatasetStore:
    inner: PostgresDatasetStore

    def health(self) -> dict[str, Any]:
        try:
            return _public_status(self.inner.health())
        except Exception as exc:
            return _safe_error_status("health_failed", exc)

    def summary(self) -> dict[str, Any]:
        try:
            return _public_status(self.inner.summary())
        except Exception as exc:
            return _safe_error_status("summary_failed", exc)

    def get_product(self, parent_asin: str) -> dict[str, Any] | None:
        try:
            return self.inner.get_product(parent_asin)
        except Exception:
            return None

    def get_user_sequence(self, user_id: str, window_name: str = DEFAULT_WINDOW_NAME) -> dict[str, Any] | None:
        try:
            return self.inner.get_user_sequence(user_id, window_name)
        except Exception:
            return None

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return self.inner.get_user_recent_interactions(user_id, limit)
        except Exception:
            return []


@dataclass
class DockerPsqlPostgresDatasetStore:
    compose_file: str = DEFAULT_COMPOSE_FILE
    postgres_service: str = DEFAULT_POSTGRES_SERVICE
    db_user: str = DEFAULT_DB_USER
    db_name: str = DEFAULT_DB_NAME
    query_timeout_seconds: int = 10
    runner: Runner | None = None

    def health(self) -> dict[str, Any]:
        try:
            self._json_query("SELECT json_build_object('ok', true) AS result")
        except Exception as exc:
            return _safe_error_status("unavailable", exc, backend="docker_psql")
        return {"enabled": True, "status": "ok", "backend": "docker_psql"}

    def summary(self) -> dict[str, Any]:
        sql = """
        SELECT json_build_object(
            'ok', true,
            'tables', json_build_object(
                'products', to_regclass('public.products') IS NOT NULL,
                'interactions', to_regclass('public.interactions') IS NOT NULL,
                'user_sequences', to_regclass('public.user_sequences') IS NOT NULL
            )
        ) AS result
        """
        row = self._single_object(sql)
        tables = row.get("tables") if isinstance(row.get("tables"), dict) else {}
        return {"enabled": True, "status": "ok", "backend": "docker_psql", "tables": tables}

    def get_product(self, parent_asin: str) -> dict[str, Any] | None:
        sql = """
        SELECT json_build_object(
            'parent_asin', parent_asin,
            'title', title,
            'main_category', main_category,
            'categories', categories,
            'brand', brand,
            'price', price,
            'rating', rating,
            'description', description,
            'features', features,
            'metadata', metadata
        ) AS result
        FROM products
        WHERE parent_asin = :'parent_asin'
        LIMIT 1
        """
        return self._single_object_or_none(sql, {"parent_asin": parent_asin})

    def get_user_sequence(self, user_id: str, window_name: str = DEFAULT_WINDOW_NAME) -> dict[str, Any] | None:
        sql = """
        SELECT json_build_object(
            'user_id', user_id,
            'window_name', window_name,
            'recent_item_sequence', recent_item_sequence,
            'recent_positive_item_sequence', recent_positive_item_sequence,
            'recent_strong_positive_item_sequence', recent_strong_positive_item_sequence,
            'metadata', metadata
        ) AS result
        FROM user_sequences
        WHERE user_id = :'user_id' AND window_name = :'window_name'
        LIMIT 1
        """
        return self._single_object_or_none(sql, {"user_id": user_id, "window_name": window_name})

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = clamp_recent_interaction_limit(limit)
        sql = """
        SELECT json_build_object(
            'user_id', user_id,
            'parent_asin', parent_asin,
            'event_type', event_type,
            'event_time', event_time,
            'rating', rating,
            'label_binary', label_binary,
            'split', split,
            'source', source,
            'metadata', metadata
        ) AS result
        FROM interactions
        WHERE user_id = :'user_id'
        ORDER BY event_time DESC NULLS LAST, id DESC
        LIMIT :'limit'
        """
        rows = self._json_query(sql, {"user_id": user_id, "limit": str(safe_limit)})
        return [row for row in rows if isinstance(row, dict)]

    def _single_object(self, sql: str, variables: dict[str, str] | None = None) -> dict[str, Any]:
        row = self._single_object_or_none(sql, variables)
        if row is None:
            raise RuntimeError("postgres query returned no rows")
        return row

    def _single_object_or_none(self, sql: str, variables: dict[str, str] | None = None) -> dict[str, Any] | None:
        rows = self._json_query(sql, variables)
        if not rows:
            return None
        row = rows[0]
        return row if isinstance(row, dict) else None

    def _json_query(self, sql: str, variables: dict[str, str] | None = None) -> list[Any]:
        _ensure_select_only(sql)
        command = self._command(variables)
        proc = self._run(command, sql)
        if proc.returncode != 0:
            raise RuntimeError("postgres query failed")
        return parse_psql_json_output(proc.stdout)

    def _command(self, variables: dict[str, str] | None = None) -> list[str]:
        command = [
            "docker",
            "compose",
            "-f",
            self.compose_file,
            "--profile",
            "postgres",
            "exec",
            "-T",
            self.postgres_service,
            "psql",
            "-U",
            self.db_user,
            "-d",
            self.db_name,
            "-v",
            "ON_ERROR_STOP=1",
            "-X",
            "-q",
            "-t",
            "-A",
            "-F",
            "",
        ]
        for key, value in sorted((variables or {}).items()):
            command.extend(["-v", f"{key}={value}"])
        return command

    def _run(self, command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        if self.runner is not None:
            return self.runner(command, sql)
        return subprocess.run(
            command,
            input=sql,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=self.query_timeout_seconds,
            check=False,
        )


def build_postgres_dataset_store_from_env() -> PostgresDatasetStore:
    if os.environ.get(ENABLE_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return NoopPostgresDatasetStore()
    store = DockerPsqlPostgresDatasetStore(
        compose_file=os.environ.get("RS_POSTGRES_COMPOSE_FILE", DEFAULT_COMPOSE_FILE),
        postgres_service=os.environ.get("RS_POSTGRES_SERVICE", DEFAULT_POSTGRES_SERVICE),
        db_user=os.environ.get("RS_POSTGRES_USER", DEFAULT_DB_USER),
        db_name=os.environ.get("RS_POSTGRES_DB", DEFAULT_DB_NAME),
        query_timeout_seconds=_env_int("RS_POSTGRES_QUERY_TIMEOUT_SECONDS", 10),
    )
    return SafePostgresDatasetStore(store)


def ensure_safe_postgres_dataset_store(store: PostgresDatasetStore) -> PostgresDatasetStore:
    if isinstance(store, (NoopPostgresDatasetStore, SafePostgresDatasetStore)):
        return store
    return SafePostgresDatasetStore(store)


def clamp_recent_interaction_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, MAX_RECENT_INTERACTION_LIMIT))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def parse_psql_json_output(output: str) -> list[Any]:
    rows: list[Any] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _ensure_select_only(sql: str) -> None:
    normalized = sql.strip().lower()
    if not normalized.startswith("select"):
        raise ValueError("postgres dataset wrapper allows SELECT only")
    if ";" in normalized:
        raise ValueError("postgres dataset wrapper allows single SELECT statements only")
    forbidden = ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "copy ", "create ", "grant ", "revoke ")
    if any(token in normalized for token in forbidden):
        raise ValueError("postgres dataset wrapper allows read-only queries only")


def _public_status(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload)
    for key in ("dsn", "password", "url", "stderr", "command"):
        safe.pop(key, None)
    return safe


def _safe_error_status(reason: str, exc: Exception, backend: str = "postgres_dataset") -> dict[str, Any]:
    return {
        "enabled": True,
        "status": "degraded",
        "backend": backend,
        "reason": reason,
        "error_type": type(exc).__name__,
    }
