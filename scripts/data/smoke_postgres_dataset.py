from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rs_core.data import build_postgres_dataset_store_from_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke read-only access to the local/trial PostgreSQL dataset wrapper.")
    parser.add_argument("--summary", action="store_true", help="Print connection and table presence summary.")
    parser.add_argument("--health", action="store_true", help="Print public-safe health status.")
    parser.add_argument("--product", default=None, help="Fetch one product by parent_asin.")
    parser.add_argument("--user", default=None, help="Fetch user sequence and recent interactions for user_id.")
    parser.add_argument("--window-name", default="recent_2y", help="Window name for --user sequence lookup.")
    parser.add_argument("--limit", type=int, default=50, help="Recent interaction limit; wrapper clamps to max 200.")
    parser.add_argument("--require-ok", action="store_true", help="Exit non-zero unless health.status is ok.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store = build_postgres_dataset_store_from_env()
    output: dict[str, Any] = {}
    if args.health or not any([args.summary, args.product, args.user]):
        output["health"] = store.health()
    if args.summary:
        output["summary"] = store.summary()
    if args.product:
        output["product"] = store.get_product(args.product)
    if args.user:
        output["user_sequence"] = store.get_user_sequence(args.user, args.window_name)
        output["recent_interactions"] = store.get_user_recent_interactions(args.user, args.limit)
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    if args.require_ok and output.get("health", {}).get("status") != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
