from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from rs_core.data.postgres_dataset import (
    DEFAULT_COMPOSE_FILE,
    DEFAULT_DB_NAME,
    DEFAULT_DB_USER,
    DEFAULT_POSTGRES_SERVICE,
    parse_psql_json_output,
)
from rs_core.recsys.candidate_store.schema import row_to_recall_candidate
from rs_core.recsys.types import RecallCandidate

ENABLE_ENV = "RS_POSTGRES_CANDIDATE_STORE_ENABLED"
MAX_QUERY_LIMIT = 500
Runner = Callable[[list[str], str], subprocess.CompletedProcess[str]]


class CandidateStore(Protocol):
    def health(self) -> dict[str, Any]: ...

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]: ...

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]: ...

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]: ...

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]: ...

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]: ...

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]: ...


class NoopCandidateStore:
    def health(self) -> dict[str, Any]:
        return {"enabled": False, "status": "disabled", "backend": "noop"}

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]:
        return []

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]:
        return []

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]:
        return []

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]:
        return []

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
        return []

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]:
        return []


@dataclass
class SafeCandidateStore:
    inner: CandidateStore

    def health(self) -> dict[str, Any]:
        try:
            return _public_status(self.inner.health())
        except Exception as exc:
            return _safe_error_status("health_failed", exc)

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]:
        try:
            return self.inner.item_neighbors(source=source, seed_items=seed_items, limit_per_seed=limit_per_seed)
        except Exception:
            return []

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]:
        try:
            return self.inner.user_candidates(user_id=user_id, source=source, limit=limit)
        except Exception:
            return []

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]:
        try:
            return self.inner.popular_candidates(scope=scope, bucket=bucket, limit=limit)
        except Exception:
            return []

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]:
        try:
            return self.inner.category_candidates(buckets=buckets, limit_per_bucket=limit_per_bucket)
        except Exception:
            return []

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
        try:
            return self.inner.user_category_buckets(user_id=user_id, limit=limit)
        except Exception:
            return []

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]:
        try:
            return self.inner.pool_candidates(user_id=user_id, limit=limit)
        except Exception:
            return []


