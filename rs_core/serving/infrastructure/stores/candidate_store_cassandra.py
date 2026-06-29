from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from rs_core.serving.infrastructure.stores.candidate_import_plan import ImportPlan, TargetSchema, batches, has_partial_artifact_errors, plan_jsonl, resolve_path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "deploy" / "local" / "cassandra" / "init" / "001_candidate_store.cql"


class CassandraSession(Protocol):
    def execute(self, statement: Any, parameters: Any | None = None) -> Any: ...

    def prepare(self, statement: str) -> Any: ...


@dataclass(frozen=True)
class CassandraConnectionArgs:
    hosts: tuple[str, ...] = ("127.0.0.1",)
    port: int = 9042
    keyspace: str = "rs_agent"
    datacenter: str = "datacenter1"
    username: str = ""
    password: str = ""
    request_timeout_seconds: int = 30


def import_candidate_store_to_cassandra(
    *,
    inputs: list[Path],
    limit_rows: int = 1000,
    batch_size: int = 500,
    artifact_id: str = "",
    source: str = "",
    store_version: str = "",
    target_schema: TargetSchema = "auto",
    write: bool = False,
    apply_schema: bool = False,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    connection_args: CassandraConnectionArgs | None = None,
    session: CassandraSession | None = None,
) -> dict[str, Any]:
    if apply_schema:
        active_session = session or _connect(connection_args or CassandraConnectionArgs(), connect_keyspace=False)
        statements = _read_cql_statements(resolve_path(schema_path))
        for statement in statements:
            active_session.execute(statement)
        return {"dry_run": False, "apply_schema": True, "statement_count": len(statements), "schema_path": str(resolve_path(schema_path))}

    plans = [plan_jsonl(resolve_path(path), limit_rows, artifact_id=artifact_id, source_override=source, target_schema=target_schema) for path in inputs]
    reports = [_with_store_version(plan.report, store_version) for plan in plans]
    if not write:
        return {"dry_run": True, "input_count": len(inputs), "reports": reports}
    if not store_version.strip():
        return {"dry_run": False, "input_count": len(inputs), "write_status": "rejected_missing_store_version", "reports": reports}

    active_session = session or _connect(connection_args or CassandraConnectionArgs())
    write_reports: list[dict[str, Any]] = []
    for plan in plans:
        report = _with_store_version(plan.report, store_version)
        if plan.schema == "unsupported":
            report["write_status"] = "skipped_unsupported_schema"
            write_reports.append(report)
            continue
        if has_partial_artifact_errors(report):
            report["write_status"] = "rejected_partial_artifact"
            write_reports.append(report)
            continue
        if not plan.rows:
            report["write_status"] = "skipped_no_rows"
            write_reports.append(report)
            continue
        prepared = active_session.prepare(_insert_cql(plan.schema))
        written = 0
        batch_count = 0
        for batch in batches(plan.rows, batch_size):
            for row in batch:
                active_session.execute(prepared, _bind_values(plan.schema, row, store_version=store_version))
                written += 1
            batch_count += 1
        _write_manifest(active_session, plan, store_version=store_version, artifact_id=artifact_id)
        report["write_status"] = "written"
        report["written_rows"] = written
        report["batches"] = batch_count
        write_reports.append(report)
    return {"dry_run": False, "input_count": len(inputs), "reports": write_reports}


