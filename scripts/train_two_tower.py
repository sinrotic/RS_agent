from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.two_tower_training import train_two_tower_recall, train_two_tower_variants


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train DSSM-style and YouTubeDNN-style two-tower recall artifacts")
    parser.add_argument("--config", required=True, help="Hybrid demo config path")
    parser.add_argument("--output-dir", help="Directory for two-tower artifacts")
    parser.add_argument("--limit-users", type=int, help="Optional user limit for smoke runs")
    parser.add_argument("--variant", choices=["dssm", "youtube_dnn", "all"], default="all")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.variant == "all":
        result = train_two_tower_variants(args.config, output_dir=args.output_dir, limit_users=args.limit_users)
        for variant, run in result["runs"].items():
            print(f"{variant} artifact manifest written to: {run['artifact_manifest_path']}")
            print(f"{variant} recall index written to: {run['recall_index_path']}")
        return

    result = train_two_tower_recall(args.config, output_dir=args.output_dir, limit_users=args.limit_users, variant=args.variant)
    print(f"{args.variant} artifact manifest written to: {result['artifact_manifest_path']}")
    print(f"{args.variant} recall index written to: {result['recall_index_path']}")


if __name__ == "__main__":
    main()
