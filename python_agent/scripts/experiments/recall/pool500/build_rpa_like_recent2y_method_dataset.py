from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_lab.experiments.recall.build_rpa_like_recent2y_method_dataset import (  # noqa: E402
    RPALikeRecent2YDatasetConfig,
    build_rpa_like_recent2y_method_dataset,
    parse_args,
)


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or (
        ROOT / "outputs" / "recall" / "pool500_method_datasets" / "recent_2y" / "rpa_like_recursive_cf" / "v1" / args.scale_tier
    )
    run_id = args.run_id or f"rpa_like_recent2y_v1_{args.scale_tier}"
    manifest = build_rpa_like_recent2y_method_dataset(
        RPALikeRecent2YDatasetConfig(
            data_root=args.data_root,
            output_dir=output_dir,
            run_id=run_id,
            scale_tier=args.scale_tier,
            max_rss_mb=args.max_rss_mb,
            smoke_user_limit=args.smoke_user_limit,
            formal_max_users=args.formal_max_users,
            max_items_per_user=args.max_items_per_user,
            recursive_depth_cap=args.recursive_depth_cap,
            overwrite=args.overwrite,
            enforce_venv=not args.skip_venv_check,
        )
    )
    print(json.dumps({"status": manifest["status"], "manifest_path": manifest["outputs"]["method_dataset_manifest"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
