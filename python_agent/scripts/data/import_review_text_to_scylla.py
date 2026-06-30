from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.data.review_text_store import (  # noqa: E402
    DEFAULT_KEYSPACE,
    DEFAULT_SCHEMA_PATH,
    ScyllaConnectionArgs,
    import_review_text_to_scylla,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Amazon review title/text into Scylla review text store; dry-run is the default.")
    parser.add_argument("--input", type=Path, action="append", default=[], help="Review JSONL path. May be repeated.")
    parser.add_argument("--limit-rows", type=int, default=1000, help="Maximum rows to scan/import per input file. 0 means no limit.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--progress-every", type=int, default=100000)
    parser.add_argument("--retry-attempts", type=int, default=5)
    parser.add_argument("--retry-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--min-timestamp-ms", type=int, default=None)
    parser.add_argument("--max-timestamp-ms", type=int, default=None)
    parser.add_argument(
        "--source-line-filter",
        action="append",
        default=[],
        help="Exact JSONL source-line filter in INPUT_PATH=FILTER_PATH form. May be repeated.",
    )
    parser.add_argument("--hosts", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9042)
    parser.add_argument("--keyspace", default=DEFAULT_KEYSPACE)
    parser.add_argument("--datacenter", default="datacenter1")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--apply-schema", action="store_true")
    args = parser.parse_args()

    result = import_review_text_to_scylla(
        inputs=args.input,
        limit_rows=max(0, int(args.limit_rows)),
        batch_size=max(1, int(args.batch_size)),
        progress_every=max(0, int(args.progress_every)),
        write=bool(args.write),
        apply_schema=bool(args.apply_schema),
        schema_path=args.schema,
        retry_attempts=max(1, int(args.retry_attempts)),
        retry_sleep_seconds=max(0.0, float(args.retry_sleep_seconds)),
        min_timestamp_ms=args.min_timestamp_ms,
        max_timestamp_ms=args.max_timestamp_ms,
        source_line_filters=parse_source_line_filters(args.source_line_filter),
        connection_args=ScyllaConnectionArgs(
            hosts=tuple(host.strip() for host in str(args.hosts).split(",") if host.strip()) or ("127.0.0.1",),
            port=int(args.port),
            keyspace=str(args.keyspace or DEFAULT_KEYSPACE),
            datacenter=str(args.datacenter or "datacenter1"),
            username=str(args.username or ""),
            password=str(args.password or ""),
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def parse_source_line_filters(values: list[str]) -> dict[Path, Path]:
    filters: dict[Path, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--source-line-filter must be INPUT_PATH=FILTER_PATH, got: {value}")
        input_path, filter_path = value.split("=", 1)
        filters[Path(input_path)] = Path(filter_path)
    return filters


if __name__ == "__main__":
    raise SystemExit(main())