def _insert_cql(schema: str) -> str:
    if schema == "item_neighbors":
        return """
        INSERT INTO item_neighbors_by_seed
        (source, store_version, src_item_id, rank, dst_item_id, score, category, artifact_id, metadata, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    if schema == "usercf_candidates":
        return """
        INSERT INTO user_candidates_by_user
        (source, store_version, user_id, rank, parent_asin, score, category, artifact_id, metadata, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    if schema == "pool_candidates":
        return """
        INSERT INTO pool_candidates_by_user
        (store_version, user_id, rank, parent_asin, source, score, category, artifact_id, metadata, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    if schema == "popular_candidates":
        return """
        INSERT INTO popular_candidates_by_scope
        (source, store_version, scope, bucket, rank, parent_asin, score, category, artifact_id, metadata, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    if schema == "category_candidates":
        return """
        INSERT INTO category_candidates_by_bucket
        (source, store_version, bucket, rank, parent_asin, score, category, artifact_id, metadata, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
    if schema == "user_category_profiles":
        return """
        INSERT INTO user_category_buckets_by_user
        (store_version, user_id, rank, bucket, score, metadata, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
    raise ValueError(f"unsupported schema: {schema}")


def _bind_values(schema: str, row: dict[str, Any], *, store_version: str) -> tuple[Any, ...]:
    now = datetime.now(timezone.utc)
    metadata = json.dumps(row.get("metadata") if isinstance(row.get("metadata"), dict) else {}, ensure_ascii=False, sort_keys=True)
    if schema == "item_neighbors":
        return (row["source"], store_version, row["src_item_id"], int(row.get("rank") or 0), row["dst_item_id"], float(row.get("score") or 0.0), row.get("category") or "", row.get("artifact_id") or "", metadata, now)
    if schema == "usercf_candidates":
        return (row["source"], store_version, row["user_id"], int(row.get("rank") or 0), row["parent_asin"], float(row.get("score") or 0.0), row.get("category") or "", row.get("artifact_id") or "", metadata, now)
    if schema == "pool_candidates":
        return (store_version, row["user_id"], int(row.get("rank") or 0), row["parent_asin"], row["source"], float(row.get("score") or 0.0), row.get("category") or "", row.get("artifact_id") or "", metadata, now)
    if schema == "popular_candidates":
        return (row["source"], store_version, row.get("scope") or "global", row.get("bucket") or "", int(row.get("rank") or 0), row["parent_asin"], float(row.get("score") or 0.0), row.get("category") or "", row.get("artifact_id") or "", metadata, now)
    if schema == "category_candidates":
        return (row["source"], store_version, row["bucket"], int(row.get("rank") or 0), row["parent_asin"], float(row.get("score") or 0.0), row.get("category") or "", row.get("artifact_id") or "", metadata, now)
    if schema == "user_category_profiles":
        return (store_version, row["user_id"], int(row.get("rank") or 0), row["bucket"], float(row.get("score") or 0.0), metadata, now)
    raise ValueError(f"unsupported schema: {schema}")


def _write_manifest(active_session: CassandraSession, plan: ImportPlan, *, store_version: str, artifact_id: str) -> None:
    cql = """
    INSERT INTO candidate_store_manifests
    (store_name, store_version, source, artifact_path, artifact_id, row_count, imported_at, status, metrics, metadata)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    prepared = active_session.prepare(cql)
    source = next(iter(plan.report.get("sources", {}) or {"unknown": 0}))
    metrics = json.dumps(plan.report, ensure_ascii=False, sort_keys=True)
    active_session.execute(prepared, ("candidate_store", store_version, str(source), str(plan.path), artifact_id or "", int(plan.report.get("importable_rows", 0)), datetime.now(timezone.utc), "imported", metrics, "{}"))


def _connect(args: CassandraConnectionArgs, *, connect_keyspace: bool = True) -> CassandraSession:
    try:
        from cassandra.auth import PlainTextAuthProvider  # type: ignore[import-not-found]
        from cassandra.cluster import Cluster  # type: ignore[import-not-found]
        from cassandra.policies import DCAwareRoundRobinPolicy  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - requires optional dependency absence
        raise RuntimeError("cassandra-driver optional dependency is not installed") from exc

    auth_provider = None
    if args.username or args.password:
        auth_provider = PlainTextAuthProvider(username=args.username, password=args.password)
    cluster_kwargs: dict[str, Any] = {"contact_points": list(args.hosts), "port": args.port, "connect_timeout": args.request_timeout_seconds, "control_connection_timeout": args.request_timeout_seconds}
    if args.datacenter:
        cluster_kwargs["load_balancing_policy"] = DCAwareRoundRobinPolicy(local_dc=args.datacenter)
    if auth_provider is not None:
        cluster_kwargs["auth_provider"] = auth_provider
    cluster = Cluster(**cluster_kwargs)
    session = cluster.connect(args.keyspace if connect_keyspace else None)
    session.default_timeout = args.request_timeout_seconds
    return session


def _read_cql_statements(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    statements: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
    if current:
        statement = "\n".join(current).strip().rstrip(";").strip()
        if statement:
            statements.append(statement)
    return statements


def _with_store_version(report: dict[str, Any], store_version: str) -> dict[str, Any]:
    result = dict(report)
    if store_version:
        result["store_version"] = store_version
    return result
