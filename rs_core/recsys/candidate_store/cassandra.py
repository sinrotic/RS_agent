from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from rs_core.recsys.candidate_store.postgres import CandidateStore, MAX_QUERY_LIMIT, SafeCandidateStore, _safe_error_status
from rs_core.recsys.candidate_store.schema import row_to_recall_candidate
from rs_core.recsys.types import RecallCandidate

DEFAULT_CASSANDRA_HOSTS = "127.0.0.1"
DEFAULT_CASSANDRA_PORT = 9042
DEFAULT_CASSANDRA_KEYSPACE = "rs_agent"
DEFAULT_CASSANDRA_DATACENTER = "datacenter1"
DEFAULT_CASSANDRA_STORE_VERSION = "default"

REQUIRED_TABLES = (
    "item_neighbors_by_seed",
    "user_candidates_by_user",
    "popular_candidates_by_scope",
    "category_candidates_by_bucket",
    "user_category_buckets_by_user",
    "pool_candidates_by_user",
)


@dataclass(frozen=True)
class CassandraSettings:
    hosts: tuple[str, ...] = ("127.0.0.1",)
    port: int = DEFAULT_CASSANDRA_PORT
    keyspace: str = DEFAULT_CASSANDRA_KEYSPACE
    datacenter: str = DEFAULT_CASSANDRA_DATACENTER
    username: str = ""
    password: str = ""
    connect_timeout_seconds: int = 5
    request_timeout_seconds: int = 3
    store_version: str = DEFAULT_CASSANDRA_STORE_VERSION
    consistency: str = "LOCAL_ONE"


@dataclass
class CassandraCandidateStore:
    settings: CassandraSettings
    session: Any | None = None
    cluster: Any | None = None

    def health(self) -> dict[str, Any]:
        try:
            session = self._get_session()
            table_status = {table: False for table in REQUIRED_TABLES}
            rows = session.execute(
                "SELECT table_name FROM system_schema.tables WHERE keyspace_name = %s",
                (self.settings.keyspace,),
            )
            for row in rows or []:
                table_name = _row_get(row, "table_name")
                if table_name in table_status:
                    table_status[str(table_name)] = True
        except Exception as exc:
            return _safe_error_status("unavailable", exc, backend="cassandra") | {
                "store_version": self.settings.store_version,
                "keyspace": self.settings.keyspace,
            }
        status = "ok" if all(table_status.values()) else "degraded"
        return {
            "enabled": True,
            "status": status,
            "backend": "cassandra",
            "keyspace": self.settings.keyspace,
            "store_version": self.settings.store_version,
            "tables": table_status,
        }

    def item_neighbors(self, *, source: str, seed_items: list[str], limit_per_seed: int) -> list[RecallCandidate]:
        seeds = _clean_unique(seed_items)
        if not seeds:
            return []
        limit = _clamp_limit(limit_per_seed)
        rows: list[dict[str, Any]] = []
        session = self._get_session()
        cql = """
        SELECT source, src_item_id, dst_item_id, score, rank, category, artifact_id, metadata
        FROM item_neighbors_by_seed
        WHERE source = %s AND store_version = %s AND src_item_id = %s
        LIMIT %s
        """
        for seed in seeds:
            for row in session.execute(cql, (source, self.settings.store_version, seed, limit)) or []:
                rows.append(_candidate_row(row, default_source=source, item_field="dst_item_id", seed_item_id=seed))
        return _rows_to_candidates(rows, default_source=source)

    def user_candidates(self, *, user_id: str, source: str, limit: int) -> list[RecallCandidate]:
        clean_user = str(user_id or "").strip()
        if not clean_user:
            return []
        session = self._get_session()
        cql = """
        SELECT source, parent_asin, score, rank, category, artifact_id, metadata
        FROM user_candidates_by_user
        WHERE source = %s AND store_version = %s AND user_id = %s
        LIMIT %s
        """
        rows = [
            _candidate_row(row, default_source=source, item_field="parent_asin")
            for row in session.execute(cql, (source, self.settings.store_version, clean_user, _clamp_limit(limit))) or []
        ]
        return _rows_to_candidates(rows, default_source=source)

    def popular_candidates(self, *, scope: str = "global", bucket: str = "", limit: int = 50) -> list[RecallCandidate]:
        session = self._get_session()
        cql = """
        SELECT source, parent_asin, score, rank, category, artifact_id, metadata
        FROM popular_candidates_by_scope
        WHERE source = %s AND store_version = %s AND scope = %s AND bucket = %s
        LIMIT %s
        """
        rows = [
            _candidate_row(row, default_source="popular", item_field="parent_asin")
            for row in session.execute(cql, ("popular", self.settings.store_version, str(scope or "global"), str(bucket or ""), _clamp_limit(limit))) or []
        ]
        return _rows_to_candidates(rows, default_source="popular")

    def category_candidates(self, *, buckets: list[str], limit_per_bucket: int = 20) -> list[RecallCandidate]:
        clean_buckets = _clean_unique(buckets)
        if not clean_buckets:
            return []
        limit = _clamp_limit(limit_per_bucket)
        session = self._get_session()
        cql = """
        SELECT source, parent_asin, score, rank, category, artifact_id, metadata
        FROM category_candidates_by_bucket
        WHERE source = %s AND store_version = %s AND bucket = %s
        LIMIT %s
        """
        rows: list[dict[str, Any]] = []
        for bucket in clean_buckets:
            for row in session.execute(cql, ("category", self.settings.store_version, bucket, limit)) or []:
                payload = _candidate_row(row, default_source="category", item_field="parent_asin")
                metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
                payload["metadata"] = dict(metadata) | {"category_bucket": bucket}
                rows.append(payload)
        return _rows_to_candidates(rows, default_source="category")

    def user_category_buckets(self, *, user_id: str, limit: int = 5) -> list[str]:
        clean_user = str(user_id or "").strip()
        if not clean_user:
            return []
        session = self._get_session()
        cql = """
        SELECT bucket
        FROM user_category_buckets_by_user
        WHERE store_version = %s AND user_id = %s
        LIMIT %s
        """
        rows = session.execute(cql, (self.settings.store_version, clean_user, _clamp_limit(limit, maximum=50))) or []
        return [str(_row_get(row, "bucket") or "").strip() for row in rows if str(_row_get(row, "bucket") or "").strip()]

    def pool_candidates(self, *, user_id: str, limit: int = 500) -> list[RecallCandidate]:
        clean_user = str(user_id or "").strip()
        if not clean_user:
            return []
        session = self._get_session()
        cql = """
        SELECT source, parent_asin, score, rank, category, artifact_id, metadata
        FROM pool_candidates_by_user
        WHERE store_version = %s AND user_id = %s
        LIMIT %s
        """
        rows = [
            _candidate_row(row, default_source="pool500_fallback", item_field="parent_asin")
            for row in session.execute(cql, (self.settings.store_version, clean_user, _clamp_limit(limit))) or []
        ]
        return _rows_to_candidates(rows, default_source="pool500_fallback")

    def _get_session(self) -> Any:
        if self.session is not None:
            return self.session
        try:
            from cassandra.auth import PlainTextAuthProvider  # type: ignore[import-not-found]
            from cassandra.cluster import Cluster  # type: ignore[import-not-found]
            from cassandra.policies import DCAwareRoundRobinPolicy  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - exercised through health with missing optional dependency
            raise RuntimeError("cassandra-driver optional dependency is not installed") from exc

        auth_provider = None
        if self.settings.username or self.settings.password:
            auth_provider = PlainTextAuthProvider(username=self.settings.username, password=self.settings.password)
        cluster_kwargs: dict[str, Any] = {
            "contact_points": list(self.settings.hosts),
            "port": self.settings.port,
            "connect_timeout": self.settings.connect_timeout_seconds,
            "control_connection_timeout": self.settings.connect_timeout_seconds,
        }
        if auth_provider is not None:
            cluster_kwargs["auth_provider"] = auth_provider
        if self.settings.datacenter:
            cluster_kwargs["load_balancing_policy"] = DCAwareRoundRobinPolicy(local_dc=self.settings.datacenter)
        self.cluster = Cluster(**cluster_kwargs)
        self.session = self.cluster.connect(self.settings.keyspace)
        self.session.default_timeout = self.settings.request_timeout_seconds
        return self.session


