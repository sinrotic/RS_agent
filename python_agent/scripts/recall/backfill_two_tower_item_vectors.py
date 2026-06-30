from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, read_json, write_json, write_jsonl  # noqa: E402
from rs_core.online.recall.vectorstores.two_tower_backfill import backfill_two_tower_item_vectors  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill missing item vectors for a two-tower source index.")
    parser.add_argument("--source-index-manifest", required=True, type=Path)
    parser.add_argument("--canonical-items", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--index-path", default=None, type=Path, help="Override source index JSONL path from manifest.")
    parser.add_argument("--embedding-path", default=None, type=Path, help="Override source embedding JSONL path from manifest.")
    parser.add_argument("--manifest", default=None, type=Path, help="Output manifest path. Defaults to output-dir/source_index_manifest.json.")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    source_manifest_path = args.source_index_manifest.resolve()
    source_manifest = read_json(source_manifest_path)
    existing_path = _resolve_manifest_path(source_manifest_path, args.index_path or args.embedding_path or source_manifest.get("index_path") or source_manifest.get("embedding_path"))
    canonical_items_path = args.canonical_items.resolve()
    output_dir = args.output_dir.resolve()
    output_embedding_path = output_dir / "item_embeddings.backfilled.jsonl"
    output_index_path = output_dir / "two_tower_recall_index.backfilled.jsonl"
    output_manifest_path = (args.manifest or output_dir / "source_index_manifest.backfilled.json").resolve()

    result = backfill_two_tower_item_vectors(
        existing_rows=iter_jsonl(existing_path),
        catalog_rows=iter_jsonl(canonical_items_path),
    )

    manifest = dict(source_manifest)
    manifest.update(
        {
            "schema_version": source_manifest.get("schema_version", "two_tower_source_index_v1"),
            "source_status": "FULL_DERIVED_INDEX_WITH_BACKFILLED_COLD_START_VECTORS",
            "index_path": str(output_index_path),
            "embedding_path": str(output_embedding_path),
            "row_count": result.report["output_item_count"],
            "embedding_row_count": result.report["output_item_count"],
            "index_row_count": result.report["output_item_count"],
            "item_embedding_row_count": result.report["output_item_count"],
            "recall_index_row_count": result.report["output_item_count"],
            "backfill": result.report
            | {
                "source_index_manifest_path": str(source_manifest_path),
                "source_vector_path": str(existing_path),
                "canonical_items_path": str(canonical_items_path),
                "vector_origin_policy": "trained_two_tower_preserved_then_category_centroid_then_global_centroid",
            },
            "candidate_generation_allowed": bool(source_manifest.get("candidate_generation_allowed", False)),
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "train_only": True,
            "no_holdout": True,
        }
    )

    if not args.dry_run:
        write_jsonl(output_embedding_path, result.rows)
        write_jsonl(output_index_path, result.rows)
        write_json(output_manifest_path, manifest)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def _resolve_manifest_path(manifest_path: Path, value: Any) -> Path:
    if value is None or str(value).strip() == "":
        raise ValueError("source manifest does not provide index_path or embedding_path")
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


if __name__ == "__main__":
    main()
