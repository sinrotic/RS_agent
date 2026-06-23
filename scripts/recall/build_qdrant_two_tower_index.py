from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.recsys.vectorstores.qdrant_builders import add_qdrant_connection_args, merge_qdrant_config, qdrant_config_from_args, qdrant_config_from_env  # noqa: E402
from rs_core.recsys.vectorstores.qdrant_contracts import DEFAULT_TWO_TOWER_COLLECTION  # noqa: E402
from rs_core.recsys.vectorstores.qdrant_two_tower_build import build_qdrant_two_tower_item_index  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Qdrant collection from a validated two-tower source index manifest.")
    parser.add_argument("--source-index-manifest", required=True, help="Path to source_index_manifest.json")
    parser.add_argument("--collection-name", default=DEFAULT_TWO_TOWER_COLLECTION)
    parser.add_argument("--manifest", default=None, help="Output Qdrant migration manifest path")
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--limit-items", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    add_qdrant_connection_args(parser)
    return parser


def main(argv: list[str] | None = None) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(argv)
    qdrant_config = merge_qdrant_config(qdrant_config_from_env(), qdrant_config_from_args(args))
    manifest = build_qdrant_two_tower_item_index(
        source_index_manifest_path=args.source_index_manifest,
        collection_name=args.collection_name,
        qdrant_config=qdrant_config,
        manifest_path=args.manifest,
        batch_size=args.batch_size,
        limit_items=args.limit_items,
        dry_run=args.dry_run,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    main()
