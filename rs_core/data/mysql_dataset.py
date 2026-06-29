from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Protocol

DEFAULT_COMPOSE_FILE = "deploy/local/docker-compose.yml"
DEFAULT_MYSQL_SERVICE = "mysql"
DEFAULT_DB_USER = "rs_agent"
DEFAULT_DB_PASSWORD = "rs_agent_dev_only"
DEFAULT_DB_NAME = "rs_agent"
DEFAULT_WINDOW_NAME = "recent_2y"
MAX_RECENT_INTERACTION_LIMIT = 200
ENABLE_ENV = "RS_MYSQL_DATASET_ENABLED"

Runner = Callable[[list[str], str], subprocess.CompletedProcess[str]]


class MysqlDatasetStore(Protocol):
    def health(self) -> dict[str, Any]: ...

    def summary(self) -> dict[str, Any]: ...

    def get_product(self, parent_asin: str) -> dict[str, Any] | None: ...

    def get_user_sequence(self, user_id: str, window_name: str = DEFAULT_WINDOW_NAME) -> dict[str, Any] | None: ...

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]: ...


class NoopMysqlDatasetStore:
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
class SafeMysqlDatasetStore:
    inner: MysqlDatasetStore

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
class DockerMysqlDatasetStore:
    compose_file: str = DEFAULT_COMPOSE_FILE
    mysql_service: str = DEFAULT_MYSQL_SERVICE
    db_user: str = DEFAULT_DB_USER
    db_password: str = DEFAULT_DB_PASSWORD
    db_name: str = DEFAULT_DB_NAME
    query_timeout_seconds: int = 10
    runner: Runner | None = None

    def health(self) -> dict[str, Any]:
        try:
            self._json_query("SELECT JSON_OBJECT('ok', TRUE) AS result")
        except Exception as exc:
            return _safe_error_status("unavailable", exc, backend="docker_mysql")
        return {"enabled": True, "status": "ok", "backend": "docker_mysql"}

    def summary(self) -> dict[str, Any]:
        sql = """
        SELECT JSON_OBJECT(
            'ok', TRUE,
            'tables', JSON_OBJECT(
                'products', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'products'),
                'interactions', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'interactions'),
                'user_sequences', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'user_sequences')
            )
        ) AS result
        """
        row = self._single_object(sql)
        tables = row.get("tables") if isinstance(row.get("tables"), dict) else {}
        return {"enabled": True, "status": "ok", "backend": "docker_mysql", "tables": tables}

    def get_product(self, parent_asin: str) -> dict[str, Any] | None:
        sql = f"""
        SELECT JSON_OBJECT(
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
        WHERE parent_asin = {_sql_text(parent_asin)}
        LIMIT 1
        """
        return self._single_object_or_none(sql)

    def get_user_sequence(self, user_id: str, window_name: str = DEFAULT_WINDOW_NAME) -> dict[str, Any] | None:
        sql = f"""
        SELECT JSON_OBJECT(
            'user_id', user_id,
            'window_name', window_name,
            'recent_item_sequence', recent_item_sequence,
            'recent_positive_item_sequence', recent_positive_item_sequence,
            'recent_strong_positive_item_sequence', recent_strong_positive_item_sequence,
            'metadata', metadata
        ) AS result
        FROM user_sequences
        WHERE user_id = {_sql_text(user_id)} AND window_name = {_sql_text(window_name)}
        LIMIT 1
        """
        return self._single_object_or_none(sql)

    def get_user_recent_interactions(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        safe_limit = clamp_recent_interaction_limit(limit)
        sql = f"""
        SELECT JSON_OBJECT(
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
        WHERE user_id = {_sql_text(user_id)}
        ORDER BY event_time IS NULL, event_time DESC, id DESC
        LIMIT {safe_limit}
        """
        rows = self._json_query(sql)
        return [row for row in rows if isinstance(row, dict)]

    def _single_object(self, sql: str) -> dict[str, Any]:
        row = self._single_object_or_none(sql)
        if row is None:
            raise RuntimeError("mysql query returned no rows")
        return row

    def _single_object_or_none(self, sql: str) -> dict[str, Any] | None:
        rows = self._json_query(sql)
        if not rows:
            return None
        row = rows[0]
        return row if isinstance(row, dict) else None

    def _json_query(self, sql: str) -> list[Any]:
        _ensure_select_only(sql)
        command = self._command()
        proc = self._run(command, sql)
        if proc.returncode != 0:
            raise RuntimeError("mysql query failed")
        return parse_mysql_json_output(proc.stdout)

    def _command(self) -> list[str]:
        mysql_command = (
            'MYSQL_PWD="$MYSQL_PASSWORD" mysql '
            '--batch --raw --skip-column-names --default-character-set=utf8mb4 '
            '-u "$MYSQL_USER" "$MYSQL_DATABASE"'
        )
        return [
            "docker",
            "compose",
            "-f",
            self.compose_file,
            "--profile",
            "mysql",
            "exec",
            "-T",
            self.mysql_service,
            "sh",
            "-lc",
            mysql_command,
        ]

    def _run(self, command: list[str], sql: str) -> subprocess.CompletedProcess[str]:
        if self.runner is not None:
            return self.runner(command, sql)
        env = dict(os.environ)
        if self.db_password:
            env["MYSQL_PWD"] = self.db_password
        return subprocess.run(
            command,
            input=sql,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=self.query_timeout_seconds,
            check=False,
            env=env,
        )


def build_mysql_dataset_store_from_env() -> MysqlDatasetStore:
    if os.environ.get(ENABLE_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return NoopMysqlDatasetStore()
    store = DockerMysqlDatasetStore(
        compose_file=os.environ.get("RS_MYSQL_COMPOSE_FILE", DEFAULT_COMPOSE_FILE),
        mysql_service=os.environ.get("RS_MYSQL_SERVICE", DEFAULT_MYSQL_SERVICE),
        db_user=os.environ.get("RS_MYSQL_USER", DEFAULT_DB_USER),
        db_password=os.environ.get("RS_MYSQL_PASSWORD", DEFAULT_DB_PASSWORD),
        db_name=os.environ.get("RS_MYSQL_DB", DEFAULT_DB_NAME),
        query_timeout_seconds=_env_int("RS_MYSQL_QUERY_TIMEOUT_SECONDS", 10),
    )
    return SafeMysqlDatasetStore(store)


def ensure_safe_mysql_dataset_store(store: MysqlDatasetStore) -> MysqlDatasetStore:
    if isinstance(store, (NoopMysqlDatasetStore, SafeMysqlDatasetStore)):
        return store
    return SafeMysqlDatasetStore(store)


def clamp_recent_interaction_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = 50
    return max(1, min(value, MAX_RECENT_INTERACTION_LIMIT))


def parse_mysql_json_output(output: str) -> list[Any]:
    rows: list[Any] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _ensure_select_only(sql: str) -> None:
    normalized = _strip_quoted_literals(sql.strip().lower())
    if not normalized.startswith("select"):
        raise ValueError("mysql dataset wrapper allows SELECT only")
    if ";" in normalized:
        raise ValueError("mysql dataset wrapper allows single SELECT statements only")
    forbidden = ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "copy ", "create ", "grant ", "revoke ")
    if any(token in normalized for token in forbidden):
        raise ValueError("mysql dataset wrapper allows read-only queries only")


def _strip_quoted_literals(sql: str) -> str:
    result: list[str] = []
    in_quote = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'":
            result.append("''")
            in_quote = not in_quote
            index += 1
            while in_quote and index < len(sql):
                if sql[index] == "'":
                    if index + 1 < len(sql) and sql[index + 1] == "'":
                        index += 2
                        continue
                    in_quote = False
                    index += 1
                    break
                index += 1
            continue
        if not in_quote:
            result.append(char)
        index += 1
    return "".join(result)


def _sql_text(value: Any) -> str:
    text = str(value or "")
    return "'" + text.replace("'", "''").replace("\\", "\\\\") + "'"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _public_status(payload: dict[str, Any]) -> dict[str, Any]:
    safe = dict(payload)
    for key in ("dsn", "password", "url", "stderr", "command"):
        safe.pop(key, None)
    return safe


def _safe_error_status(reason: str, exc: Exception, backend: str = "mysql_dataset") -> dict[str, Any]:
    return {
        "enabled": True,
        "status": "degraded",
        "backend": backend,
        "reason": reason,
        "error_type": type(exc).__name__,
    }
