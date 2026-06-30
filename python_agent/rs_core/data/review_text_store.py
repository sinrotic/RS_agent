from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "deploy" / "local" / "cassandra" / "init" / "001_review_text_store.cql"
DEFAULT_KEYSPACE = "rs_agent_review_text"


class ScyllaSession(Protocol):
    def execute(self, statement: Any, parameters: Any | None = None) -> Any: ...

    def prepare(self, statement: str) -> Any: ...


@dataclass(frozen=True)
class ScyllaConnectionArgs:
    hosts: tuple[str, ...] = ("127.0.0.1",)
    port: int = 9042
    keyspace: str = DEFAULT_KEYSPACE
    datacenter: str = "datacenter1"
    username: str = ""
    password: str = ""
    request_timeout_seconds: int = 30


def import_review_text_to_scylla(
    *,
    inputs: list[Path],
    limit_rows: int = 0,
    batch_size: int = 500,
    progress_every: int = 100_000,
    write: bool = False,
    apply_schema: bool = False,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    connection_args: ScyllaConnectionArgs | None = None,
    session: ScyllaSession | None = None,
    retry_attempts: int = 3,
    retry_sleep_seconds: float = 1.0,
    min_timestamp_ms: int | None = None,
    max_timestamp_ms: int | None = None,
    source_line_filters: dict[Path, Path] | None = None,
) -> dict[str, Any]:
    if apply_schema:
        active_session = session or _connect(connection_args or ScyllaConnectionArgs(), connect_keyspace=False)
        statements = _read_cql_statements(resolve_path(schema_path))
        for statement in statements:
            active_session.execute(statement)
        return {"dry_run": False, "apply_schema": True, "statement_count": len(statements), "schema_path": str(resolve_path(schema_path))}

    if not write:
        reports: list[dict[str, Any]] = []
        for path in inputs:
            resolved = resolve_path(path)
            _rows, report = plan_review_text_jsonl(
                resolved,
                limit_rows=limit_rows,
                min_timestamp_ms=min_timestamp_ms,
                max_timestamp_ms=max_timestamp_ms,
                source_line_filter=resolve_optional_filter(source_line_filters, resolved),
            )
            reports.append(report)
        return {"dry_run": True, "input_count": len(inputs), "reports": reports}

    active_session = session or _connect(connection_args or ScyllaConnectionArgs())
    prepared = _PreparedStatements(
        by_key=active_session.prepare(_insert_by_key_cql()),
        by_item=active_session.prepare(_insert_by_item_cql()),
        by_user=active_session.prepare(_insert_by_user_cql()),
    )
    write_reports: list[dict[str, Any]] = []
    total_written = 0
    resolved_inputs: list[str] = []
    for path in inputs:
        resolved = resolve_path(path)
        resolved_inputs.append(str(resolved))
        written, report = write_review_text_jsonl(
            active_session,
            prepared,
            resolved,
            limit_rows=limit_rows,
            progress_every=max(0, int(progress_every)),
            retry_attempts=max(1, int(retry_attempts)),
            retry_sleep_seconds=max(0.0, float(retry_sleep_seconds)),
            min_timestamp_ms=min_timestamp_ms,
            max_timestamp_ms=max_timestamp_ms,
            source_line_filter=resolve_optional_filter(source_line_filters, resolved),
        )
        total_written += written
        write_reports.append(report)

    _write_import_manifest(active_session, inputs=resolved_inputs, reports=write_reports, row_count=total_written)
    return {"dry_run": False, "input_count": len(inputs), "reports": write_reports}


def plan_review_text_jsonl(
    path: Path,
    *,
    limit_rows: int = 0,
    min_timestamp_ms: int | None = None,
    max_timestamp_ms: int | None = None,
    source_line_filter: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "scanned_rows": 0,
        "importable_rows": 0,
        "skipped_without_text": 0,
        "skipped_outside_time_range": 0,
        "skipped_outside_source_lines": 0,
        "json_errors": 0,
    }
    if not path.exists():
        report["status"] = "missing"
        return [], report

    rows: list[dict[str, Any]] = []
    line_filter = SourceLineFilter(source_line_filter) if source_line_filter else None
    for source_line, raw in iter_jsonl(path, limit_rows):
        report["scanned_rows"] += 1
        if line_filter and not line_filter.accepts(source_line):
            report["skipped_outside_source_lines"] += 1
            continue
        row = review_text_row(raw, source_path=path, source_line=source_line)
        if row is None:
            report["skipped_without_text"] += 1
            continue
        if not timestamp_in_range(row["timestamp_ms"], min_timestamp_ms, max_timestamp_ms):
            report["skipped_outside_time_range"] += 1
            continue
        rows.append(row)
        report["importable_rows"] += 1
    report["status"] = "supported"
    return rows, report