@dataclass
class PostgresCandidateStore:
    compose_file: str = DEFAULT_COMPOSE_FILE
    postgres_service: str = DEFAULT_POSTGRES_SERVICE
    db_user: str = DEFAULT_DB_USER
    db_name: str = DEFAULT_DB_NAME
    query_timeout_seconds: int = 10
    runner: Runner | None = None

    def health(self) -> dict[str, Any]:
        try:
            row = self._single_object(
                """
                SELECT json_build_object(
                    'ok', true,
                    'tables', json_build_object(
                        'item_neighbors', to_regclass('public.item_neighbors') IS NOT NULL,
                        'usercf_candidates', to_regclass('public.usercf_candidates') IS NOT NULL,
                        'popular_candidates', to_regclass('public.popular_candidates') IS NOT NULL,
                        'category_candidates', to_regclass('public.category_candidates') IS NOT NULL,
                        'user_category_profiles', to_regclass('public.user_category_profiles') IS NOT NULL,
                        'pool_candidates', to_regclass('public.pool_candidates') IS NOT NULL
                    )
                ) AS result
                """
            )
        except Exception as exc:
            return _safe_error_status("unavailable", exc, backend="docker_psql")
        tables = row.get("tables") if isinstance(row.get("tables"), dict) else {}
        required = ("item_neighbors", "usercf_candidates", "popular_candidates", "category_candidates")
        status = "ok" if all(tables.get(name) for name in required) else "degraded"
        return {"enabled": True, "status": status, "backend": "docker_psql", "tables": tables}

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]:
        seeds = [str(item) for item in seed_items if str(item or "").strip()]
        if not seeds:
            return []
        safe_limit = _clamp_limit(limit_per_seed)
        sql = """
        WITH seeds AS (
            SELECT jsonb_array_elements_text(:'seed_items'::jsonb) AS src_item_id
        ), ranked AS (
            SELECT
                n.source,
                n.src_item_id,
                n.dst_item_id AS parent_asin,
                n.score,
                n.rank,
                n.category,
                n.metadata,
                n.artifact_id,
                row_number() OVER (PARTITION BY n.src_item_id ORDER BY n.rank NULLS LAST, n.score DESC, n.dst_item_id) AS rn
            FROM item_neighbors n
            JOIN seeds s ON s.src_item_id = n.src_item_id
            WHERE n.source = :'source'
        )
        SELECT json_build_object(
            'source', source,
            'src_item_id', src_item_id,
            'parent_asin', parent_asin,
            'score', score,
            'rank', rank,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM ranked
        WHERE rn <= :'limit'
        ORDER BY src_item_id, rn
        """
        rows = self._json_query(sql, {"source": source, "seed_items": _json_array(seeds), "limit": str(safe_limit)})
        return _rows_to_candidates(rows, default_source=source)

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]:
        if not str(user_id or "").strip():
            return []
        sql = """
        SELECT json_build_object(
            'source', source,
            'parent_asin', parent_asin,
            'score', score,
            'rank', rank,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM usercf_candidates
        WHERE source = :'source' AND user_id = :'user_id'
        ORDER BY rank NULLS LAST, score DESC, parent_asin
        LIMIT :'limit'
        """
        rows = self._json_query(sql, {"source": source, "user_id": str(user_id), "limit": str(_clamp_limit(limit))})
        return _rows_to_candidates(rows, default_source=source)

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]:
        sql = """
        SELECT json_build_object(
            'source', 'popular',
            'parent_asin', parent_asin,
            'score', score,
            'rank', rank,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM popular_candidates
        WHERE scope = :'scope' AND bucket = :'bucket'
        ORDER BY rank NULLS LAST, score DESC, parent_asin
        LIMIT :'limit'
        """
        rows = self._json_query(sql, {"scope": scope, "bucket": bucket, "limit": str(_clamp_limit(limit))})
        return _rows_to_candidates(rows, default_source="popular")

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]:
        clean_buckets = [str(bucket) for bucket in buckets if str(bucket or "").strip()]
        if not clean_buckets:
            return []
        sql = """
        WITH buckets AS (
            SELECT jsonb_array_elements_text(:'buckets'::jsonb) AS bucket
        ), ranked AS (
            SELECT
                c.bucket,
                c.parent_asin,
                c.score,
                c.rank,
                c.category,
                c.metadata,
                c.artifact_id,
                row_number() OVER (PARTITION BY c.bucket ORDER BY c.rank NULLS LAST, c.score DESC, c.parent_asin) AS rn
            FROM category_candidates c
            JOIN buckets b ON b.bucket = c.bucket
        )
        SELECT json_build_object(
            'source', 'category',
            'parent_asin', parent_asin,
            'score', score,
            'rank', rank,
            'category', category,
            'metadata', metadata || jsonb_build_object('category_bucket', bucket),
            'artifact_id', artifact_id
        ) AS result
        FROM ranked
        WHERE rn <= :'limit'
        ORDER BY bucket, rn
        """
        rows = self._json_query(sql, {"buckets": _json_array(clean_buckets), "limit": str(_clamp_limit(limit_per_bucket))})
        return _rows_to_candidates(rows, default_source="category")

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
        if not str(user_id or "").strip():
            return []
        sql = """
        SELECT json_build_object('bucket', bucket) AS result
        FROM user_category_profiles
        WHERE user_id = :'user_id'
        ORDER BY rank NULLS LAST, score DESC, bucket
        LIMIT :'limit'
        """
        rows = self._json_query(sql, {"user_id": str(user_id), "limit": str(_clamp_limit(limit, maximum=50))})
        return [str(row.get("bucket")) for row in rows if isinstance(row, dict) and row.get("bucket")]

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]:
        if not str(user_id or "").strip():
            return []
        if not self._table_exists("pool_candidates"):
            return []
        sql = """
        SELECT json_build_object(
            'source', source,
            'parent_asin', parent_asin,
            'score', score,
            'rank', rank,
            'category', category,
            'metadata', metadata,
            'artifact_id', artifact_id
        ) AS result
        FROM pool_candidates
        WHERE user_id = :'user_id'
        ORDER BY rank NULLS LAST, score DESC, parent_asin
        LIMIT :'limit'
        """
        rows = self._json_query(sql, {"user_id": str(user_id), "limit": str(_clamp_limit(limit))})
        return _rows_to_candidates(rows, default_source="pool500_fallback")

    def _table_exists(self, table_name: str) -> bool:
        row = self._single_object("SELECT json_build_object('exists', to_regclass(:'table_name') IS NOT NULL) AS result", {"table_name": f"public.{table_name}"})
        return bool(row.get("exists"))

    def _single_object(self, sql: str, variables: dict[str, str] | None = None) -> dict[str, Any]:
        rows = self._json_query(sql, variables)
        if not rows:
            raise RuntimeError("postgres query returned no rows")
        row = rows[0]
        return row if isinstance(row, dict) else {}

    def _json_query(self, sql: str, variables: dict[str, str] | None = None) -> list[Any]:
        _ensure_select_only(sql)
        command = self._command(variables)
        proc = self._run(command, sql)
        if proc.returncode != 0:
            raise RuntimeError("postgres candidate store query failed")
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
        return subprocess.run(command, input=sql, text=True, encoding="utf-8", capture_output=True, timeout=self.query_timeout_seconds, check=False)


def build_postgres_candidate_store_from_env() -> CandidateStore:
    if os.environ.get(ENABLE_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        return NoopCandidateStore()
    store = PostgresCandidateStore(
        compose_file=os.environ.get("RS_POSTGRES_COMPOSE_FILE", DEFAULT_COMPOSE_FILE),
        postgres_service=os.environ.get("RS_POSTGRES_SERVICE", DEFAULT_POSTGRES_SERVICE),
        db_user=os.environ.get("RS_POSTGRES_USER", DEFAULT_DB_USER),
        db_name=os.environ.get("RS_POSTGRES_DB", DEFAULT_DB_NAME),
        query_timeout_seconds=_env_int("RS_POSTGRES_QUERY_TIMEOUT_SECONDS", 10),
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
    normalized = sql.strip().lower()
    if not normalized.startswith(("select", "with")):
        raise ValueError("postgres candidate store allows SELECT/CTE queries only")
    if ";" in normalized:
        raise ValueError("postgres candidate store allows single SELECT statements only")
    forbidden = ("insert ", "update ", "delete ", "drop ", "alter ", "truncate ", "copy ", "create ", "grant ", "revoke ")
    if any(token in normalized for token in forbidden):
        raise ValueError("postgres candidate store allows read-only queries only")


def _json_array(values: list[str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=False)


def _clamp_limit(value: int, *, maximum: int = MAX_QUERY_LIMIT) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 50
    return max(1, min(parsed, maximum))


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


def _safe_error_status(reason: str, exc: Exception, backend: str = "postgres_candidate_store") -> dict[str, Any]:
    return {"enabled": True, "status": "degraded", "backend": backend, "reason": reason, "error_type": type(exc).__name__}
