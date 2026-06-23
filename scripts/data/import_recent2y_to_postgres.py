from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, TextIO

DEFAULT_SOURCE_DIR = "data/processed/amazon_2023_recall_recent_2y_1m_3m"
DEFAULT_COMPOSE_FILE = "deploy/local/docker-compose.yml"
DEFAULT_POSTGRES_SERVICE = "postgres"
DEFAULT_DB_USER = "rs_agent"
DEFAULT_DB_NAME = "rs_agent"
DEFAULT_IMPORT_SOURCE = "recent_2y"

PRODUCT_COLUMNS = [
    "parent_asin",
    "title",
    "main_category",
    "categories",
    "brand",
    "price",
    "rating",
    "description",
    "features",
    "metadata",
]
INTERACTION_COLUMNS = [
    "user_id",
    "parent_asin",
    "event_type",
    "event_time",
    "rating",
    "label_binary",
    "split",
    "source",
    "metadata",
]
SEQUENCE_COLUMNS = [
    "user_id",
    "window_name",
    "recent_item_sequence",
    "recent_positive_item_sequence",
    "recent_strong_positive_item_sequence",
    "metadata",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream the recent 2y dataset into the local/trial PostgreSQL database."
    )
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--postgres-service", default=DEFAULT_POSTGRES_SERVICE)
    parser.add_argument("--db-user", default=DEFAULT_DB_USER)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    parser.add_argument("--import-source", default=DEFAULT_IMPORT_SOURCE)
    parser.add_argument(
        "--items-file",
        default=None,
        help="Item JSONL filename under source-dir. Defaults to canonical_items.all.jsonl when present, otherwise canonical_items.jsonl.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit rows per input file for smoke imports.")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate products/interactions/user_sequences before import. Use before full imports.",
    )
    parser.add_argument("--skip-products", action="store_true")
    parser.add_argument("--skip-interactions", action="store_true")
    parser.add_argument("--skip-user-sequences", action="store_true")
    parser.add_argument(
        "--no-single-transaction",
        action="store_true",
        help="Let each COPY autocommit. Prefer this for full local imports to reduce long-transaction/WAL pressure.",
    )
    return parser.parse_args()


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


def ms_to_iso(value: Any) -> str:
    if value is None:
        return ""
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return ""
    if ts > 10_000_000_000:
        ts /= 1000.0
    return datetime.fromtimestamp(ts, UTC).isoformat()


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
        json_dumps(obj.get("categories_flat") or []),
        obj.get("store"),
        "",
        obj.get("average_rating") or "",
        obj.get("description_text") or "",
        json_dumps([feature_text] if feature_text else []),
        json_dumps(metadata),
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
        ms_to_iso(obj.get("timestamp")),
        obj.get("rating") or "",
        obj.get("label_binary") if obj.get("label_binary") is not None else "",
        obj.get("split") or "",
        import_source,
        json_dumps(metadata),
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
        json_dumps(obj.get("recent_item_sequence") or []),
        json_dumps(obj.get("recent_positive_item_sequence") or []),
        json_dumps(obj.get("recent_strong_positive_item_sequence") or []),
        json_dumps(metadata),
    ]


def write_copy(
    stdin: TextIO,
    table: str,
    columns: list[str],
    rows: Iterable[list[Any]],
    progress_label: str,
    progress_every: int,
) -> int:
    stdin.write(f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT csv);\n")
    writer = csv.writer(stdin, lineterminator="\n")
    count = 0
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
        count += 1
        if count % progress_every == 0:
            print(f"{progress_label}: {count} rows streamed", file=sys.stderr, flush=True)
    stdin.write("\\.\n")
    stdin.flush()
    print(f"{progress_label}: {count} rows streamed", file=sys.stderr, flush=True)
    return count


def build_psql_command(args: argparse.Namespace) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        args.compose_file,
        "--profile",
        "postgres",
        "exec",
        "-T",
        args.postgres_service,
        "psql",
        "-U",
        args.db_user,
        "-d",
        args.db_name,
        "-v",
        "ON_ERROR_STOP=1",
    ]


def main() -> int:
    args = parse_args()
    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        raise SystemExit(f"source dir not found: {source_dir}")

    items_file = args.items_file
    if items_file is None:
        items_file = "canonical_items.all.jsonl" if (source_dir / "canonical_items.all.jsonl").exists() else "canonical_items.jsonl"
    items_path = source_dir / items_file
    if not args.skip_products and not items_path.exists():
        raise SystemExit(f"items file not found: {items_path}")

    command = build_psql_command(args)
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None

    counts: dict[str, int] = {}
    try:
        if not args.no_single_transaction:
            proc.stdin.write("BEGIN;\n")
        if args.truncate:
            proc.stdin.write("TRUNCATE products, interactions, user_sequences RESTART IDENTITY;\n")

        if not args.skip_products:
            rows = (product_row(obj, args.import_source) for obj in iter_jsonl(items_path, args.limit))
            counts["products"] = write_copy(proc.stdin, "products", PRODUCT_COLUMNS, rows, "products", 100_000)

        if not args.skip_interactions:
            rows = (
                interaction_row(obj, args.import_source)
                for obj in iter_jsonl(source_dir / "canonical_interactions.jsonl", args.limit)
            )
            counts["interactions"] = write_copy(
                proc.stdin, "interactions", INTERACTION_COLUMNS, rows, "interactions", 250_000
            )

        if not args.skip_user_sequences:
            rows = (sequence_row(obj, args.import_source) for obj in iter_jsonl(source_dir / "user_sequences.jsonl", args.limit))
            counts["user_sequences"] = write_copy(
                proc.stdin, "user_sequences", SEQUENCE_COLUMNS, rows, "user_sequences", 100_000
            )

        if not args.no_single_transaction:
            proc.stdin.write("COMMIT;\n")
        proc.stdin.write(
            "SELECT 'products', count(*) FROM products "
            "UNION ALL SELECT 'interactions', count(*) FROM interactions "
            "UNION ALL SELECT 'user_sequences', count(*) FROM user_sequences "
            "ORDER BY 1;\n"
        )
        proc.stdin.close()
        output = proc.stdout.read()
        return_code = proc.wait()
    except Exception:
        proc.kill()
        raise

    print(output)
    print(json_dumps({"imported": counts}))
    if return_code != 0:
        raise SystemExit(return_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
