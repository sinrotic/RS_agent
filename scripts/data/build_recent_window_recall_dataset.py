from __future__ import annotations

import argparse

from rs_core.dataproc.recent_window_materializer import (
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SEQUENCE_MAX_LEN,
    DEFAULT_SHARD_COUNT,
    DEFAULT_SOURCE_MANIFEST,
    materialize_recent_window_dataset,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Derive the fixed recent-window recall dataset from an existing recall-clean manifest."
    )
    parser.add_argument(
        "--source-manifest",
        default=DEFAULT_SOURCE_MANIFEST,
        help="Manifest for the existing recall-clean full dataset.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for derived recent-window outputs.",
    )
    parser.add_argument(
        "--sequence-max-len",
        type=int,
        default=DEFAULT_SEQUENCE_MAX_LEN,
        help="Maximum recent items preserved in user sequence outputs.",
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=DEFAULT_SHARD_COUNT,
        help="Number of temporary sequence shards used while materializing user sequences.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = materialize_recent_window_dataset(
        source_manifest_path=args.source_manifest,
        output_dir=args.output_dir,
        sequence_max_len=args.sequence_max_len,
        shard_count=args.shard_count,
    )
    manifest = outputs["manifest"]
    print(f"Manifest written to: {outputs['manifest_path']}")
    print(f"Stats written to: {outputs['stats_path']}")
    print(f"Canonical interactions written to: {manifest['canonical_interactions_path']}")
    print(f"Train-only canonical items written to: {manifest['canonical_items_path']}")
    print(f"All-window canonical items written to: {manifest['all_canonical_items_path']}")
    print(f"User sequences written to: {manifest['user_sequences_path']}")
    print(f"Train user sequences written to: {manifest['train_user_sequences_path']}")


if __name__ == "__main__":
    main()
