from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.training.multi_turn_sft_generator import DEFAULT_CONFIG, run_multi_turn_sft_generation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate multi-turn RS Agent SFT data from simulated user/recommendation agent interactions.")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--limit", type=int, default=None, help="Override generation.target_samples for smoke/full runs.")
    parser.add_argument("--dry-run", action="store_true", help="Run locally without API calls or output writes.")
    parser.add_argument("--execute", action="store_true", help="Call the configured OpenAI-compatible model and write outputs.")
    args = parser.parse_args()
    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute cannot be used together")
    return args


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = run_multi_turn_sft_generation(args.config, execute=args.execute, limit=args.limit, dry_run_override=True if args.dry_run else None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
