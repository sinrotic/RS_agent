from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from rs_core.data.mysql_dataset import DEFAULT_COMPOSE_FILE, DEFAULT_DB_NAME, DEFAULT_DB_USER, DEFAULT_MYSQL_SERVICE

DEFAULT_SOURCE_DIR = "data/processed/amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_IMPORT_SOURCE = "recent_2y"

PRODUCT_COLUMNS = ["parent_asin", "title", "main_category", "categories", "brand", "price", "rating", "description", "features", "metadata"]
INTERACTION_COLUMNS = ["user_id", "parent_asin", "event_type", "event_time", "rating", "label_binary", "split", "source", "metadata"]
SEQUENCE_COLUMNS = ["user_id", "window_name", "recent_item_sequence", "recent_positive_item_sequence", "recent_strong_positive_item_sequence", "metadata"]
JSON_COLUMNS = {"categories", "features", "metadata", "recent_item_sequence", "recent_positive_item_sequence", "recent_strong_positive_item_sequence"}
NUMERIC_COLUMNS = {"price", "rating", "label_binary"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch import the recent 2y dataset into the local/trial MySQL database.")
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--mysql-service", default=DEFAULT_MYSQL_SERVICE)
    parser.add_argument("--db-user", default=DEFAULT_DB_USER)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--import-source", default=DEFAULT_IMPORT_SOURCE)
    parser.add_argument("--items-file", default=None, help="Item JSONL filename under source-dir. Defaults to canonical_items.all.jsonl when present, otherwise canonical_items.jsonl.")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows per input file for smoke imports.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--truncate", action="store_true", help="Truncate products/interactions/user_sequences before import. Use before full imports.")
    parser.add_argument("--skip-products", action="store_true")
    parser.add_argument("--skip-interactions", action="store_true")
    parser.add_argument("--skip-user-sequences", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report planned input files only. This is the default.")
    mode.add_argument("--write", action="store_true", help="Write to MySQL.")
    return parser.parse_args()


def import_recent2y_to_mysql(
    *,
    source_dir: Path,
    items_file: str | None = None,
    limit: int | None = None,
    batch_size: int = 500,
    import_source: str = DEFAULT_IMPORT_SOURCE,
    truncate: bool = False,
    skip_products: bool = False,
    skip_interactions: bool = False,
    skip_user_sequences: bool = False,
    write: bool = False,
    runner: Any | None = None,
    compose_file: str = DEFAULT_COMPOSE_FILE,
    mysql_service: str = DEFAULT_MYSQL_SERVICE,
    db_user: str = DEFAULT_DB_USER,
    db_name: str = DEFAULT_DB_NAME,
) -> dict[str, Any]:
    if items_file is None:
        items_file = "canonical_items.all.jsonl" if (source_dir / "canonical_items.all.jsonl").exists() else "canonical_items.jsonl"
    inputs = {
        "products": source_dir / items_file,
        "interactions": source_dir / "canonical_interactions.jsonl",
        "user_sequences": source_dir / "user_sequences.jsonl",
    }
    selected = {
        "products": not skip_products,
        "interactions": not skip_interactions,
        "user_sequences": not skip_user_sequences,
    }
    reports = {name: {"path": str(path), "exists": path.exists(), "selected": selected[name]} for name, path in inputs.items()}
    if not write:
        return {"dry_run": True, "reports": reports}
    for name, report in reports.items():
        if report["selected"] and not report["exists"]:
            raise FileNotFoundError(f"{name} file not found: {report['path']}")

    command = _mysql_command(compose_file=compose_file, mysql_service=mysql_service, db_user=db_user, db_name=db_name)
    if truncate:
        _run_mysql(command, "TRUNCATE TABLE interactions;\nTRUNCATE TABLE user_sequences;\nTRUNCATE TABLE products;", runner=runner)

    counts: dict[str, int] = {}
    if not skip_products:
        rows = (product_row(obj, import_source) for obj in iter_jsonl(inputs["products"], limit))
        counts["products"] = _write_rows(command, "products", PRODUCT_COLUMNS, rows, batch_size, runner=runner)
    if not skip_interactions:
        rows = (interaction_row(obj, import_source) for obj in iter_jsonl(inputs["interactions"], limit))
        counts["interactions"] = _write_rows(command, "interactions", INTERACTION_COLUMNS, rows, batch_size, runner=runner)
    if not skip_user_sequences:
        rows = (sequence_row(obj, import_source) for obj in iter_jsonl(inputs["user_sequences"], limit))
        counts["user_sequences"] = _write_rows(command, "user_sequences", SEQUENCE_COLUMNS, rows, batch_size, runner=runner)
    return {"dry_run": False, "reports": reports, "imported": counts}


def iter_jsonl(path: Path, limit: int | None) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        seen = 0
        for line in f:
            line = line.strip()
            if not line:
                continue
            if limit is not None and seen >= limit:
                break
            seen += 1
            yield json.loads(line)


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


def product_row(obj: dict[str, Any], import_source: str) -> list[Any]:
    feature_text = obj.get("features_text") or ""
    metadata = {
        "import_source": import_source,
        "category": obj.get("category"),
        "source_categories": obj.get("source_categories", []),
        "categories_path": obj.get("categories_path"),
        "rating_number": obj.get("rating_number"),
    }
    return [
        obj.get("parent_asin"),
        obj.get("title_clean"),
        obj.get("main_category") or obj.get("category"),
        obj.get("categories_flat") or [],
        obj.get("store"),
        None,
        obj.get("average_rating"),
        obj.get("description_text") or "",
        [feature_text] if feature_text else [],
        metadata,
    ]


def interaction_row(obj: dict[str, Any], import_source: str) -> list[Any]:
    metadata = {
        "import_source": import_source,
        "category": obj.get("category"),
        "verified_purchase": obj.get("verified_purchase"),
        "helpful_vote": obj.get("helpful_vote"),
        "label_strength": obj.get("label_strength"),
        "label_strong": obj.get("label_strong"),
        "user_interaction_count": obj.get("user_interaction_count"),
        "item_interaction_count": obj.get("item_interaction_count"),
        "row_num": obj.get("row_num"),
        "dedup_strategy": obj.get("dedup_strategy"),
    }
    return [
        obj.get("user_id"),
        obj.get("parent_asin"),
        "rating",
        ms_to_mysql_datetime(obj.get("timestamp")),
        obj.get("rating"),
        obj.get("label_binary"),
        obj.get("split") or "",
        import_source,
        metadata,
    ]


def sequence_row(obj: dict[str, Any], import_source: str) -> list[Any]:
    metadata = {
        "import_source": import_source,
        "sequence_len": obj.get("sequence_len"),
        "positive_sequence_len": obj.get("positive_sequence_len"),
        "strong_positive_sequence_len": obj.get("strong_positive_sequence_len"),
        "recent_timestamp_sequence": obj.get("recent_timestamp_sequence", []),
        "recent_positive_timestamp_sequence": obj.get("recent_positive_timestamp_sequence", []),
        "recent_strong_positive_timestamp_sequence": obj.get("recent_strong_positive_timestamp_sequence", []),
    }
    return [
        obj.get("user_id"),
        import_source,
        obj.get("recent_item_sequence") or [],
        obj.get("recent_positive_item_sequence") or [],
        obj.get("recent_strong_positive_item_sequence") or [],
        metadata,
    ]


def _write_rows(command: list[str], table: str, columns: list[str], rows: Iterable[list[Any]], batch_size: int, *, runner: Any | None) -> int:
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
    if table == "products":
        return {"parent_asin"}
    if table == "interactions":
        return set()
    if table == "user_sequences":
        return {"user_id", "window_name"}
    return set()


def _sql_value(column: str, value: Any) -> str:
    if value is None or value == "":
        return "NULL"
    if column in JSON_COLUMNS:
        return "CAST(" + _sql_text(json_dumps(value)) + " AS JSON)"
    if column in NUMERIC_COLUMNS:
        return _sql_number(value)
    return _sql_text(value)


def _sql_text(value: Any) -> str:
    text = str(value or "")
    return "'" + text.replace("\\", "\\\\").replace("'", "''") + "'"


def _sql_number(value: Any) -> str:
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return "NULL"


def _mysql_command(*, compose_file: str, mysql_service: str, db_user: str, db_name: str) -> list[str]:
    mysql_command = (
        'MYSQL_PWD="$MYSQL_PASSWORD" mysql '
        '--batch --raw --skip-column-names --default-character-set=utf8mb4 '
        f'-u {_shell_quote(db_user)} {_shell_quote(db_name)}'
    )
    return ["docker", "compose", "-f", compose_file, "--profile", "mysql", "exec", "-T", mysql_service, "sh", "-lc", mysql_command]


def _run_mysql(command: list[str], sql: str, *, runner: Any | None) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(command, sql)
    proc = subprocess.run(command, input=sql, text=True, encoding="utf-8", capture_output=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise RuntimeError("mysql import command failed")
    return proc


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def main() -> int:
    args = parse_args()
    result = import_recent2y_to_mysql(
        source_dir=Path(args.source_dir),
        items_file=args.items_file,
        limit=args.limit,
        batch_size=max(1, int(args.batch_size)),
        import_source=str(args.import_source),
        truncate=bool(args.truncate),
        skip_products=bool(args.skip_products),
        skip_interactions=bool(args.skip_interactions),
        skip_user_sequences=bool(args.skip_user_sequences),
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
