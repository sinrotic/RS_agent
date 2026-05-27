from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_core.recsys.rag import build_sqlite_bm25_index

DEFAULT_FIELDS = ["title", "category", "main_category", "summary", "description", "features"]


def build_rag_bm25_index(
    *,
    items_path: str | Path,
    index_path: str | Path,
    manifest_path: str | Path | None = None,
    fields: list[str] | None = None,
    max_chunk_chars: int = 400,
    overwrite: bool = False,
) -> dict[str, Any]:
    items_path = _resolve_path(items_path)
    index_path = _resolve_path(index_path)
    manifest_path = _resolve_path(manifest_path) if manifest_path else index_path.with_suffix(index_path.suffix + ".manifest.json")
    if not items_path.is_file():
        raise FileNotFoundError(str(items_path))
    if index_path.exists() and not overwrite:
        raise FileExistsError(f"index already exists: {index_path}")
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(f"manifest already exists: {manifest_path}")

    selected_fields = fields or DEFAULT_FIELDS
    items = list(iter_jsonl(items_path))
    build_sqlite_bm25_index(index_path, items, fields=selected_fields, max_chunk_chars=max_chunk_chars)
    counts = _index_counts(index_path)
    manifest = {
        "schema_version": "rag_sqlite_bm25_index_v1",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items_path": str(items_path),
        "index_path": str(index_path),
        "fields": selected_fields,
        "max_chunk_chars": max_chunk_chars,
        "item_row_count": len(items),
        "indexed_item_count": counts["indexed_item_count"],
        "chunk_count": counts["chunk_count"],
        "retriever": "sqlite_bm25",
        "hybrid_supported": True,
        "hybrid_vector_method": "hashed_text_vector_v1",
        "candidate_scoped": True,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
    }
    write_json(manifest_path, manifest)
    return manifest


def _index_counts(index_path: Path) -> dict[str, int]:
    with sqlite3.connect(index_path) as conn:
        chunk_count = int(conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0])
        indexed_item_count = int(conn.execute("SELECT COUNT(DISTINCT item_id) FROM rag_chunks").fetchone()[0])
    return {"chunk_count": chunk_count, "indexed_item_count": indexed_item_count}


def _resolve_path(path: str | Path | None) -> Path:
    if path is None:
        raise ValueError("path is required")
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a lightweight SQLite FTS5/BM25 RAG index from item JSONL.")
    parser.add_argument("--items", required=True, help="Item JSONL path, e.g. data/processed/.../canonical_items.jsonl")
    parser.add_argument("--index", required=True, help="Output SQLite index path")
    parser.add_argument("--manifest", help="Output manifest path; defaults to <index>.manifest.json")
    parser.add_argument("--fields", nargs="+", default=DEFAULT_FIELDS, help="Item fields to chunk and index")
    parser.add_argument("--max-chunk-chars", type=int, default=400)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manifest = build_rag_bm25_index(
        items_path=args.items,
        index_path=args.index,
        manifest_path=args.manifest,
        fields=list(args.fields),
        max_chunk_chars=args.max_chunk_chars,
        overwrite=args.overwrite,
    )
    print(f"built {manifest['chunk_count']} chunks for {manifest['indexed_item_count']} items -> {manifest['index_path']}")


if __name__ == "__main__":
    main()
