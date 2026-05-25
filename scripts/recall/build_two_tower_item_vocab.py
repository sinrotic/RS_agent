from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.two_tower_training import build_two_tower_item_vocab


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build train-only two-tower item vocab artifacts")
    parser.add_argument("--canonical-interactions-train", required=True, help="Path to canonical_interactions.train.jsonl")
    parser.add_argument("--canonical-items", help="Optional canonical_items metadata jsonl; cannot add item ids")
    parser.add_argument("--output-vocab", required=True, help="Output two_tower_item_vocab.jsonl path")
    parser.add_argument("--output-manifest", required=True, help="Output two_tower_item_vocab_manifest.json path")
    parser.add_argument("--min-freq", type=int, default=1, help="Minimum train interaction frequency required to keep an item")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_two_tower_item_vocab(
        canonical_interactions_train=args.canonical_interactions_train,
        canonical_items=args.canonical_items,
        output_vocab=args.output_vocab,
        output_manifest=args.output_manifest,
        min_frequency=args.min_freq,
    )
    print(f"two_tower item vocab written to: {manifest['item_vocab_path']}")
    print(f"two_tower item vocab manifest written to: {args.output_manifest}")


if __name__ == "__main__":
    main()
