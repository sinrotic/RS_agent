from __future__ import annotations

import argparse
from pathlib import Path

from rs_core.data.pipelines.recall_views import (
    DEFAULT_CATEGORY_TOP_K,
    DEFAULT_INPUT_DIR,
    DEFAULT_ITEM_GRAPH_MIN_SCORE,
    DEFAULT_ITEM_GRAPH_STRONG_MULTIPLIER,
    DEFAULT_ITEM_GRAPH_TOP_K,
    DEFAULT_ITEM_GRAPH_WINDOW,
    DEFAULT_LIGHTWEIGHT_MAX_OUTPUT_BYTES,
    DEFAULT_LIGHTWEIGHT_MIN_FREE_BYTES,
    DEFAULT_MAX_ITEMS_PER_USER_FOR_ITEMCF,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_RECENT_WINDOW_RATIO,
    DEFAULT_SEMANTIC_INVERTED_TOP_K,
    build_recall_views,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build minimal recall views from canonical recall-clean tables."
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help="Directory containing canonical recall-clean outputs.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Directory used to store recall views.",
    )
    parser.add_argument(
        "--recent-window-ratio",
        type=float,
        default=DEFAULT_RECENT_WINDOW_RATIO,
        help="Fraction of the train time span treated as recent for popularity views.",
    )
    parser.add_argument(
        "--max-items-per-user-for-itemcf",
        type=int,
        default=DEFAULT_MAX_ITEMS_PER_USER_FOR_ITEMCF,
        help="Maximum recent unique items per user used for ItemCF edges.",
    )
    parser.add_argument(
        "--category-top-k",
        type=int,
        default=DEFAULT_CATEGORY_TOP_K,
        help="Top-K items retained per category bucket in category recall outputs.",
    )
    parser.add_argument(
        "--item-graph-window",
        type=int,
        default=DEFAULT_ITEM_GRAPH_WINDOW,
        help="Maximum forward sequence distance used for directed item graph edges.",
    )
    parser.add_argument(
        "--item-graph-top-k",
        type=int,
        default=DEFAULT_ITEM_GRAPH_TOP_K,
        help="Maximum outgoing item graph neighbors retained per source item.",
    )
    parser.add_argument(
        "--item-graph-min-score",
        type=float,
        default=DEFAULT_ITEM_GRAPH_MIN_SCORE,
        help="Minimum item graph edge score retained in the output.",
    )
    parser.add_argument(
        "--item-graph-strong-multiplier",
        type=float,
        default=DEFAULT_ITEM_GRAPH_STRONG_MULTIPLIER,
        help="Score multiplier applied when destination item is in the strong-positive sequence.",
    )
    parser.add_argument(
        "--lightweight-full-safe",
        action="store_true",
        help="Build only full-safe lightweight recall views and skip ItemCF/item_graph outputs.",
    )
    parser.add_argument(
        "--lightweight-max-output-bytes",
        type=int,
        default=DEFAULT_LIGHTWEIGHT_MAX_OUTPUT_BYTES,
        help="Hard cap for total lightweight output bytes before promotion.",
    )
    parser.add_argument(
        "--lightweight-min-free-bytes",
        type=int,
        default=DEFAULT_LIGHTWEIGHT_MIN_FREE_BYTES,
        help="Minimum free bytes required on the output filesystem before building lightweight views.",
    )
    parser.add_argument(
        "--semantic-inverted-top-k",
        type=int,
        default=DEFAULT_SEMANTIC_INVERTED_TOP_K,
        help="Maximum item postings retained per semantic inverted-index token in lightweight mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    manifest_payload, stats_payload = build_recall_views(
        input_dir=Path(args.input_dir),
        output_dir=output_dir,
        recent_window_ratio=args.recent_window_ratio,
        max_items_per_user_for_itemcf=args.max_items_per_user_for_itemcf,
        category_top_k=args.category_top_k,
        item_graph_window=args.item_graph_window,
        item_graph_top_k=args.item_graph_top_k,
        item_graph_min_score=args.item_graph_min_score,
        item_graph_strong_multiplier=args.item_graph_strong_multiplier,
        lightweight_full_safe=args.lightweight_full_safe,
        lightweight_max_output_bytes=args.lightweight_max_output_bytes,
        lightweight_min_free_bytes=args.lightweight_min_free_bytes,
        semantic_inverted_top_k=args.semantic_inverted_top_k,
    )

    if args.lightweight_full_safe:
        print(f"Lightweight full-safe recall views written to: {output_dir}")
        print(f"Manifest written to: {manifest_payload['manifest_path']}")
        print(f"Stats written to: {stats_payload['stats_path']}")
        return

    print(f"Popularity recall written to: {stats_payload['popular_recall']['output_path']}")
    print(f"Weak ItemCF recall written to: {stats_payload['itemcf_recall']['weak']['output_path']}")
    print(f"Strong ItemCF recall written to: {stats_payload['itemcf_recall']['strong']['output_path']}")
    print(f"Item graph recall written to: {stats_payload['item_graph_recall']['output_path']}")
    print(f"Category recall written to: {stats_payload['category_recall']['category_items_path']}")
    print(f"Semantic recall inputs written to: {stats_payload['category_recall']['semantic_path']}")
    print(f"Manifest written to: {manifest_payload['manifest_path']}")
    print(f"Stats written to: {stats_payload['stats_path']}")


if __name__ == "__main__":
    main()
