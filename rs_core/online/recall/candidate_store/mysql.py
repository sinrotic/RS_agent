from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from rs_core.data.mysql_dataset import (
    DEFAULT_COMPOSE_FILE,
    DEFAULT_DB_NAME,
    DEFAULT_DB_PASSWORD,
    DEFAULT_DB_USER,
    DEFAULT_MYSQL_SERVICE,
    parse_mysql_json_output,
)
from rs_core.online.recall.candidate_store.base import (
    MAX_QUERY_LIMIT,
    CandidateStore,
    NoopCandidateStore,
    SafeCandidateStore,
    clamp_limit,
    safe_error_status,
)
from rs_core.online.recall.candidate_store.schema import row_to_recall_candidate
from rs_core.common.recsys_types import RecallCandidate

ENABLE_ENV = "RS_MYSQL_CANDIDATE_STORE_ENABLED"
Runner = Callable[[list[str], str], subprocess.CompletedProcess[str]]


@dataclass
class MysqlCandidateStore:
    compose_file: str = DEFAULT_COMPOSE_FILE
    mysql_service: str = DEFAULT_MYSQL_SERVICE
    db_user: str = DEFAULT_DB_USER
    db_password: str = DEFAULT_DB_PASSWORD
    db_name: str = DEFAULT_DB_NAME
    query_timeout_seconds: int = 10
    runner: Runner | None = None

    def health(self) -> dict[str, Any]:
        try:
            row = self._single_object(
                """
                SELECT JSON_OBJECT(
                    'ok', TRUE,
                    'tables', JSON_OBJECT(
                        'item_neighbors', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'item_neighbors'),
                        'usercf_candidates', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'usercf_candidates'),
                        'popular_candidates', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'popular_candidates'),
                        'category_candidates', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'category_candidates'),
                        'user_category_profiles', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'user_category_profiles'),
                        'pool_candidates', EXISTS(SELECT 1 FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'pool_candidates')
                    )
                ) AS result
                """
            )
        except Exception as exc:
            return safe_error_status("unavailable", exc, backend="docker_mysql")
        tables = row.get("tables") if isinstance(row.get("tables"), dict) else {}
        required = ("item_neighbors", "usercf_candidates", "popular_candidates", "category_candidates")
        status = "ok" if all(tables.get(name) for name in required) else "degraded"
        return {"enabled": True, "status": status, "backend": "docker_mysql", "tables": tables}

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]:
        seeds = [str(item) for item in seed_items if str(item or "").strip()]
        if not seeds:
            return []
        safe_limit = _clamp_limit(limit_per_seed)
        sql = f"""
        WITH seeds AS (
            SELECT seed.src_item_id
            FROM JSON_TABLE(
                CAST({_sql_json_array(seeds)} AS JSON),
                '$[*]' COLUMNS (src_item_id VARCHAR(255) PATH '$')
            ) AS seed
        ), ranked AS (
            SELECT
                n.source,
                n.src_item_id,
                n.dst_item_id AS parent_asin,
                n.score,
                n.`rank`,
                n.category,
                n.metadata,
                n.artifact_id,
                ROW_NUMBER() OVER (PARTITION BY n.src_item_id ORDER BY n.`rank` IS NULL, n.`rank`, n.score DESC, n.dst_item_id) AS rn
            FROM item_neighbors n
            JOIN seeds s ON s.src_item_id = n.src_item_id
            WHERE n.source = {_sql_text(source)}
        )
        SELECT JSON_OBJECT(
            'source', source,
            'src_item_id', src_item_id,
            'parent_asin', parent_asin,
            'score', score,
            'rank', `rank`,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM ranked
        WHERE rn <= {safe_limit}
        ORDER BY src_item_id, rn
        """
        rows = self._json_query(sql)
        return _rows_to_candidates(rows, default_source=source)

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]:
        if not str(user_id or "").strip():
            return []
        sql = f"""
        SELECT JSON_OBJECT(
            'source', source,
            'parent_asin', parent_asin,
            'score', score,
            'rank', `rank`,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM usercf_candidates
        WHERE source = {_sql_text(source)} AND user_id = {_sql_text(user_id)}
        ORDER BY `rank` IS NULL, `rank`, score DESC, parent_asin
        LIMIT {_clamp_limit(limit)}
        """
        rows = self._json_query(sql)
        return _rows_to_candidates(rows, default_source=source)

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]:
        sql = f"""
        SELECT JSON_OBJECT(
            'source', 'popular',
            'parent_asin', parent_asin,
            'score', score,
            'rank', `rank`,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM popular_candidates
        WHERE scope = {_sql_text(scope)} AND bucket = {_sql_text(bucket)}
        ORDER BY `rank` IS NULL, `rank`, score DESC, parent_asin
        LIMIT {_clamp_limit(limit)}
        """
        rows = self._json_query(sql)
        return _rows_to_candidates(rows, default_source="popular")

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]:
        clean_buckets = [str(bucket) for bucket in buckets if str(bucket or "").strip()]
        if not clean_buckets:
            return []
        safe_limit = _clamp_limit(limit_per_bucket)
        sql = f"""
        WITH buckets AS (
            SELECT bucket_row.bucket
            FROM JSON_TABLE(
                CAST({_sql_json_array(clean_buckets)} AS JSON),
                '$[*]' COLUMNS (bucket VARCHAR(255) PATH '$')
            ) AS bucket_row
        ), ranked AS (
            SELECT
                c.bucket,
                c.parent_asin,
                c.score,
                c.`rank`,
                c.category,
                c.metadata,
                c.artifact_id,
                ROW_NUMBER() OVER (PARTITION BY c.bucket ORDER BY c.`rank` IS NULL, c.`rank`, c.score DESC, c.parent_asin) AS rn
            FROM category_candidates c
            JOIN buckets b ON b.bucket = c.bucket
        )
        SELECT JSON_OBJECT(
            'source', 'category',
            'parent_asin', parent_asin,
            'score', score,
            'rank', `rank`,
            'category', category,
            'metadata', JSON_MERGE_PATCH(COALESCE(metadata, JSON_OBJECT()), JSON_OBJECT('category_bucket', bucket)),
            'artifact_id', artifact_id
        ) AS result
        FROM ranked
        WHERE rn <= {safe_limit}
        ORDER BY bucket, rn
        """
        rows = self._json_query(sql)
        return _rows_to_candidates(rows, default_source="category")

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
        if not str(user_id or "").strip():
            return []
        sql = f"""
        SELECT JSON_OBJECT('bucket', bucket) AS result
        FROM user_category_profiles
        WHERE user_id = {_sql_text(user_id)}
        ORDER BY `rank` IS NULL, `rank`, score DESC, bucket
        LIMIT {_clamp_limit(limit, maximum=50)}
        """
        rows = self._json_query(sql)
        return [str(row.get("bucket")) for row in rows if isinstance(row, dict) and row.get("bucket")]

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]:
        if not str(user_id or "").strip():
            return []
        if not self._table_exists("pool_candidates"):
            return []
        sql = f"""
        SELECT JSON_OBJECT(
            'source', source,
            'parent_asin', parent_asin,
            'score', score,
            'rank', `rank`,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM pool_candidates
        WHERE user_id = {_sql_text(user_id)}
        ORDER BY `rank` IS NULL, `rank`, score DESC, parent_asin
        LIMIT {_clamp_limit(limit)}
        """
        rows = self._json_query(sql)
        return _rows_to_candidates(rows, default_source="pool500_fallback")

    def _table_exists(self, table_name: str) -> bool:
        sql = f"""
        SELECT JSON_OBJECT(
            'exists', EXISTS(
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = {_sql_text(table_name)}
            )
        ) AS result
        """
        row = self._single_object(sql)
        return bool(row.get("exists"))

    def _single_object(self, sql: str) -> dict[str, Any]:
        rows = self._json_query(sql)
        if not rows:
            raise RuntimeError("mysql candidate store query returned no rows")
        row = rows[0]
        return row if isinstance(row, dict) else {}

    def _json_query(self, sql: str) -> list[Any]:
        _ensure_select_only(sql)
        command = self._command()
        proc = self._run(command, sql)
        if proc.returncode != 0:
            raise RuntimeError("mysql candidate store query failed")
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
        return subprocess.run(command, input=sql, text=True, encoding="utf-8", capture_output=True, timeout=self.query_timeout_seconds, check=False, env=env)


