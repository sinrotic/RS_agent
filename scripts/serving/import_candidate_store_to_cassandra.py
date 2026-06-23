from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "deploy" / "local" / "cassandra" / "init" / "001_candidate_store.cql"
SchemaKind = Literal[
    "usercf_candidates",
    "item_neighbors",
    "popular_candidates",
    "category_candidates",
    "user_category_profiles",
    "pool_candidates",
    "unsupported",
]
TargetSchema = Literal[
    "auto",
    "usercf_candidates",
    "item_neighbors",
    "popular_candidates",
    "category_candidates",
    "user_category_profiles",
    "pool_candidates",
]


class CassandraSession(Protocol):
    def execute(self, statement: Any, parameters: Any | None = None) -> Any: ...

    def prepare(self, statement: str) -> Any: ...


@dataclass(frozen=True)
class ImportPlan:
    path: Path
    schema: SchemaKind
    rows: list[dict[str, Any]]
    report: dict[str, Any]


@dataclass(frozen=True)
class CassandraConnectionArgs:
    hosts: tuple[str, ...] = ("127.0.0.1",)
    port: int = 9042
    keyspace: str = "rs_agent"
    datacenter: str = "datacenter1"
    username: str = ""
    password: str = ""
    request_timeout_seconds: int = 30


def main() -> None:
    parser = argparse.ArgumentParser(description="Safety-first Cassandra candidate store importer; dry-run is the default.")
    parser.add_argument("--input", type=Path, action="append", default=[], help="JSONL artifact path to scan/import. May be repeated.")
    parser.add_argument("--limit-rows", type=int, default=1000, help="Maximum rows to scan/import per input file. 0 means no limit.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per write chunk in write mode.")
    parser.add_argument("--artifact-id", default="", help="Artifact id stamped onto imported rows.")
    parser.add_argument("--source", default="", help="Override source stamped onto imported rows.")
    parser.add_argument("--store-version", default="", help="Required version stamped into Cassandra partition keys.")
    parser.add_argument("--target-schema", choices=["auto", "usercf_candidates", "item_neighbors", "popular_candidates", "category_candidates", "user_category_profiles", "pool_candidates"], default="auto", help="Import target schema. Use pool_candidates for merged pool500_candidates.jsonl.")
    parser.add_argument("--hosts", default="127.0.0.1", help="Comma-separated Cassandra/Scylla contact points.")
    parser.add_argument("--port", type=int, default=9042)
    parser.add_argument("--keyspace", default="rs_agent")
    parser.add_argument("--datacenter", default="datacenter1")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="", help="Local smoke only; prefer env/secret manager outside this script.")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH, help="CQL schema path used by --apply-schema.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Scan only; do not write. This is the default.")
    mode.add_argument("--write", action="store_true", help="Write supported rows to Cassandra/Scylla.")
    mode.add_argument("--apply-schema", action="store_true", help="Apply the local CQL schema and exit.")
    args = parser.parse_args()

    result = import_candidate_store_to_cassandra(
        inputs=args.input,
        limit_rows=max(0, int(args.limit_rows)),
        batch_size=max(1, int(args.batch_size)),
        artifact_id=str(args.artifact_id or ""),
        source=str(args.source or ""),
        store_version=str(args.store_version or ""),
        target_schema=args.target_schema,
        write=bool(args.write),
        apply_schema=bool(args.apply_schema),
        schema_path=args.schema,
        connection_args=CassandraConnectionArgs(
            hosts=tuple(host.strip() for host in str(args.hosts).split(",") if host.strip()) or ("127.0.0.1",),
            port=int(args.port),
            keyspace=str(args.keyspace or "rs_agent"),
            datacenter=str(args.datacenter or "datacenter1"),
            username=str(args.username or ""),
            password=str(args.password or ""),
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


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
        statements = _read_cql_statements(_resolve_path(schema_path))
        for statement in statements:
            active_session.execute(statement)
        return {"dry_run": False, "apply_schema": True, "statement_count": len(statements), "schema_path": str(_resolve_path(schema_path))}

    plans = [_plan_jsonl(_resolve_path(path), limit_rows, artifact_id=artifact_id, source_override=source, target_schema=target_schema) for path in inputs]
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
        if _has_partial_artifact_errors(report):
            report["write_status"] = "rejected_partial_artifact"
            write_reports.append(report)
            continue
        if not plan.rows:
            report["write_status"] = "skipped_no_rows"
            write_reports.append(report)
            continue
        prepared = active_session.prepare(_insert_cql(plan.schema))
        written = 0
        batches = 0
        for batch in _batches(plan.rows, batch_size):
            for row in batch:
                active_session.execute(prepared, _bind_values(plan.schema, row, store_version=store_version))
                written += 1
            batches += 1
        _write_manifest(active_session, plan, store_version=store_version, artifact_id=artifact_id)
        report["write_status"] = "written"
        report["written_rows"] = written
        report["batches"] = batches
        write_reports.append(report)
    return {"dry_run": False, "input_count": len(inputs), "reports": write_reports}


def _plan_jsonl(path: Path, limit_rows: int, *, artifact_id: str, source_override: str, target_schema: TargetSchema) -> ImportPlan:
    report: dict[str, Any] = {"path": str(path), "exists": path.exists(), "scanned_rows": 0, "candidate_like_rows": 0, "sources": {}, "target_schema": target_schema}
    if not path.exists():
        report["status"] = "missing"
        report["schema"] = "unsupported"
        return ImportPlan(path, "unsupported", [], report)

    schema: SchemaKind | None = None
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if limit_rows and report["scanned_rows"] >= limit_rows:
                report["truncated"] = True
                break
            report["scanned_rows"] += 1
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                report["json_errors"] = int(report.get("json_errors", 0)) + 1
                continue
            row_schema = _classify_row(raw, target_schema=target_schema)
            if row_schema == "unsupported":
                report["unsupported_rows"] = int(report.get("unsupported_rows", 0)) + 1
                continue
            if schema is None:
                schema = row_schema
            elif schema != row_schema:
                report["mixed_schema_rows"] = int(report.get("mixed_schema_rows", 0)) + 1
                continue
            normalized = _normalize_row(raw, row_schema, artifact_id=artifact_id, source_override=source_override, rank=len(rows) + 1)
            if normalized is None:
                report["unsupported_rows"] = int(report.get("unsupported_rows", 0)) + 1
                continue
            rows.append(normalized)
            report["candidate_like_rows"] += 1

    if schema is None:
        schema = "unsupported"
        report["status"] = "unsupported"
    else:
        rows, duplicate_rows = _dedupe_rows(schema, rows)
        if duplicate_rows:
            report["duplicate_rows"] = duplicate_rows
        report["status"] = "supported"
    report["schema"] = schema
    report["importable_rows"] = len(rows)
    report["sources"] = _source_counts(rows)
    return ImportPlan(path, schema, rows, report)


def _classify_row(row: Any, *, target_schema: TargetSchema) -> SchemaKind:
    if not isinstance(row, dict):
        return "unsupported"
    if target_schema != "auto":
        return target_schema if _row_matches_schema(row, target_schema) else "unsupported"
    if (row.get("src_item") or row.get("src_item_id")) and (row.get("dst_item") or row.get("dst_item_id")):
        return "item_neighbors"
    source = str(row.get("source") or "").strip()
    if source.startswith("popular") and (row.get("parent_asin") or row.get("item_id")):
        return "popular_candidates"
    if source.startswith("category") and (row.get("parent_asin") or row.get("item_id")):
        return "category_candidates"
    if row.get("user_id") and (row.get("parent_asin") or row.get("item_id")):
        return "pool_candidates" if _looks_like_pool_candidate(row) else "usercf_candidates"
    if row.get("user_id") and (row.get("bucket") or row.get("category_bucket")):
        return "user_category_profiles"
    return "unsupported"


def _looks_like_pool_candidate(row: dict[str, Any]) -> bool:
    return isinstance(row.get("sources"), list) or isinstance(row.get("source_scores"), dict) or _clean_text(row.get("pool_name")).startswith("pool")


def _row_matches_schema(row: dict[str, Any], schema: TargetSchema) -> bool:
    if schema == "item_neighbors":
        return bool((row.get("src_item") or row.get("src_item_id")) and (row.get("dst_item") or row.get("dst_item_id")))
    if schema in {"usercf_candidates", "pool_candidates"}:
        return bool(row.get("user_id") and (row.get("parent_asin") or row.get("item_id")))
    if schema in {"popular_candidates", "category_candidates"}:
        return bool(row.get("parent_asin") or row.get("item_id"))
    if schema == "user_category_profiles":
        return bool(row.get("user_id") and (row.get("bucket") or row.get("category_bucket") or row.get("category")))
    return False


def _normalize_row(row: dict[str, Any], schema: SchemaKind, *, artifact_id: str, source_override: str, rank: int) -> dict[str, Any] | None:
    if schema == "item_neighbors":
        src_item_id = _clean_text(row.get("src_item") or row.get("src_item_id"))
        dst_item_id = _clean_text(row.get("dst_item") or row.get("dst_item_id"))
        source = _source_for_row(row, source_override, default="item_neighbors", prefer_row_source=True)
        score = _score_for_row(row, source)
        if not src_item_id or not dst_item_id or score is None:
            return None
        return _common_candidate_row(row, source=source, item_id=dst_item_id, rank=rank, artifact_id=artifact_id) | {"src_item_id": src_item_id, "dst_item_id": dst_item_id, "score": score}
    if schema == "usercf_candidates":
        user_id = _clean_text(row.get("user_id"))
        parent_asin = _clean_text(row.get("parent_asin") or row.get("item_id"))
        source = _source_for_row(row, source_override, default="usercf_recall", prefer_row_source=False)
        score = _score_for_row(row, source)
        if not user_id or not parent_asin or score is None:
            return None
        return _common_candidate_row(row, source=source, item_id=parent_asin, rank=rank, artifact_id=artifact_id) | {"user_id": user_id, "parent_asin": parent_asin, "score": score}
    if schema == "pool_candidates":
        user_id = _clean_text(row.get("user_id"))
        parent_asin = _clean_text(row.get("parent_asin") or row.get("item_id"))
        source = _source_for_row(row, source_override, default="pool500_fallback", prefer_row_source=True)
        score = _score_for_row(row, source)
        if not user_id or not parent_asin or score is None:
            return None
        return _common_candidate_row(row, source=source, item_id=parent_asin, rank=rank, artifact_id=artifact_id) | {"user_id": user_id, "parent_asin": parent_asin, "score": score}
    if schema in {"popular_candidates", "category_candidates"}:
        parent_asin = _clean_text(row.get("parent_asin") or row.get("item_id"))
        default_source = "popular" if schema == "popular_candidates" else "category"
        source = default_source
        score = _score_for_row(row, _source_for_row(row, source_override, default=default_source, prefer_row_source=True))
        if not parent_asin or score is None:
            return None
        payload = _common_candidate_row(row, source=source, item_id=parent_asin, rank=rank, artifact_id=artifact_id) | {"parent_asin": parent_asin, "score": score}
        raw_source = _source_for_row(row, source_override, default=default_source, prefer_row_source=True)
        if raw_source != source:
            payload["metadata"].setdefault("raw_source", raw_source)
        if schema == "popular_candidates":
            payload["scope"] = _clean_text(row.get("scope")) or "global"
            payload["bucket"] = _clean_text(row.get("bucket"))
        else:
            payload["bucket"] = _clean_text(row.get("bucket") or row.get("category_bucket") or row.get("category"))
            if not payload["bucket"]:
                return None
        return payload
    if schema == "user_category_profiles":
        user_id = _clean_text(row.get("user_id"))
        bucket = _clean_text(row.get("bucket") or row.get("category_bucket") or row.get("category"))
        score = _finite_float_or_none(row.get("score"))
        if score is None:
            score = 0.0
        if not user_id or not bucket:
            return None
        return {"user_id": user_id, "bucket": bucket, "score": score, "rank": _int_or_default(row.get("rank"), rank), "metadata": _metadata_for_row(row)}
    return None


def _common_candidate_row(row: dict[str, Any], *, source: str, item_id: str, rank: int, artifact_id: str) -> dict[str, Any]:
    return {
        "source": source,
        "parent_asin": item_id,
        "rank": _int_or_default(row.get("rank"), rank),
        "category": _clean_text(row.get("category")),
        "artifact_id": artifact_id or _clean_text(row.get("artifact_id")),
        "metadata": _metadata_for_row(row),
    }


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


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def _batches(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]


def _source_for_row(row: dict[str, Any], override: str, *, default: str, prefer_row_source: bool) -> str:
    if override.strip():
        return override.strip()
    if prefer_row_source and _clean_text(row.get("source")):
        return _clean_text(row.get("source"))
    sources = row.get("sources")
    if prefer_row_source and isinstance(sources, list) and sources:
        return _clean_text(sources[0]) or default
    return default


def _score_for_row(row: dict[str, Any], source: str) -> float | None:
    if row.get("score") is not None:
        return _finite_float_or_none(row.get("score"))
    source_scores = row.get("source_scores")
    if isinstance(source_scores, dict) and source_scores:
        if source in source_scores:
            return _finite_float_or_none(source_scores[source])
        scores = [_finite_float_or_none(value) for value in source_scores.values()]
        valid_scores = [score for score in scores if score is not None]
        return max(valid_scores) if valid_scores else None
    return 0.0


def _metadata_for_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    result = dict(metadata)
    if isinstance(row.get("sources"), list):
        result.setdefault("sources", row["sources"])
    if isinstance(row.get("source_scores"), dict):
        result.setdefault("source_scores", row["source_scores"])
    return result


def _dedupe_rows(schema: SchemaKind, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    by_key: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        if schema == "item_neighbors":
            key = (str(row["source"]), str(row["src_item_id"]), str(row["dst_item_id"]))
        elif schema == "usercf_candidates":
            key = (str(row["source"]), str(row["user_id"]), str(row["parent_asin"]))
        elif schema == "pool_candidates":
            key = (str(row["user_id"]), str(row["parent_asin"]))
        elif schema == "popular_candidates":
            key = (str(row["source"]), str(row.get("scope", "global")), str(row.get("bucket", "")), str(row["parent_asin"]))
        elif schema == "category_candidates":
            key = (str(row["source"]), str(row["bucket"]), str(row["parent_asin"]))
        elif schema == "user_category_profiles":
            key = (str(row["user_id"]), str(row["bucket"]))
        else:
            key = (str(len(by_key)),)
        by_key[key] = row
    return list(by_key.values()), len(rows) - len(by_key)


def _source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or "user_category_profiles")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _has_partial_artifact_errors(report: dict[str, Any]) -> bool:
    return bool(report.get("truncated")) or any(int(report.get(key, 0)) > 0 for key in ("json_errors", "mixed_schema_rows", "unsupported_rows"))


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _with_store_version(report: dict[str, Any], store_version: str) -> dict[str, Any]:
    result = dict(report)
    if store_version:
        result["store_version"] = store_version
    return result


if __name__ == "__main__":
    main()
