from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_lab.experiments.recall.pool500.methods.itemcf_strong.augcf_lite_builder import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    AugCFLiteConfig,
    build_itemcf_strong_augcf_lite_method_dataset,
)

DEFAULT_OUTPUT_DIR = Path(
    "outputs/recall/pool500_method_datasets/recent_2y/itemcf_strong_augcf_lite/v1/smoke"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build train-only AugCF-lite method dataset rows for pool500 itemcf_strong."
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default="augcf_lite_v1_smoke")
    parser.add_argument("--limit-users", type=int, default=5000, help="0 means no user cap")
    parser.add_argument("--max-src-items", type=int, default=20000, help="0 means no source item cap")
    parser.add_argument("--top-k-per-src", type=int, default=100)
    parser.add_argument("--pseudo-per-src", type=int, default=40)
    parser.add_argument(
        "--negative-ratio",
        type=int,
        default=5,
        help="Compatibility alias from plan; maps to pseudo_per_src if pseudo_per_src is not explicitly changed.",
    )
    parser.add_argument("--category-pool-size", type=int, default=2000)
    parser.add_argument("--max-pseudo-scan-per-key", type=int, default=200)
    parser.add_argument("--max-items-per-user", type=int, default=80)
    parser.add_argument("--max-pairs-per-user", type=int, default=2000)
    parser.add_argument("--min-pair-support", type=int, default=1)
    parser.add_argument("--source-variant", default="itemcf_strong_augcf_lite_recent2y_v1")
    parser.add_argument(
        "--edge-mode",
        choices=("observed_plus_pseudo", "observed_only", "pseudo_only"),
        default="observed_plus_pseudo",
    )
    parser.add_argument("--exclude-hot-dst", action="store_true")
    parser.add_argument("--controlled-hot-budget", action="store_true")
    parser.add_argument("--max-hot-share-per-src", type=float, default=1.0)
    parser.add_argument("--max-final-hot-share-per-user", type=float, default=0.3)
    parser.add_argument("--max-pseudo-per-user", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260604)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pseudo_per_src = args.pseudo_per_src
    if "--pseudo-per-src" not in sys.argv and "--negative-ratio" in sys.argv:
        pseudo_per_src = max(0, args.negative_ratio * 8)
    config = AugCFLiteConfig(
        data_root=args.data_root,
        output_dir=args.output_dir,
        run_id=args.run_id,
        limit_users=args.limit_users,
        max_src_items=args.max_src_items,
        top_k_per_src=args.top_k_per_src,
        pseudo_per_src=pseudo_per_src,
        category_pool_size=args.category_pool_size,
        max_pseudo_scan_per_key=args.max_pseudo_scan_per_key,
        max_items_per_user=args.max_items_per_user,
        max_pairs_per_user=args.max_pairs_per_user,
        min_pair_support=args.min_pair_support,
        edge_mode=args.edge_mode,
        allow_hot_dst=not args.exclude_hot_dst,
        max_hot_share_per_src=args.max_hot_share_per_src,
        controlled_hot_budget=args.controlled_hot_budget,
        source_variant=args.source_variant,
        max_final_hot_share_per_user=args.max_final_hot_share_per_user,
        max_pseudo_per_user=args.max_pseudo_per_user,
        seed=args.seed,
    )
    manifest = build_itemcf_strong_augcf_lite_method_dataset(config)
    print(json.dumps({"status": manifest["status"], "manifest": manifest["outputs"]["method_dataset_manifest"], "row_count": manifest["row_count"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
