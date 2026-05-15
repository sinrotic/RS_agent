from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.ltr_training import train_ltr_ranker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train a lightweight pure-Python LTR ranker")
    parser.add_argument("--config", required=True, help="Hybrid demo config path")
    parser.add_argument("--output-dir", help="Directory for LTR model and metrics")
    parser.add_argument("--limit-users", type=int, help="Optional user limit for smoke runs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = train_ltr_ranker(args.config, output_dir=args.output_dir, limit_users=args.limit_users)
    print(f"LTR model written to: {result['model_path']}")
    print(f"LTR metrics written to: {result['metrics_path']}")
    if result.get("candidate_rows_path"):
        print(f"LTR candidate rows written to: {result['candidate_rows_path']}")


if __name__ == "__main__":
    main()