def write_review_text_jsonl(
    active_session: ScyllaSession,
    prepared: _PreparedStatements,
    path: Path,
    *,
    limit_rows: int = 0,
    progress_every: int = 100_000,
    retry_attempts: int = 3,
    retry_sleep_seconds: float = 1.0,
    min_timestamp_ms: int | None = None,
    max_timestamp_ms: int | None = None,
    source_line_filter: Path | None = None,
) -> tuple[int, dict[str, Any]]:
    report: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "scanned_rows": 0,
        "importable_rows": 0,
        "skipped_without_text": 0,
        "skipped_outside_time_range": 0,
        "skipped_outside_source_lines": 0,
        "json_errors": 0,
        "status": "supported" if path.exists() else "missing",
        "write_status": "written" if path.exists() else "skipped_missing",
    }
    if not path.exists():
        report["written_rows"] = 0
        return 0, report

    written = 0
    line_filter = SourceLineFilter(source_line_filter) if source_line_filter else None
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if limit_rows and report["scanned_rows"] >= limit_rows:
                report["truncated"] = True
                break
            text = line.strip()
            if not text:
                continue
            report["scanned_rows"] += 1
            if line_filter and not line_filter.accepts(line_number):
                report["skipped_outside_source_lines"] += 1
                continue
            try:
                raw = json.loads(text)
            except json.JSONDecodeError:
                report["json_errors"] += 1
                continue
            row = review_text_row(raw, source_path=path, source_line=line_number)
            if row is None:
                report["skipped_without_text"] += 1
                continue
            if not timestamp_in_range(row["timestamp_ms"], min_timestamp_ms, max_timestamp_ms):
                report["skipped_outside_time_range"] += 1
                continue
            _execute_with_retry(
                active_session,
                prepared.by_key,
                _bind_by_key(row),
                retry_attempts=retry_attempts,
                retry_sleep_seconds=retry_sleep_seconds,
            )
            _execute_with_retry(
                active_session,
                prepared.by_item,
                _bind_by_item(row),
                retry_attempts=retry_attempts,
                retry_sleep_seconds=retry_sleep_seconds,
            )
            if row["user_id"]:
                _execute_with_retry(
                    active_session,
                    prepared.by_user,
                    _bind_by_user(row),
                    retry_attempts=retry_attempts,
                    retry_sleep_seconds=retry_sleep_seconds,
                )
            written += 1
            report["importable_rows"] += 1
            if progress_every and written % progress_every == 0:
                print(f"{path}: {written} review text rows written", flush=True)
    report["written_rows"] = written
    return written, report


def _execute_with_retry(
    active_session: ScyllaSession,
    statement: Any,
    parameters: Any,
    *,
    retry_attempts: int,
    retry_sleep_seconds: float,
) -> Any:
    for attempt in range(1, retry_attempts + 1):
        try:
            return active_session.execute(statement, parameters)
        except Exception as exc:
            if attempt >= retry_attempts or not _is_transient_scylla_error(exc):
                raise
            if retry_sleep_seconds:
                time.sleep(retry_sleep_seconds)
    raise RuntimeError("unreachable retry state")


def _is_transient_scylla_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    transient_markers = (
        "timeout",
        "unavailable",
        "overloaded",
        "temporarily unavailable",
        "connection",
    )
    return any(marker in name or marker in message for marker in transient_markers)


def iter_jsonl(path: Path, limit_rows: int = 0) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        yielded = 0
        for line_number, line in enumerate(handle, start=1):
            if limit_rows and yielded >= limit_rows:
                break
            text = line.strip()
            if not text:
                continue
            yielded += 1
            yield line_number, json.loads(text)


def timestamp_in_range(value: int | None, min_timestamp_ms: int | None, max_timestamp_ms: int | None) -> bool:
    if min_timestamp_ms is None and max_timestamp_ms is None:
        return True
    if value is None:
        return False
    if min_timestamp_ms is not None and value < min_timestamp_ms:
        return False
    if max_timestamp_ms is not None and value > max_timestamp_ms:
        return False
    return True


class SourceLineFilter:
    def __init__(self, path: Path) -> None:
        self._handle = path.open("r", encoding="utf-8")
        self._next_line = self._read_next()

    def accepts(self, source_line: int) -> bool:
        while self._next_line is not None and self._next_line < source_line:
            self._next_line = self._read_next()
        if self._next_line == source_line:
            self._next_line = self._read_next()
            return True
        return False

    def _read_next(self) -> int | None:
        while True:
            line = self._handle.readline()
            if not line:
                self._handle.close()
                return None
            text = line.strip()
            if text:
                return int(text)


def resolve_optional_filter(source_line_filters: dict[Path, Path] | None, input_path: Path) -> Path | None:
    if not source_line_filters:
        return None
    return source_line_filters.get(input_path) or source_line_filters.get(Path(str(input_path)))


