from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from rs_core.serving.infrastructure.stores.candidate_import_plan import SchemaKind, batches, has_partial_artifact_errors, plan_jsonl, resolve_path

DEFAULT_COMPOSE_FILE = "deploy/local/docker-compose.yml"
DEFAULT_MYSQL_SERVICE = "mysql"
DEFAULT_DB_USER = "rs_agent"
DEFAULT_DB_NAME = "rs_agent"
Runner = Callable[[list[str], str], subprocess.CompletedProcess[str]]


def import_candidate_store_to_mysql(
    *,
    inputs: list[Path],
    limit_rows: int = 1000,
    batch_size: int = 500,
    artifact_id: str = "",
    source: str = "",
    write: bool = False,
    runner: Runner | None = None,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    mysql_service: str = DEFAULT_MYSQL_SERVICE,
    db_user: str = DEFAULT_DB_USER,
    db_name: str = DEFAULT_DB_NAME,
) -> dict[str, Any]:
    plans = [plan_jsonl(resolve_path(path), limit_rows, artifact_id=artifact_id, source_override=source, classify_pool_candidates=False) for path in inputs]
    reports = [plan.report for plan in plans]
    if not write:
        return {"dry_run": True, "input_count": len(inputs), "reports": reports}

    command = _mysql_command(compose_file=compose_file, mysql_service=mysql_service, db_user=db_user, db_name=db_name)
    write_reports: list[dict[str, Any]] = []
    for plan in plans:
        report = dict(plan.report)
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
        inserted_batches = 0
        for batch_index, batch in enumerate(batches(plan.rows, batch_size), start=1):
            sql = _insert_sql(plan.schema, batch)
            proc = _run_mysql(command, sql, runner=runner)
            if proc.returncode != 0:
                raise RuntimeError(f"candidate store MySQL import failed path={plan.path.name} batch={batch_index} returncode={proc.returncode}")
            inserted_batches += 1
        report["write_status"] = "written"
        report["batches"] = inserted_batches
        report["written_rows"] = len(plan.rows)
        write_reports.append(report)
    return {"dry_run": False, "input_count": len(inputs), "reports": write_reports}


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
                _sql_json(row.get("metadata", {})),
            ]) + ")"
            for row in rows
        )
        return f"""
INSERT INTO item_neighbors (source, src_item_id, dst_item_id, score, `rank`, category, artifact_id, metadata)
VALUES
{values}
ON DUPLICATE KEY UPDATE
    score = VALUES(score),
    `rank` = VALUES(`rank`),
    category = VALUES(category),
    artifact_id = VALUES(artifact_id),
    metadata = VALUES(metadata),
    updated_at = CURRENT_TIMESTAMP
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
                _sql_json(row.get("metadata", {})),
            ]) + ")"
            for row in rows
        )
        return f"""
INSERT INTO usercf_candidates (source, user_id, parent_asin, score, `rank`, category, artifact_id, metadata)
VALUES
{values}
ON DUPLICATE KEY UPDATE
    score = VALUES(score),
    `rank` = VALUES(`rank`),
    category = VALUES(category),
    artifact_id = VALUES(artifact_id),
    metadata = VALUES(metadata),
    updated_at = CURRENT_TIMESTAMP
""".strip()
    raise ValueError(f"unsupported schema: {schema}")


def _mysql_command(*, compose_file: str, mysql_service: str, db_user: str, db_name: str) -> list[str]:
    mysql_command = (
        'MYSQL_PWD="$MYSQL_PASSWORD" mysql '
        '--batch --raw --skip-column-names --default-character-set=utf8mb4 '
        f'-u {_shell_quote(db_user)} {_shell_quote(db_name)}'
    )
    return ["docker", "compose", "-f", compose_file, "--profile", "mysql", "exec", "-T", mysql_service, "sh", "-lc", mysql_command]


def _run_mysql(command: list[str], sql: str, *, runner: Runner | None) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(command, sql)
    return subprocess.run(command, input=sql, text=True, encoding="utf-8", capture_output=True, timeout=60, check=False)


def _sql_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "NULL"
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def _sql_number(value: Any) -> str:
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return "0.0"


def _sql_int(value: Any) -> str:
    if value is None:
        return "NULL"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return "0"


def _sql_json(value: Any) -> str:
    payload = json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)
    return "CAST(" + _sql_text(payload) + " AS JSON)"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
