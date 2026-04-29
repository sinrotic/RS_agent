from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_DIR = ROOT / "data/processed/amazon_2023_base_smoke_e2e"
DEFAULT_CLEAN_DIR = ROOT / "data/processed/amazon_2023_recall_clean_smoke_e2e"
DEFAULT_VIEWS_DIR = ROOT / "data/processed/amazon_2023_recall_views_smoke_e2e"
DEFAULT_REPORT_PATH = ROOT / "dic/RECALL_DATA_PROFILE_SMOKE_E2E.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the minimal smoke recall pipeline end to end."
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=["Electronics", "Office_Products"],
        help="Amazon categories used for the smoke run.",
    )
    parser.add_argument(
        "--base-output-dir",
        default=str(DEFAULT_BASE_DIR),
        help="Output directory for base normalized data.",
    )
    parser.add_argument(
        "--clean-output-dir",
        default=str(DEFAULT_CLEAN_DIR),
        help="Output directory for recall clean tables.",
    )
    parser.add_argument(
        "--views-output-dir",
        default=str(DEFAULT_VIEWS_DIR),
        help="Output directory for recall view files.",
    )
    parser.add_argument(
        "--report-path",
        default=str(DEFAULT_REPORT_PATH),
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--max-reviews-per-category",
        type=int,
        default=3,
        help="Review cap used during smoke download.",
    )
    parser.add_argument(
        "--positive-rating-threshold",
        type=float,
        default=3.0,
        help="Positive threshold used to make small smoke data produce enough train positives.",
    )
    parser.add_argument(
        "--small-data-all-train-threshold",
        type=int,
        default=3,
        help="If filtered rows are at or below this value, place all rows into train.",
    )
    parser.add_argument(
        "--metadata-scope",
        choices=("observed-items", "all"),
        default="observed-items",
        help="Metadata scope passed to download_and_clean_amazon.py.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse an existing base output directory instead of downloading again.",
    )
    return parser.parse_args()


def run_step(label: str, command: list[str]) -> None:
    print(f"==> {label}")
    subprocess.run(command, check=True, cwd=ROOT)


def main() -> None:
    args = parse_args()
    base_output_dir = Path(args.base_output_dir)
    clean_output_dir = Path(args.clean_output_dir)
    views_output_dir = Path(args.views_output_dir)
    report_path = Path(args.report_path)
    manifest_path = base_output_dir / "manifest.json"
    clean_stats_path = clean_output_dir / "stats.json"
    view_stats_path = views_output_dir / "stats.json"

    if not args.skip_download:
        run_step(
            "download_and_clean_amazon.py",
            [
                sys.executable,
                str(ROOT / "scripts/download_and_clean_amazon.py"),
                "--categories",
                *args.categories,
                "--output-dir",
                str(base_output_dir),
                "--max-reviews-per-category",
                str(args.max_reviews_per_category),
                "--metadata-scope",
                args.metadata_scope,
            ],
        )

    run_step(
        "build_recall_clean_tables.py",
        [
            sys.executable,
            str(ROOT / "scripts/build_recall_clean_tables.py"),
            "--input-manifest",
            str(manifest_path),
            "--output-dir",
            str(clean_output_dir),
            "--positive-rating-threshold",
            str(args.positive_rating_threshold),
            "--small-data-all-train-threshold",
            str(args.small_data_all_train_threshold),
            "--overwrite",
        ],
    )

    run_step(
        "build_recall_views.py",
        [
            sys.executable,
            str(ROOT / "scripts/build_recall_views.py"),
            "--input-dir",
            str(clean_output_dir),
            "--output-dir",
            str(views_output_dir),
        ],
    )

    run_step(
        "profile_recall_tables.py",
        [
            sys.executable,
            str(ROOT / "scripts/profile_recall_tables.py"),
            "--clean-stats",
            str(clean_stats_path),
            "--view-stats",
            str(view_stats_path),
            "--output-path",
            str(report_path),
        ],
    )

    run_step(
        "verify_recall_outputs.py",
        [
            sys.executable,
            str(ROOT / "scripts/verify_recall_outputs.py"),
            "--clean-stats",
            str(clean_stats_path),
            "--view-stats",
            str(view_stats_path),
        ],
    )

    print(f"Smoke clean stats: {clean_stats_path}")
    print(f"Smoke view stats: {view_stats_path}")
    print(f"Smoke report: {report_path}")


if __name__ == "__main__":
    main()
