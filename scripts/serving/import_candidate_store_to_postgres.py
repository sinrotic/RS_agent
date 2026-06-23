from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from rs_core.data.postgres_dataset import DEFAULT_COMPOSE_FILE, DEFAULT_DB_NAME, DEFAULT_DB_USER, DEFAULT_POSTGRES_SERVICE

PROJECT_ROOT = Path(__file__).resolve().parents[2]
Runner = Callable[[list[str], str], subprocess.CompletedProcess[str]]
SchemaKind = Literal["usercf_candidates", "item_neighbors", "unsupported"]


@dataclass(frozen=True)
class ImportPlan:
    path: Path
    schema: SchemaKind
    rows: list[dict[str, Any]]
    report: dict[str, Any]


def main() -> None:
    parser = argparse.ArgumentParser(description="Safety-first candidate store importer; dry-run is the default.")
    parser.add_argument("--input", type=Path, action="append", default=[], help="JSONL artifact path to scan/import. May be repeated.")
    parser.add_argument("--limit-rows", type=int, default=1000, help="Maximum rows to scan/import per input file. 0 means no limit.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per INSERT statement in write mode.")
    parser.add_argument("--artifact-id", default="", help="Artifact id stamped onto imported rows.")
    parser.add_argument("--source", default="", help="Override source stamped onto imported rows.")
    parser.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE, help="Docker compose file for local Postgres psql.")
    parser.add_argument("--postgres-service", default=DEFAULT_POSTGRES_SERVICE, help="Docker compose service name for Postgres.")
    parser.add_argument("--db-user", default=DEFAULT_DB_USER, help="Postgres user name; no password is accepted on the command line.")
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME, help="Postgres database name.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Scan only; do not write to Postgres. This is the default.")
    mode.add_argument("--write", action="store_true", help="Write supported rows through docker compose psql stdin.")
    args = parser.parse_args()

    result = import_candidate_store_to_postgres(
        inputs=args.input,
        limit_rows=max(0, int(args.limit_rows)),
        batch_size=max(1, int(args.batch_size)),
        artifact_id=str(args.artifact_id or ""),
        source=str(args.source or ""),
        write=bool(args.write),
        compose_file=str(args.compose_file),
        postgres_service=str(args.postgres_service),
        db_user=str(args.db_user),
        db_name=str(args.db_name),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def import_candidate_store_to_postgres(
    *,
    inputs: list[Path],
    limit_rows: int = 1000,
    batch_size: int = 500,
    artifact_id: str = "",
    source: str = "",
    write: bool = False,
    runner: Runner | None = None,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    postgres_service: str = DEFAULT_POSTGRES_SERVICE,
    db_user: str = DEFAULT_DB_USER,
    db_name: str = DEFAULT_DB_NAME,
) -> dict[str, Any]:
    plans = [_plan_jsonl(_resolve_path(path), limit_rows, artifact_id=artifact_id, source_override=source) for path in inputs]
    reports = [plan.report for plan in plans]
    if not write:
        return {"dry_run": True, "input_count": len(inputs), "reports": reports}

    command = _psql_command(compose_file=compose_file, postgres_service=postgres_service, db_user=db_user, db_name=db_name)
    write_reports: list[dict[str, Any]] = []
    for plan in plans:
        report = dict(plan.report)
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
        inserted_batches = 0
        for batch_index, batch in enumerate(_batches(plan.rows, batch_size), start=1):
            sql = _insert_sql(plan.schema, batch)
            proc = _run_psql(command, sql, runner=runner)
            if proc.returncode != 0:
                raise RuntimeError(f"candidate store import failed path={plan.path.name} batch={batch_index} returncode={proc.returncode}")
            inserted_batches += 1
        report["write_status"] = "written"
        report["batches"] = inserted_batches
        report["written_rows"] = len(plan.rows)
        write_reports.append(report)
    return {"dry_run": False, "input_count": len(inputs), "reports": write_reports}


def _resolve_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _plan_jsonl(path: Path, limit_rows: int, *, artifact_id: str, source_override: str) -> ImportPlan:
    report: dict[str, Any] = {"path": str(path), "exists": path.exists(), "scanned_rows": 0, "candidate_like_rows": 0, "sources": {}}
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
            row_schema = _classify_row(raw)
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


def _classify_row(row: Any) -> SchemaKind:
    if not isinstance(row, dict):
        return "unsupported"
    if row.get("user_id") and (row.get("parent_asin") or row.get("item_id")):
        return "usercf_candidates"
    if (row.get("src_item") or row.get("src_item_id")) and (row.get("dst_item") or row.get("dst_item_id")):
        return "item_neighbors"
    return "unsupported"


def _normalize_row(row: dict[str, Any], schema: SchemaKind, *, artifact_id: str, source_override: str, rank: int) -> dict[str, Any] | None:
    if schema == "item_neighbors":
        src_item_id = _clean_text(row.get("src_item") or row.get("src_item_id"))
        dst_item_id = _clean_text(row.get("dst_item") or row.get("dst_item_id"))
        score = _score_for_row(row, _source_for_row(row, source_override, default="item_neighbors", prefer_row_source=True))
        if not src_item_id or not dst_item_id or score is None:
            return None
        source = _source_for_row(row, source_override, default="item_neighbors", prefer_row_source=True)
        return {
            "source": source,
            "src_item_id": src_item_id,
            "dst_item_id": dst_item_id,
            "score": score,
            "rank": _int_or_default(row.get("rank"), rank),
            "category": _clean_text(row.get("category")),
            "artifact_id": artifact_id or _clean_text(row.get("artifact_id")),
            "metadata": _metadata_for_row(row),
        }
    if schema == "usercf_candidates":
        user_id = _clean_text(row.get("user_id"))
        parent_asin = _clean_text(row.get("parent_asin") or row.get("item_id"))
        source = _source_for_row(row, source_override, default="usercf_recall", prefer_row_source=False)
        score = _score_for_row(row, source)
        if not user_id or not parent_asin or score is None:
            return None
        return {
            "source": source,
            "user_id": user_id,
            "parent_asin": parent_asin,
            "score": score,
            "rank": _int_or_default(row.get("rank"), rank),
            "category": _clean_text(row.get("category")),
            "artifact_id": artifact_id or _clean_text(row.get("artifact_id")),
            "metadata": _metadata_for_row(row),
        }
    return None


def _insert_sql(schema: SchemaKind, rows: list[dict[str, Any]]) -> str:
    if schema == "item_neighbors":
        values = ",\n".join(
            "(" + ", ".join([
                _sql_text(row["source"]),
                _sql_text(row["src_item_id"]),
                _sql_text(row["dst_item_id"]),
                _sql_number(row["score"]),
                _sql_int(row["rank"]),
                _sql_text(row.get("category")),
                _sql_text(row.get("artifact_id")),
                _sql_jsonb(row.get("metadata", {})),
            ]) + ")"
            for row in rows
        )
        return f"""
INSERT INTO item_neighbors (source, src_item_id, dst_item_id, score, rank, category, artifact_id, metadata)
VALUES
{values}
ON CONFLICT (source, src_item_id, dst_item_id) DO UPDATE SET
    score = EXCLUDED.score,
    rank = EXCLUDED.rank,
    category = EXCLUDED.category,
    artifact_id = EXCLUDED.artifact_id,
    metadata = EXCLUDED.metadata,
    updated_at = now()
""".strip()
    if schema == "usercf_candidates":
        values = ",\n".join(
            "(" + ", ".join([
                _sql_text(row["source"]),
                _sql_text(row["user_id"]),
                _sql_text(row["parent_asin"]),
                _sql_number(row["score"]),
                _sql_int(row["rank"]),
                _sql_text(row.get("category")),
                _sql_text(row.get("artifact_id")),
                _sql_jsonb(row.get("metadata", {})),
            ]) + ")"
            for row in rows
        )
        return f"""
INSERT INTO usercf_candidates (source, user_id, parent_asin, score, rank, category, artifact_id, metadata)
VALUES
{values}
ON CONFLICT (source, user_id, parent_asin) DO UPDATE SET
    score = EXCLUDED.score,
    rank = EXCLUDED.rank,
    category = EXCLUDED.category,
    artifact_id = EXCLUDED.artifact_id,
    metadata = EXCLUDED.metadata,
    updated_at = now()
""".strip()
    raise ValueError(f"unsupported schema: {schema}")


def _psql_command(*, compose_file: str, postgres_service: str, db_user: str, db_name: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        compose_file,
        "--profile",
        "postgres",
        "exec",
        "-T",
        postgres_service,
        "psql",
        "-U",
        db_user,
        "-d",
        db_name,
        "-v",
        "ON_ERROR_STOP=1",
        "-X",
        "-q",
    ]


def _run_psql(command: list[str], sql: str, *, runner: Runner | None) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(command, sql)
    return subprocess.run(command, input=sql, text=True, encoding="utf-8", capture_output=True, timeout=60, check=False)


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
        else:
            key = (str(len(by_key)),)
        by_key[key] = row
    return list(by_key.values()), len(rows) - len(by_key)


def _source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = str(row.get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _has_partial_artifact_errors(report: dict[str, Any]) -> bool:
    return any(int(report.get(key, 0)) > 0 for key in ("json_errors", "mixed_schema_rows", "unsupported_rows"))


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


def _sql_text(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return "NULL"
    return "'" + text.replace("'", "''") + "'"


def _sql_number(value: Any) -> str:
    parsed = _finite_float_or_none(value)
    return str(parsed if parsed is not None else 0.0)


def _sql_int(value: Any) -> str:
    if value is None:
        return "NULL"
    return str(_int_or_default(value, 0))


def _sql_jsonb(value: Any) -> str:
    payload = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)
    return "'" + payload.replace("'", "''") + "'::jsonb"


if __name__ == "__main__":
    main()
