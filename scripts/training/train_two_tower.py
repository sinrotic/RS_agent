from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.two_tower_training import train_two_tower_recall


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train DSSM-style and YouTubeDNN-style two-tower recall artifacts")
    parser.add_argument("--config", required=True, help="Hybrid demo config path")
    parser.add_argument("--output-dir", help="Directory for two-tower artifacts")
    parser.add_argument("--limit-users", type=int, help="Optional user limit for smoke runs")
    parser.add_argument("--variant", choices=["dssm", "youtube_dnn", "all"], default="all")
    parser.add_argument("--item-vocab-manifest", help="Train-only two_tower_item_vocab_manifest.json path")
    parser.add_argument("--user-quality-manifest", help="Optional train-only user quality policy manifest for selecting training users")
    parser.add_argument("--user-quality-bucket", help="Optional quality_bucket filter within --user-quality-manifest")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.variant == "all":
        raise SystemExit("safe train-only two_tower training requires --variant youtube_dnn; --variant all is blocked")
    if args.variant != "youtube_dnn":
        raise SystemExit("safe train-only two_tower training allows only --variant youtube_dnn")

    result = train_two_tower_recall(
        args.config,
        output_dir=args.output_dir,
        limit_users=args.limit_users,
        variant=args.variant,
        item_vocab_manifest=args.item_vocab_manifest,
        user_quality_manifest=args.user_quality_manifest,
        user_quality_bucket=args.user_quality_bucket,
    )
    print(f"{args.variant} artifact manifest written to: {result['artifact_manifest_path']}")
    print(f"{args.variant} recall index written to: {result['recall_index_path']}")


if __name__ == "__main__":
    main()
