from __future__ import annotations

import argparse
from pathlib import Path

from rs_core.dataproc.validation import read_json, run_recall_output_checks

DEFAULT_CLEAN_STATS = "./data/processed/amazon_2023_recall_clean/stats.json"
DEFAULT_VIEW_STATS = "./data/processed/amazon_2023_recall_views/stats.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify smoke recall outputs and fail fast when the minimal recall chain is not ready."
    )
    parser.add_argument(
        "--clean-stats",
        default=DEFAULT_CLEAN_STATS,
        help="stats.json emitted by build_recall_clean_tables.py",
    )
    parser.add_argument(
        "--view-stats",
        default=DEFAULT_VIEW_STATS,
        help="stats.json emitted by build_recall_views.py",
    )
    parser.add_argument(
        "--require-strong-itemcf",
        action="store_true",
        help="Treat strong ItemCF as a required check instead of an observation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    clean_stats = read_json(Path(args.clean_stats))
    view_stats = read_json(Path(args.view_stats))
    ok, lines = run_recall_output_checks(clean_stats, view_stats, args.require_strong_itemcf)
    for line in lines:
        print(line)
    print("SMOKE VERIFY: PASS" if ok else "SMOKE VERIFY: FAIL")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
