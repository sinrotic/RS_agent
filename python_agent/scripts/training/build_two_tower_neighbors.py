from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.two_tower_training import build_two_tower_seed_sidecar, build_two_tower_seed_sidecar_from_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build deterministic two_tower_seed item-neighbor sidecar from item embeddings")
    parser.add_argument("--config", help="Config containing two_tower_seed_sidecar paths")
    parser.add_argument("--embedding-input-path", help="Input item_embeddings.jsonl path")
    parser.add_argument("--sidecar-path", help="Output two_tower_seed sidecar JSONL path")
    parser.add_argument("--manifest-path", help="Output two_tower_seed manifest JSON path")
    parser.add_argument("--neighbor-k", type=int, default=50, help="Neighbors per item")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.config and not any([args.embedding_input_path, args.sidecar_path, args.manifest_path]):
        manifest = build_two_tower_seed_sidecar_from_config(args.config)
    else:
        if not args.embedding_input_path or not args.sidecar_path or not args.manifest_path:
            raise SystemExit("Provide --config or all of --embedding-input-path, --sidecar-path, and --manifest-path")
        manifest = build_two_tower_seed_sidecar(
            embedding_input_path=args.embedding_input_path,
            sidecar_path=args.sidecar_path,
            manifest_path=args.manifest_path,
            neighbor_k=args.neighbor_k,
            config_path=args.config,
        )
    print(f"two_tower_seed sidecar written to: {manifest['sidecar_path']}")
    print(f"two_tower_seed manifest written to: {args.manifest_path or 'configured manifest path'}")


if __name__ == "__main__":
    main()
