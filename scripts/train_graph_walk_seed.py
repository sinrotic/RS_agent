from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.graph_walk_training import train_graph_walk_seed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Phase 1.19 DeepWalk graph_walk_seed sidecar")
    parser.add_argument("--config", required=True, help="Hybrid demo config path")
    parser.add_argument("--output-dir", help="Directory for graph_walk_seed artifacts")
    parser.add_argument("--limit-users", type=int, help="Optional user limit for smoke runs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = train_graph_walk_seed(args.config, output_dir=args.output_dir, limit_users=args.limit_users)
    print(f"graph_walk_seed sidecar written to: {result['sidecar_path']}")
    print(f"graph_walk_seed manifest written to: {result['manifest_path']}")
    print(f"graph_walk_seed embeddings written to: {result['embeddings_path']}")


if __name__ == "__main__":
    main()
