from __future__ import annotations

import argparse
import json
from pathlib import Path

from rs_core.serving.infrastructure.stores.candidate_store_cassandra import (
    DEFAULT_SCHEMA_PATH,
    CassandraConnectionArgs,
    import_candidate_store_to_cassandra,
)


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


if __name__ == "__main__":
    main()
