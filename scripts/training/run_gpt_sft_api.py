from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.offline.training.gpt_sft_runner import run_gpt_sft


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GPT SFT data generation; dry-run by default.")
    parser.add_argument("--config", default="configs/training/gpt_sft_api_smoke.yaml")
    parser.add_argument("--input", default=None, help="Training signals JSON/JSONL input. Defaults to synthetic smoke SFT sample.")
    parser.add_argument("--output", default=None, help="Output JSONL path for generated SFT samples.")
    parser.add_argument("--limit", type=int, default=None, help="Override data.max_samples for this run.")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and show message summary without calling the API.")
    parser.add_argument("--execute", action="store_true", help="Call the OpenAI-compatible API and write output JSONL.")
    args = parser.parse_args()
    if args.dry_run and args.execute:
        parser.error("--dry-run and --execute cannot be used together")
    return args


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    result = run_gpt_sft(
        args.config,
        execute=args.execute,
        limit=args.limit,
        input_path=args.input,
        output_path=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
