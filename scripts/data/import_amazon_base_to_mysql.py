from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from rs_core.data.mysql_dataset import DEFAULT_COMPOSE_FILE, DEFAULT_DB_NAME, DEFAULT_DB_USER, DEFAULT_MYSQL_SERVICE

DEFAULT_MANIFEST = "data/processed/amazon_2023_base/manifest.json"
DEFAULT_SCHEMA_FILE = "scripts/data/sql/create_amazon_base_raw_tables.mysql.sql"
DEFAULT_IMPORT_SOURCE = "amazon_2023_base"

ITEM_COLUMNS = [
    "dataset",
    "category",
    "parent_asin",
    "title",
    "main_category",
    "categories",
    "description",
    "features",
    "images",
    "price",
    "price_raw",
    "average_rating",
    "rating_number",
    "store",
    "details",
    "bought_together",
    "source_file",
    "source_line",
]
REVIEW_COLUMNS = [
    "review_key",
    "dataset",
    "category",
    "user_id",
    "parent_asin",
    "asin",
    "rating",
    "text_len",
    "has_review_title",
    "has_review_text",
    "review_text_ref",
    "timestamp_ms",
    "event_time",
    "verified_purchase",
    "helpful_vote",
    "source_file",
    "source_line",
]
JSON_COLUMNS = {"categories", "description", "features", "images", "details", "bought_together"}
NUMERIC_COLUMNS = {"price", "average_rating", "rating", "rating_number", "text_len", "timestamp_ms", "helpful_vote", "source_line"}
BOOL_COLUMNS = {"verified_purchase", "has_review_title", "has_review_text"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Amazon Reviews 2023 base JSONL files into local/trial MySQL raw tables.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--schema-file", default=DEFAULT_SCHEMA_FILE)
    parser.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--mysql-service", default=DEFAULT_MYSQL_SERVICE)
    parser.add_argument("--db-user", default=DEFAULT_DB_USER)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--import-source", default=DEFAULT_IMPORT_SOURCE)
    parser.add_argument("--categories", nargs="+", default=None, help="Optional category filter, e.g. Electronics Office_Products.")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows per selected input file for smoke imports.")
    parser.add_argument("--recent2y-source-dir", default=None, help="Optional recent2y canonical dataset directory used only as a filter for base metadata/reviews.")
    parser.add_argument(
        "--review-filter-mode",
        choices=["strict", "item"],
        default="strict",
        help="When --recent2y-source-dir is set, filter base reviews by strict user_id+parent_asin+timestamp keys or by item universe only.",
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--skip-items", action="store_true")
    parser.add_argument("--skip-reviews", action="store_true")
    parser.add_argument("--truncate", action="store_true", help="Truncate selected raw tables before import. Use before deliberate reloads.")
    parser.add_argument("--resume", action="store_true", help="Resume from the current max source_line per category/table instead of truncating.")
    parser.add_argument(
        "--resume-overlap",
        type=int,
        default=0,
        help="When resuming, reprocess this many source lines before the current max source_line for idempotent recovery.",
    )
    parser.add_argument("--create-schema", action="store_true", help="Run the raw table DDL before importing.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report planned inputs only. This is the default.")
    mode.add_argument("--write", action="store_true", help="Write to MySQL. Password is read inside the container from MYSQL_PASSWORD.")
    return parser.parse_args()


def import_amazon_base_to_mysql(
    *,
    manifest_path: Path,
    schema_file: Path = Path(DEFAULT_SCHEMA_FILE),
    categories: list[str] | None = None,
    limit: int | None = None,
    recent2y_source_dir: Path | None = None,
    review_filter_mode: str = "strict",
    batch_size: int = 100,
    import_source: str = DEFAULT_IMPORT_SOURCE,
    truncate: bool = False,
    resume: bool = False,
    resume_overlap: int = 0,
    create_schema: bool = False,
    skip_items: bool = False,
    skip_reviews: bool = False,
    write: bool = False,
    runner: Any | None = None,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    mysql_service: str = DEFAULT_MYSQL_SERVICE,
    db_user: str = DEFAULT_DB_USER,
    db_name: str = DEFAULT_DB_NAME,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    outputs = selected_outputs(manifest, manifest_path, categories)
    universe = load_recent2y_universe(recent2y_source_dir) if recent2y_source_dir is not None else None
    reports = build_reports(outputs, skip_items=skip_items, skip_reviews=skip_reviews)
    if universe is not None:
        reports.append(
            {
                "kind": "recent2y_filter",
                "path": str(recent2y_source_dir),
                "exists": recent2y_source_dir.exists(),
                "item_count": len(universe.item_ids),
                "interaction_key_count": len(universe.interaction_keys),
                "review_filter_mode": review_filter_mode,
            }
        )

    if not write:
        return {"dry_run": True, "manifest": str(manifest_path), "reports": reports}

    for report in reports:
        if report.get("selected", False) and not report["exists"]:
            raise FileNotFoundError(f"selected input file not found: {report['path']}")

    if truncate and resume:
        raise ValueError("--truncate and --resume cannot be used together")

    command = _mysql_command(compose_file=compose_file, mysql_service=mysql_service, db_user=db_user, db_name=db_name)
    if create_schema:
        if not schema_file.exists():
            raise FileNotFoundError(f"schema file not found: {schema_file}")
        _run_mysql(command, schema_file.read_text(encoding="utf-8"), runner=runner)
    if truncate:
        statements: list[str] = []
        if not skip_reviews:
            statements.append("TRUNCATE TABLE amazon_reviews_base")
        if not skip_items:
            statements.append("TRUNCATE TABLE amazon_items_base")
        if statements:
            _run_mysql(command, ";\n".join(statements) + ";", runner=runner)

    resume_points = _resume_points(command, runner=runner) if resume else {}
    counts = {"amazon_items_base": 0, "amazon_reviews_base": 0}
    for output in outputs:
        category = str(output["category"])
        if not skip_items:
            start_line = _resume_start_line(resume_points, "amazon_items_base", category, resume_overlap)
            item_objects = iter_jsonl(output["metadata_path"], limit, start_line=start_line)
            if universe is not None:
                item_objects = ((line, obj) for line, obj in item_objects if str(obj.get("parent_asin") or "") in universe.item_ids)
            rows = (item_row(obj, source_path=output["metadata_path"], source_line=line) for line, obj in item_objects)
            counts["amazon_items_base"] += _write_rows(command, "amazon_items_base", ITEM_COLUMNS, rows, batch_size, runner=runner)
        if not skip_reviews:
            start_line = _resume_start_line(resume_points, "amazon_reviews_base", category, resume_overlap)
            review_objects = iter_jsonl(output["reviews_path"], limit, start_line=start_line)
            if universe is not None:
                review_objects = filter_reviews_by_universe(review_objects, universe=universe, mode=review_filter_mode)
            rows = (review_row(obj, source_path=output["reviews_path"], source_line=line) for line, obj in review_objects)
            counts["amazon_reviews_base"] += _write_rows(command, "amazon_reviews_base", REVIEW_COLUMNS, rows, batch_size, runner=runner)

    result: dict[str, Any] = {"dry_run": False, "manifest": str(manifest_path), "reports": reports, "imported": counts, "import_source": import_source}
    if universe is not None:
        result["recent2y_filter"] = {"item_count": len(universe.item_ids), "interaction_key_count": len(universe.interaction_keys), "review_filter_mode": review_filter_mode}
    if resume:
        result["resume_points"] = {f"{table}:{category}": line for (table, category), line in resume_points.items()}
    return result


class Recent2yUniverse:
    def __init__(self, *, item_ids: set[str], interaction_keys: set[tuple[str, str, str]]) -> None:
        self.item_ids = item_ids
        self.interaction_keys = interaction_keys


def load_recent2y_universe(source_dir: Path) -> Recent2yUniverse:
    if not source_dir.exists():
        raise FileNotFoundError(f"recent2y source dir not found: {source_dir}")
    item_ids: set[str] = set()
    interaction_keys: set[tuple[str, str, str]] = set()
    item_file = source_dir / "canonical_items.jsonl"
    if item_file.exists():
        for obj in iter_jsonl_objects(item_file):
            parent_asin = safe_key(obj.get("parent_asin"))
            if parent_asin:
                item_ids.add(parent_asin)
    for filename in ("canonical_interactions.train.jsonl", "canonical_interactions.valid.jsonl", "canonical_interactions.test.jsonl", "canonical_interactions.jsonl"):
        path = source_dir / filename
        if not path.exists():
            continue
        for obj in iter_jsonl_objects(path):
            user_id = safe_key(obj.get("user_id"))
            parent_asin = safe_key(obj.get("parent_asin"))
            timestamp = normalize_timestamp_key(obj.get("timestamp"))
            if parent_asin:
                item_ids.add(parent_asin)
            if user_id and parent_asin and timestamp:
                interaction_keys.add((user_id, parent_asin, timestamp))
    return Recent2yUniverse(item_ids=item_ids, interaction_keys=interaction_keys)


def filter_reviews_by_universe(
    rows: Iterable[tuple[int, dict[str, Any]]],
    *,
    universe: Recent2yUniverse,
    mode: str,
) -> Iterable[tuple[int, dict[str, Any]]]:
    for line, obj in rows:
        parent_asin = safe_key(obj.get("parent_asin"))
        if mode == "item":
            if parent_asin in universe.item_ids:
                yield line, obj
            continue
        user_id = safe_key(obj.get("user_id"))
        timestamp = normalize_timestamp_key(obj.get("timestamp"))
        if user_id and parent_asin and timestamp and (user_id, parent_asin, timestamp) in universe.interaction_keys:
            yield line, obj


def iter_jsonl_objects(path: Path) -> Iterable[dict[str, Any]]:
    for _, obj in iter_jsonl(path, None):
        yield obj


def safe_key(value: Any) -> str:
    return str(value or "")


def normalize_timestamp_key(value: Any) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def selected_outputs(manifest: dict[str, Any], manifest_path: Path, categories: list[str] | None) -> list[dict[str, Any]]:
    wanted = set(categories or [])
    outputs = []
    for output in manifest.get("outputs", []):
        category = output.get("category")
        if wanted and category not in wanted:
            continue
        reviews_path = resolve_manifest_path(manifest_path, output.get("reviews_path"))
        metadata_path = resolve_manifest_path(manifest_path, output.get("metadata_path"))
        outputs.append({"category": category, "reviews_path": reviews_path, "metadata_path": metadata_path})
    if wanted and {str(output["category"]) for output in outputs} != wanted:
        found = {str(output["category"]) for output in outputs}
        missing = sorted(wanted - found)
        raise ValueError(f"categories not found in manifest: {missing}")
    return outputs


def resolve_manifest_path(manifest_path: Path, value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def build_reports(outputs: list[dict[str, Any]], *, skip_items: bool, skip_reviews: bool) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for output in outputs:
        reports.append(
            {
                "category": output["category"],
                "kind": "items",
                "table": "amazon_items_base",
                "path": str(output["metadata_path"]),
                "exists": output["metadata_path"].exists(),
                "selected": not skip_items,
            }
        )
        reports.append(
            {
                "category": output["category"],
                "kind": "reviews",
                "table": "amazon_reviews_base",
                "path": str(output["reviews_path"]),
                "exists": output["reviews_path"].exists(),
                "selected": not skip_reviews,
            }
        )
    return reports


def iter_jsonl(path: Path, limit: int | None, *, start_line: int = 1) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as f:
        seen = 0
        for line_number, line in enumerate(f, start=1):
            if line_number < start_line:
                continue
            line = line.strip()
            if not line:
                continue
            if limit is not None and seen >= limit:
                break
            seen += 1
            yield line_number, json.loads(line)


def _resume_start_line(resume_points: dict[tuple[str, str], int], table: str, category: str, overlap: int) -> int:
    max_source_line = resume_points.get((table, category), 0)
    if max_source_line <= 0:
        return 1
    return max(1, max_source_line - max(0, overlap) + 1)


def _resume_points(command: list[str], *, runner: Any | None) -> dict[tuple[str, str], int]:
    sql = """
SELECT 'amazon_items_base', category, COALESCE(MAX(source_line), 0)
FROM amazon_items_base
GROUP BY category;
SELECT 'amazon_reviews_base', category, COALESCE(MAX(source_line), 0)
FROM amazon_reviews_base
GROUP BY category;
""".strip()
    proc = _run_mysql(command, sql, runner=runner)
    points: dict[tuple[str, str], int] = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        table, category, source_line = parts
        try:
            points[(table, category)] = int(source_line)
        except ValueError:
            continue
    return points


def item_row(obj: dict[str, Any], *, source_path: Path, source_line: int) -> list[Any]:
    return [
        safe_text(obj.get("dataset"), 128),
        safe_text(obj.get("category"), 128),
        safe_text(obj.get("parent_asin"), 64),
        safe_text(obj.get("title")),
        safe_text(obj.get("main_category"), 255),
        obj.get("categories") or [],
        obj.get("description") or [],
        obj.get("features") or [],
        obj.get("images") or [],
        obj.get("price"),
        safe_text(obj.get("price")),
        obj.get("average_rating"),
        obj.get("rating_number"),
        safe_text(obj.get("store"), 255),
        obj.get("details"),
        obj.get("bought_together"),
        str(source_path),
        source_line,
    ]


def review_row(obj: dict[str, Any], *, source_path: Path, source_line: int) -> list[Any]:
    timestamp_ms = obj.get("timestamp")
    return [
        review_key(obj, source_line=source_line),
        safe_text(obj.get("dataset"), 128),
        safe_text(obj.get("category"), 128),
        safe_text(obj.get("user_id"), 128),
        safe_text(obj.get("parent_asin"), 64),
        safe_text(obj.get("asin"), 64),
        obj.get("rating"),
        obj.get("text_len"),
        bool(safe_text(obj.get("title"))),
        bool(safe_text(obj.get("text"))),
        review_key(obj, source_line=source_line),
        timestamp_ms,
        ms_to_mysql_datetime(timestamp_ms),
        obj.get("verified_purchase"),
        obj.get("helpful_vote"),
        str(source_path),
        source_line,
    ]


def review_key(obj: dict[str, Any], *, source_line: int) -> str:
    parts = [
        str(obj.get("category") or ""),
        str(source_line),
        str(obj.get("user_id") or ""),
        str(obj.get("parent_asin") or ""),
        str(obj.get("asin") or ""),
        str(obj.get("timestamp") or ""),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def safe_text(value: Any, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "")
    if max_len is not None and len(text) > max_len:
        return text[:max_len]
    return text


def ms_to_mysql_datetime(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000:
        ts /= 1000.0
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S")


def _write_rows(command: list[str], table: str, columns: list[str], rows: Iterable[list[Any]], batch_size: int, *, runner: Any | None) -> int:
    if runner is not None:
        return _write_rows_with_runner(command, table, columns, rows, batch_size, runner=runner)
    return _write_rows_streaming(command, table, columns, rows, batch_size)


def _write_rows_with_runner(
    command: list[str],
    table: str,
    columns: list[str],
    rows: Iterable[list[Any]],
    batch_size: int,
    *,
    runner: Any,
) -> int:
    count = 0
    batch: list[list[Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            _run_mysql(command, _insert_sql(table, columns, batch), runner=runner)
            count += len(batch)
            print(f"{table}: {count} rows inserted", file=sys.stderr, flush=True)
            batch = []
    if batch:
        _run_mysql(command, _insert_sql(table, columns, batch), runner=runner)
        count += len(batch)
    print(f"{table}: {count} rows inserted", file=sys.stderr, flush=True)
    return count


def _write_rows_streaming(command: list[str], table: str, columns: list[str], rows: Iterable[list[Any]], batch_size: int) -> int:
    count = 0
    batch: list[list[Any]] = []
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        if proc.stdin is None:
            raise RuntimeError("mysql import command failed")
        proc.stdin.write("SET SESSION unique_checks=0;\n")
        proc.stdin.write("SET SESSION foreign_key_checks=0;\n")
        for row in rows:
            batch.append(row)
            if len(batch) >= batch_size:
                proc.stdin.write(_insert_sql(table, columns, batch))
                proc.stdin.write(";\n")
                count += len(batch)
                print(f"{table}: {count} rows inserted", file=sys.stderr, flush=True)
                batch = []
        if batch:
            proc.stdin.write(_insert_sql(table, columns, batch))
            proc.stdin.write(";\n")
            count += len(batch)
        proc.stdin.write("SET SESSION foreign_key_checks=1;\n")
        proc.stdin.write("SET SESSION unique_checks=1;\n")
        proc.stdin.close()
        stdout = proc.stdout.read() if proc.stdout is not None else ""
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        returncode = proc.wait()
    except BrokenPipeError as exc:
        proc.kill()
        proc.wait()
        raise RuntimeError("mysql import command failed") from exc
    except Exception:
        proc.kill()
        proc.wait()
        raise
    if returncode != 0:
        _ = stdout, stderr
        raise RuntimeError("mysql import command failed")
    print(f"{table}: {count} rows inserted", file=sys.stderr, flush=True)
    return count


def _insert_sql(table: str, columns: list[str], rows: list[list[Any]]) -> str:
    values = ",\n".join("(" + ", ".join(_sql_value(column, value) for column, value in zip(columns, row, strict=True)) + ")" for row in rows)
    update_columns = [column for column in columns if column not in _key_columns(table)]
    updates = ",\n    ".join(f"{column} = VALUES({column})" for column in update_columns)
    return f"""
INSERT INTO {table} ({", ".join(columns)})
VALUES
{values}
ON DUPLICATE KEY UPDATE
    {updates}
""".strip()


def _key_columns(table: str) -> set[str]:
    if table == "amazon_items_base":
        return {"category", "parent_asin"}
    if table == "amazon_reviews_base":
        return {"review_key"}
    return set()


def _sql_value(column: str, value: Any) -> str:
    if value is None or value == "":
        return "NULL"
    if column in JSON_COLUMNS:
        return "CAST(" + _sql_text(json_dumps(value)) + " AS JSON)"
    if column in BOOL_COLUMNS:
        return "1" if bool(value) else "0"
    if column in NUMERIC_COLUMNS:
        return _sql_number(value)
    return _sql_text(value)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _sql_text(value: Any) -> str:
    text = str(value or "").replace("\x00", "")
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def _sql_number(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return "NULL"


def _mysql_command(*, compose_file: str, mysql_service: str, db_user: str, db_name: str) -> list[str]:
    mysql_command = (
        'MYSQL_PWD="$MYSQL_PASSWORD" mysql '
        "--batch --raw --skip-column-names --default-character-set=utf8mb4 "
        f"-u {_shell_quote(db_user)} {_shell_quote(db_name)}"
    )
    return ["docker", "compose", "-f", compose_file, "--profile", "mysql", "exec", "-T", mysql_service, "sh", "-lc", mysql_command]


def _run_mysql(command: list[str], sql: str, *, runner: Any | None) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(command, sql)
    proc = subprocess.run(command, input=sql, text=True, encoding="utf-8", capture_output=True, timeout=300, check=False)
    if proc.returncode != 0:
        raise RuntimeError("mysql import command failed")
    return proc


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def main() -> int:
    args = parse_args()
    result = import_amazon_base_to_mysql(
        manifest_path=Path(args.manifest),
        schema_file=Path(args.schema_file),
        categories=list(args.categories) if args.categories else None,
        limit=args.limit,
        batch_size=max(1, int(args.batch_size)),
        recent2y_source_dir=Path(args.recent2y_source_dir) if args.recent2y_source_dir else None,
        review_filter_mode=str(args.review_filter_mode),
        import_source=str(args.import_source),
        truncate=bool(args.truncate),
        resume=bool(args.resume),
        resume_overlap=max(0, int(args.resume_overlap)),
        create_schema=bool(args.create_schema),
        skip_items=bool(args.skip_items),
        skip_reviews=bool(args.skip_reviews),
        write=bool(args.write),
        compose_file=str(args.compose_file),
        mysql_service=str(args.mysql_service),
        db_user=str(args.db_user),
        db_name=str(args.db_name),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
