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
    parser.add_argument("--training-sample-path", help="Optional train-only two_tower_train_samples.jsonl path for explicit negatives")
    parser.add_argument("--user-quality-manifest", help="Optional train-only user quality policy manifest for selecting training users")
    parser.add_argument("--user-quality-bucket", help="Optional quality_bucket filter within --user-quality-manifest")
    parser.add_argument("--compact-inputs", action="store_true", help="Keep only training-required fields while loading full train inputs")
    parser.add_argument("--epochs", type=int, help="Override the configured training epoch count")
    parser.add_argument("--min-user-positives", type=int, help="Override minimum positive events required per training user")
    parser.add_argument("--max-samples-per-user", type=int, help="Override maximum train examples emitted per user")
    parser.add_argument("--batch-size", type=int, help="Override training batch size")
    parser.add_argument("--user-history-window", type=int, help="Override maximum positive history items used by the user tower")
    parser.add_argument("--embedding-dim", type=int, help="Override item/user embedding dimension")
    parser.add_argument("--hidden-dim", type=int, help="Override hidden layer dimension")
    parser.add_argument("--learning-rate", type=float, help="Override optimizer learning rate")
    parser.add_argument("--negative-samples", type=int, help="Override per-example negative sample count")
    parser.add_argument("--negative-sampling-power", type=float, help="Override popularity-power negative sampling exponent")
    parser.add_argument("--negative-sampling-version", help="Override negative sampling version label, e.g. v1 or v2")
    parser.add_argument("--unique-negatives-per-example", action="store_true", help="Deduplicate negatives within each training example")
    parser.add_argument("--use-explicit-negative-item-ids", action="store_true", help="Use optional train-only negative_item_ids from sequence rows")
    parser.add_argument("--explicit-negative-weight", type=float, help="Fraction of requested negatives to draw from explicit negative_item_ids")
    parser.add_argument("--negative-dedup-max-attempts", type=int, help="Maximum sampling attempts before fallback when deduplicating negatives")
    parser.add_argument("--sampled-softmax-candidate-mode", choices=["per_example", "batch_shared"], help="Override sampled softmax candidate construction mode")
    parser.add_argument("--sampled-softmax-correction", choices=["none", "logq"], help="Override sampled softmax correction for popularity-sampled candidates")
    parser.add_argument("--sampled-softmax-logq-epsilon", type=float, help="Minimum probability used by logQ sampled softmax correction")
    parser.add_argument("--torch-user-history-weighting", choices=["uniform", "recency_decay"], help="Override PyTorch user tower history weighting")
    parser.add_argument("--recency-decay", type=float, help="Override recency decay for sequence weighting")
    parser.add_argument("--example-age-weighting", choices=["none", "decay"], help="Override train-only example age loss weighting")
    parser.add_argument("--example-age-half-life-days", type=float, help="Half-life in days for example age decay weighting")
    parser.add_argument("--example-age-min-weight", type=float, help="Minimum per-example weight for example age decay weighting")
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
    if args.min_user_positives is not None:
        training_overrides["min_user_positives"] = args.min_user_positives
    if args.max_samples_per_user is not None:
        training_overrides["max_samples_per_user"] = args.max_samples_per_user
    if args.batch_size is not None:
        training_overrides["batch_size"] = args.batch_size
    if args.user_history_window is not None:
        training_overrides["user_history_window"] = args.user_history_window
    if args.embedding_dim is not None:
        training_overrides["embedding_dim"] = args.embedding_dim
    if args.hidden_dim is not None:
        training_overrides["hidden_dim"] = args.hidden_dim
    if args.learning_rate is not None:
        training_overrides["learning_rate"] = args.learning_rate
    if args.training_sample_path is not None:
        training_overrides["training_sample_path"] = args.training_sample_path
    if args.negative_samples is not None:
        training_overrides["negative_samples"] = args.negative_samples
    if args.negative_sampling_power is not None:
        training_overrides["negative_sampling_power"] = args.negative_sampling_power
    if args.negative_sampling_version is not None:
        training_overrides["negative_sampling_version"] = args.negative_sampling_version
    if args.unique_negatives_per_example:
        training_overrides["unique_negatives_per_example"] = True
    if args.use_explicit_negative_item_ids:
        training_overrides["use_explicit_negative_item_ids"] = True
    if args.explicit_negative_weight is not None:
        training_overrides["explicit_negative_weight"] = args.explicit_negative_weight
    if args.negative_dedup_max_attempts is not None:
        training_overrides["negative_dedup_max_attempts"] = args.negative_dedup_max_attempts
    if args.sampled_softmax_candidate_mode is not None:
        training_overrides["sampled_softmax_candidate_mode"] = args.sampled_softmax_candidate_mode
    if args.sampled_softmax_correction is not None:
        training_overrides["sampled_softmax_correction"] = args.sampled_softmax_correction
    if args.sampled_softmax_logq_epsilon is not None:
        training_overrides["sampled_softmax_logq_epsilon"] = args.sampled_softmax_logq_epsilon
    if args.torch_user_history_weighting is not None:
        training_overrides["torch_user_history_weighting"] = args.torch_user_history_weighting
    if args.recency_decay is not None:
        training_overrides["recency_decay"] = args.recency_decay
    if args.example_age_weighting is not None:
        training_overrides["example_age_weighting"] = args.example_age_weighting
    if args.example_age_half_life_days is not None:
        training_overrides["example_age_half_life_days"] = args.example_age_half_life_days
    if args.example_age_min_weight is not None:
        training_overrides["example_age_min_weight"] = args.example_age_min_weight
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