def build_mysql_candidate_store_from_env() -> CandidateStore:
    if os.environ.get(ENABLE_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return NoopCandidateStore()
    store = MysqlCandidateStore(
        compose_file=os.environ.get("RS_MYSQL_COMPOSE_FILE", DEFAULT_COMPOSE_FILE),
        mysql_service=os.environ.get("RS_MYSQL_SERVICE", DEFAULT_MYSQL_SERVICE),
        db_user=os.environ.get("RS_MYSQL_USER", DEFAULT_DB_USER),
        db_password=os.environ.get("RS_MYSQL_PASSWORD", DEFAULT_DB_PASSWORD),
        db_name=os.environ.get("RS_MYSQL_DB", DEFAULT_DB_NAME),
        query_timeout_seconds=_env_int("RS_MYSQL_QUERY_TIMEOUT_SECONDS", 10),
    )
    return SafeCandidateStore(store)


def _rows_to_candidates(rows: list[Any], *, default_source: str) -> list[RecallCandidate]:
    candidates: list[RecallCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = row_to_recall_candidate(row, default_source=default_source)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _ensure_select_only(sql: str) -> None:
    normalized = _strip_quoted_literals(sql.strip().lower())
    if not normalized.startswith(("select", "with")):
        raise ValueError("mysql candidate store allows SELECT/CTE queries only")
    if ";" in normalized:
        raise ValueError("mysql candidate store allows single SELECT statements only")
    forbidden = ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "copy ", "create ", "grant ", "revoke ")
    if any(token in normalized for token in forbidden):
        raise ValueError("mysql candidate store allows read-only queries only")


def _strip_quoted_literals(sql: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'":
            result.append("''")
            index += 1
            while index < len(sql):
                if sql[index] == "'":
                    if index + 1 < len(sql) and sql[index + 1] == "'":
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _sql_text(value: Any) -> str:
    text = str(value or "")
    return "'" + text.replace("'", "''").replace("\\", "\\\\") + "'"


def _sql_json_array(values: list[str]) -> str:
    return _sql_text(json.dumps(values, ensure_ascii=False))


def _clamp_limit(value: int, *, maximum: int = MAX_QUERY_LIMIT) -> int:
    return clamp_limit(value, maximum=maximum)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
