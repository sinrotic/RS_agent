from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    parser.add_argument("--compact-inputs", action="store_true", help="Keep only training-required fields while loading full train inputs")
    parser.add_argument("--epochs", type=int, help="Override the configured training epoch count")
    parser.add_argument("--gradient-accumulation-steps", type=int, help="Accumulate this many physical batches before each optimizer step")
    parser.add_argument("--mixed-precision", action="store_true", help="Use CUDA AMP mixed precision when a CUDA device is available")
    parser.add_argument("--progress-log", help="Optional JSONL progress log path")
    return parser.parse_args()


def _progress_logger(path: str | None):
    if not path:
        return None
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    def log(event: str, payload: dict[str, Any]) -> None:
        row = {"ts": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"), "event": event, **payload}
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()

    return log


def main() -> None:
    args = parse_args()
    if args.variant == "all":
        raise SystemExit("safe train-only two_tower training requires --variant youtube_dnn; --variant all is blocked")
    if args.variant != "youtube_dnn":
        raise SystemExit("safe train-only two_tower training allows only --variant youtube_dnn")

    training_overrides = {}
    if args.epochs is not None:
        training_overrides["epochs"] = args.epochs
    if args.gradient_accumulation_steps is not None:
        training_overrides["gradient_accumulation_steps"] = args.gradient_accumulation_steps
    if args.mixed_precision:
        training_overrides["mixed_precision"] = True
    config_overrides = {"two_tower_training": training_overrides} if training_overrides else None

    result = train_two_tower_recall(
        args.config,
        output_dir=args.output_dir,
        limit_users=args.limit_users,
        variant=args.variant,
        config_overrides=config_overrides,
        item_vocab_manifest=args.item_vocab_manifest,
        user_quality_manifest=args.user_quality_manifest,
        user_quality_bucket=args.user_quality_bucket,
        compact_inputs=args.compact_inputs,
        progress_callback=_progress_logger(args.progress_log),
    )
    print(f"{args.variant} artifact manifest written to: {result['artifact_manifest_path']}")
    print(f"{args.variant} recall index written to: {result['recall_index_path']}")


if __name__ == "__main__":
    main()
