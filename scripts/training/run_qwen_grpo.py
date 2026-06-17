from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.training.grpo_runner import run_grpo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Qwen GRPO scaffold checks; dry-run by default.")
    parser.add_argument("--config", default="configs/training/qwen_grpo_smoke.yaml")
    parser.add_argument("--init-only", action="store_true", help="Explicitly initialize model/tokenizer and stop.")
    parser.add_argument("--max-steps", type=int, default=0, help="Enter heavy path only when > 0.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_grpo(args.config, dry_run=not args.init_only and args.max_steps <= 0, init_only=args.init_only, max_steps=args.max_steps)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