def review_text_row(raw: dict[str, Any], *, source_path: Path, source_line: int) -> dict[str, Any] | None:
    review_text = clean_text(raw.get("text"))
    review_title = clean_text(raw.get("title"))
    if not review_text and not review_title:
        return None
    timestamp_ms = int_or_none(raw.get("timestamp"))
    return {
        "review_key": review_text_key(raw, source_line=source_line),
        "category": clean_text(raw.get("category")),
        "user_id": clean_text(raw.get("user_id")),
        "parent_asin": clean_text(raw.get("parent_asin")),
        "asin": clean_text(raw.get("asin")),
        "timestamp_ms": timestamp_ms,
        "event_time": event_time_from_ms(timestamp_ms),
        "rating": finite_float_or_none(raw.get("rating")),
        "review_title": review_title,
        "review_text": review_text,
        "text_len": len(review_text),
        "verified_purchase": bool_or_none(raw.get("verified_purchase")),
        "helpful_vote": int_or_none(raw.get("helpful_vote")),
        "source_file": str(source_path),
        "source_line": int(source_line),
        "imported_at": datetime.now(UTC),
    }


def review_text_key(raw: dict[str, Any], *, source_line: int) -> str:
    parts = [
        str(raw.get("category") or ""),
        str(source_line),
        str(raw.get("user_id") or ""),
        str(raw.get("parent_asin") or ""),
        str(raw.get("asin") or ""),
        str(raw.get("timestamp") or ""),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _PreparedStatements:
    by_key: Any
    by_item: Any
    by_user: Any


def _insert_by_key_cql() -> str:
    return """
    INSERT INTO review_text_by_key
    (review_key, category, user_id, parent_asin, asin, timestamp_ms, event_time, rating, review_title, review_text, text_len, verified_purchase, helpful_vote, source_file, source_line, imported_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """


def _insert_by_item_cql() -> str:
    return """
    INSERT INTO review_text_by_item
    (category, parent_asin, event_time, review_key, user_id, asin, rating, text_len, verified_purchase, helpful_vote)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """


def _insert_by_user_cql() -> str:
    return """
    INSERT INTO review_text_by_user
    (user_id, event_time, review_key, category, parent_asin, asin, rating, text_len, verified_purchase, helpful_vote)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """


def _bind_by_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["review_key"],
        row["category"],
        row["user_id"],
        row["parent_asin"],
        row["asin"],
        row["timestamp_ms"],
        row["event_time"],
        row["rating"],
        row["review_title"],
        row["review_text"],
        row["text_len"],
        row["verified_purchase"],
        row["helpful_vote"],
        row["source_file"],
        row["source_line"],
        row["imported_at"],
    )


def _bind_by_item(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["category"],
        row["parent_asin"],
        row["event_time"],
        row["review_key"],
        row["user_id"],
        row["asin"],
        row["rating"],
        row["text_len"],
        row["verified_purchase"],
        row["helpful_vote"],
    )


def _bind_by_user(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["user_id"],
        row["event_time"],
        row["review_key"],
        row["category"],
        row["parent_asin"],
        row["asin"],
        row["rating"],
        row["text_len"],
        row["verified_purchase"],
        row["helpful_vote"],
    )


def _write_import_manifest(active_session: ScyllaSession, *, inputs: list[str], reports: list[dict[str, Any]], row_count: int) -> None:
    prepared = active_session.prepare(
        """
        INSERT INTO review_text_import_manifests
        (import_id, input_paths, row_count, imported_at, status, metrics)
        VALUES (?, ?, ?, ?, ?, ?)
        """
    )
    imported_at = datetime.now(UTC)
    import_id = hashlib.sha256(("\n".join(inputs) + imported_at.isoformat()).encode("utf-8")).hexdigest()
    active_session.execute(prepared, (import_id, json.dumps(inputs, ensure_ascii=False), int(row_count), imported_at, "imported", json.dumps({"reports": reports}, ensure_ascii=False, sort_keys=True, default=str)))


def _connect(args: ScyllaConnectionArgs, *, connect_keyspace: bool = True) -> ScyllaSession:
    try:
        from cassandra.auth import PlainTextAuthProvider  # type: ignore[import-not-found]
        from cassandra.cluster import Cluster  # type: ignore[import-not-found]
        from cassandra.policies import DCAwareRoundRobinPolicy  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("cassandra-driver optional dependency is not installed") from exc

    auth_provider = None
    if args.username or args.password:
        auth_provider = PlainTextAuthProvider(username=args.username, password=args.password)
    cluster_kwargs: dict[str, Any] = {
        "contact_points": list(args.hosts),
        "port": args.port,
        "connect_timeout": args.request_timeout_seconds,
        "control_connection_timeout": args.request_timeout_seconds,
    }
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


def batches(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + batch_size] for index in range(0, len(rows), batch_size)]


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def clean_text(value: Any) -> str:
    return str(value or "").replace("\x00", "").strip()


def int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def finite_float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def event_time_from_ms(value: int | None) -> datetime | None:
    if value is None:
        return None
    seconds = value / 1000.0 if value > 10_000_000_000 else float(value)
    return datetime.fromtimestamp(seconds, UTC)
