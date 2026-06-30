from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.workflow.hybrid_demo import run_hybrid_demo
DEFAULT_CONFIG = ROOT / "configs/demo/hybrid_demo/hybrid_demo_small.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 1.5 small-sample hybrid recommendation demo.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to hybrid demo config.")
    parser.add_argument("--limit-users", type=int, default=None, help="Optional max users for a quick run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_hybrid_demo(args.config, limit_users=args.limit_users)
    print(f"Recommendations written to: {result['recommendations_path']}")
    print(f"Metrics written to: {result['metrics_path']}")
    print(f"Report written to: {result['report_path']}")


if __name__ == "__main__":
    main()