def build_cassandra_candidate_store_from_env() -> CandidateStore:
    return SafeCandidateStore(CassandraCandidateStore(settings=cassandra_settings_from_env()))


def cassandra_settings_from_env() -> CassandraSettings:
    hosts = tuple(host.strip() for host in os.environ.get("RS_CASSANDRA_HOSTS", DEFAULT_CASSANDRA_HOSTS).split(",") if host.strip())
    return CassandraSettings(
        hosts=hosts or ("127.0.0.1",),
        port=_env_int("RS_CASSANDRA_PORT", DEFAULT_CASSANDRA_PORT),
        keyspace=os.environ.get("RS_CASSANDRA_KEYSPACE", DEFAULT_CASSANDRA_KEYSPACE).strip() or DEFAULT_CASSANDRA_KEYSPACE,
        datacenter=os.environ.get("RS_CASSANDRA_DATACENTER", DEFAULT_CASSANDRA_DATACENTER).strip(),
        username=os.environ.get("RS_CASSANDRA_USERNAME", "").strip(),
        password=os.environ.get("RS_CASSANDRA_PASSWORD", ""),
        connect_timeout_seconds=_env_int("RS_CASSANDRA_CONNECT_TIMEOUT_SECONDS", 5),
        request_timeout_seconds=_env_int("RS_CASSANDRA_REQUEST_TIMEOUT_SECONDS", 3),
        store_version=os.environ.get("RS_CASSANDRA_STORE_VERSION", DEFAULT_CASSANDRA_STORE_VERSION).strip() or DEFAULT_CASSANDRA_STORE_VERSION,
        consistency=os.environ.get("RS_CASSANDRA_CONSISTENCY", "LOCAL_ONE").strip() or "LOCAL_ONE",
    )


def _candidate_row(row: Any, *, default_source: str, item_field: str, seed_item_id: str = "") -> dict[str, Any]:
    metadata = _metadata_dict(_row_get(row, "metadata"))
    payload = {
        "source": _row_get(row, "source") or default_source,
        item_field: _row_get(row, item_field),
        "score": _row_get(row, "score"),
        "rank": _row_get(row, "rank"),
        "category": _row_get(row, "category"),
        "artifact_id": _row_get(row, "artifact_id"),
        "metadata": metadata,
    }
    if seed_item_id:
        payload["src_item_id"] = seed_item_id
    return payload


def _rows_to_candidates(rows: list[dict[str, Any]], *, default_source: str) -> list[RecallCandidate]:
    candidates: list[RecallCandidate] = []
    for row in rows:
        candidate = row_to_recall_candidate(row, default_source=default_source)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _clean_unique(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            rows.append(text)
            seen.add(text)
    return rows


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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
