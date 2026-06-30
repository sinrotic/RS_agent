from __future__ import annotations

import argparse
import json
from pathlib import Path

from rs_core.serving.infrastructure.stores.candidate_store_mysql import (
    DEFAULT_COMPOSE_FILE,
    DEFAULT_DB_NAME,
    DEFAULT_DB_USER,
    DEFAULT_MYSQL_SERVICE,
    _insert_sql as _insert_sql,
    import_candidate_store_to_mysql,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safety-first MySQL candidate store importer; dry-run is the default.")
    parser.add_argument("--input", type=Path, action="append", default=[], help="JSONL artifact path to scan/import. May be repeated.")
    parser.add_argument("--limit-rows", type=int, default=1000, help="Maximum rows to scan/import per input file. 0 means no limit.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per INSERT statement in write mode.")
    parser.add_argument("--artifact-id", default="", help="Artifact id stamped onto imported rows.")
    parser.add_argument("--source", default="", help="Override source stamped onto imported rows.")
    parser.add_argument("--compose-file", default=DEFAULT_COMPOSE_FILE, help="Docker compose file for local MySQL.")
    parser.add_argument("--mysql-service", default=DEFAULT_MYSQL_SERVICE, help="Docker compose service name for MySQL.")
    parser.add_argument("--db-user", default=DEFAULT_DB_USER, help="MySQL user name; password is read from container env.")
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME, help="MySQL database name.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Scan only; do not write to MySQL. This is the default.")
    mode.add_argument("--write", action="store_true", help="Write supported rows through docker compose mysql stdin.")
    args = parser.parse_args()

    result = import_candidate_store_to_mysql(
        inputs=args.input,
        limit_rows=max(0, int(args.limit_rows)),
        batch_size=max(1, int(args.batch_size)),
        artifact_id=str(args.artifact_id or ""),
        source=str(args.source or ""),
        write=bool(args.write),
        compose_file=str(args.compose_file),
        mysql_service=str(args.mysql_service),
        db_user=str(args.db_user),
        db_name=str(args.db_name),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
