from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.io import iter_jsonl, write_json
from rs_core.recsys.rag import (
    DEFAULT_DENSE_MODEL_NAME,
    LOCAL_TFIDF_VECTOR_METHOD,
    LOCAL_VECTOR_METHOD,
    RAG_COMPACT_DENSE_FIELD,
    RAG_STANDARD_FIELDS,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    build_local_vector_index,
    build_sqlite_bm25_index,
)
from rs_core.recsys.rag.vector_index import DEFAULT_RAG_CORPUS_SCOPE, RAG_RETRIEVAL_SCOPE, TextEmbeddingBackend

DEFAULT_FIELDS = RAG_STANDARD_FIELDS


def build_rag_bm25_index(
    *,
    items_path: str | Path,
    index_path: str | Path,
    manifest_path: str | Path | None = None,
    fields: list[str] | None = None,
    max_chunk_chars: int = 400,
    vector_index_path: str | Path | None = None,
    vector_method: str = SENTENCE_TRANSFORMER_VECTOR_METHOD,
    embedding_model_name: str = DEFAULT_DENSE_MODEL_NAME,
    embedding_backend: TextEmbeddingBackend | None = None,
    embedding_batch_size: int = 32,
    normalize_embeddings: bool = True,
    query_prefix: str = "",
    passage_prefix: str = "",
    corpus_scope: str = DEFAULT_RAG_CORPUS_SCOPE,
    source_manifest_path: str | Path | None = None,
    item_universe: str = "train_only",
    catalog_snapshot_scope: str = "recent_window_train_catalog",
    text_policy: str = "compact_catalog_source_fields_v1",
    dense_granularity: str = "item",
    embedding_dtype: str = "float16",
    fusion_method: str = "rrf",
    item_text_compact_source_only: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    items_path = _resolve_path(items_path)
    index_path = _resolve_path(index_path)
    manifest_path = _resolve_path(manifest_path) if manifest_path else index_path.with_suffix(index_path.suffix + ".manifest.json")
    source_manifest_path = _resolve_path(source_manifest_path) if source_manifest_path else None
    if not items_path.is_file():
        raise FileNotFoundError(str(items_path))
    if source_manifest_path and not source_manifest_path.is_file():
        raise FileNotFoundError(str(source_manifest_path))
    vector_index_path = _resolve_path(vector_index_path) if vector_index_path else None
    if index_path.exists() and not overwrite:
        raise FileExistsError(f"index already exists: {index_path}")
    if vector_index_path and vector_index_path.exists() and not overwrite:
        raise FileExistsError(f"vector index already exists: {vector_index_path}")
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(f"manifest already exists: {manifest_path}")

    selected_fields = fields or DEFAULT_FIELDS
    raw_item_text_indexed = any(field in {"full_text", "item_text"} for field in selected_fields)
    if raw_item_text_indexed and item_text_compact_source_only:
        raise ValueError("full_text/item_text are source-only under compact RAG text policy; pass --allow-non-compact-item-text to index them")
    fusion_method = _normalize_fusion_method(fusion_method)
    dense_granularity = _normalize_dense_granularity(dense_granularity)
    embedding_dtype = _normalize_embedding_dtype(embedding_dtype)
    item_row_count = 0
    if vector_index_path:
        items = list(iter_jsonl(items_path))
        item_row_count = len(items)
    else:
        item_counter = {"count": 0}
        items = _counted_iter_jsonl(items_path, item_counter)
    build_sqlite_bm25_index(index_path, items, fields=selected_fields, max_chunk_chars=max_chunk_chars)
    if not vector_index_path:
        item_row_count = item_counter["count"]
    local_vector_method = _manifest_vector_method(vector_method) if vector_index_path else None
    if vector_index_path:
        build_local_vector_index(
            vector_index_path,
            items,
            fields=selected_fields,
            max_chunk_chars=max_chunk_chars,
            vector_method=vector_method,
            embedding_model_name=embedding_model_name,
            embedding_backend=embedding_backend,
            embedding_batch_size=embedding_batch_size,
            normalize_embeddings=normalize_embeddings,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            corpus_scope=corpus_scope,
            item_level=dense_granularity == "item",
            storage_dtype=embedding_dtype,
        )
    counts = _index_counts(index_path)
    manifest = {
        "schema_version": "rag_sqlite_bm25_index_v1",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "items_path": str(items_path),
        "index_path": str(index_path),
        "fields": selected_fields,
        "max_chunk_chars": max_chunk_chars,
        "item_row_count": item_row_count,
        "indexed_item_count": counts["indexed_item_count"],
        "chunk_count": counts["chunk_count"],
        "corpus_scope": corpus_scope,
        "index_scope": corpus_scope,
        "retrieval_scope": RAG_RETRIEVAL_SCOPE,
        "artifact_role": "rag_evidence",
        "knowledge_base_role": "rag_evidence",
        "source_manifest_path": str(source_manifest_path) if source_manifest_path else None,
        "item_universe": item_universe,
        "catalog_snapshot_scope": catalog_snapshot_scope,
        "text_policy": text_policy,
        "bm25_fields": selected_fields,
        "compact_dense_field": RAG_COMPACT_DENSE_FIELD if dense_granularity == "item" else None,
        "raw_item_text_indexed": raw_item_text_indexed,
        "item_text_compact_source_only": item_text_compact_source_only,
        "dense_granularity": dense_granularity,
        "embedding_dtype": embedding_dtype,
        "retriever": "sqlite_bm25",
        "hybrid_supported": True,
        "hybrid_vector_method": local_vector_method or "hashed_text_vector_v1",
        "embedding_method": local_vector_method,
        "local_vector_method": local_vector_method,
        "embedding_model_name": embedding_model_name if local_vector_method == SENTENCE_TRANSFORMER_VECTOR_METHOD else None,
        "embedding_batch_size": embedding_batch_size if local_vector_method == SENTENCE_TRANSFORMER_VECTOR_METHOD else None,
        "normalize_embeddings": normalize_embeddings if local_vector_method == SENTENCE_TRANSFORMER_VECTOR_METHOD else None,
        "query_prefix": query_prefix if local_vector_method == SENTENCE_TRANSFORMER_VECTOR_METHOD else None,
        "passage_prefix": passage_prefix if local_vector_method == SENTENCE_TRANSFORMER_VECTOR_METHOD else None,
        "fusion_method": fusion_method,
        "fusion_supported": ["weighted", "rrf"],
        "vector_index_path": str(vector_index_path) if vector_index_path else None,
        "candidate_scoped": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "safety_flags": {
            "candidate_scoped": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "raw_item_text_indexed": raw_item_text_indexed,
            "item_text_compact_source_only": item_text_compact_source_only,
        },
    }
    write_json(manifest_path, manifest)
    return manifest


def _index_counts(index_path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(index_path)) as conn:
        chunk_count = int(conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0])
        indexed_item_count = int(conn.execute("SELECT COUNT(DISTINCT item_id) FROM rag_chunks").fetchone()[0])
    return {"chunk_count": chunk_count, "indexed_item_count": indexed_item_count}


def _counted_iter_jsonl(path: Path, item_counter: dict[str, int]):
    for item in iter_jsonl(path):
        item_counter["count"] += 1
        yield item


def _manifest_vector_method(value: str) -> str:
    method = value.strip().lower()
    if method in {"tfidf", "local_tfidf", LOCAL_VECTOR_METHOD, LOCAL_TFIDF_VECTOR_METHOD}:
        return LOCAL_TFIDF_VECTOR_METHOD
    if method in {"dense", "sentence_transformer", "sentence-transformer", SENTENCE_TRANSFORMER_VECTOR_METHOD}:
        return SENTENCE_TRANSFORMER_VECTOR_METHOD
    return method


def _normalize_fusion_method(value: str) -> str:
    method = value.strip().lower()
    if method in {"weighted", "score", "weighted_score"}:
        return "weighted"
    if method == "rrf":
        return "rrf"
    raise ValueError(f"unsupported fusion_method: {value}")


def _normalize_dense_granularity(value: str) -> str:
    granularity = value.strip().lower()
    if granularity in {"item", "item_level"}:
        return "item"
    if granularity in {"chunk", "chunk_level"}:
        return "chunk"
    raise ValueError(f"unsupported dense_granularity: {value}")


def _normalize_embedding_dtype(value: str) -> str:
    dtype = value.strip().lower()
    if dtype in {"fp16", "float16"}:
        return "float16"
    if dtype in {"fp32", "float32"}:
        return "float32"
    raise ValueError(f"unsupported embedding_dtype: {value}")


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
    parser.add_argument("--vector-index", help="Optional output path for a local vector index")
    parser.add_argument("--vector-method", default=SENTENCE_TRANSFORMER_VECTOR_METHOD, help="tfidf or dense/sentence_transformer")
    parser.add_argument("--embedding-model-name", default=DEFAULT_DENSE_MODEL_NAME)
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    parser.add_argument("--no-normalize-embeddings", action="store_true")
    parser.add_argument("--query-prefix", default="")
    parser.add_argument("--passage-prefix", default="")
    parser.add_argument("--corpus-scope", default=DEFAULT_RAG_CORPUS_SCOPE)
    parser.add_argument("--source-manifest", help="Recent-window dataset manifest used to build this RAG catalog index")
    parser.add_argument("--item-universe", default="train_only")
    parser.add_argument("--catalog-snapshot-scope", default="recent_window_train_catalog")
    parser.add_argument("--text-policy", default="compact_catalog_source_fields_v1")
    parser.add_argument("--dense-granularity", default="item", choices=["item", "chunk"])
    parser.add_argument("--embedding-dtype", default="float16", choices=["float16", "float32", "fp16", "fp32"])
    parser.add_argument("--fusion-method", default="rrf", choices=["weighted", "rrf"])
    parser.add_argument("--allow-non-compact-item-text", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    manifest = build_rag_bm25_index(
        items_path=args.items,
        index_path=args.index,
        manifest_path=args.manifest,
        fields=list(args.fields),
        max_chunk_chars=args.max_chunk_chars,
        vector_index_path=args.vector_index,
        vector_method=args.vector_method,
        embedding_model_name=args.embedding_model_name,
        embedding_batch_size=args.embedding_batch_size,
        normalize_embeddings=not args.no_normalize_embeddings,
        query_prefix=args.query_prefix,
        passage_prefix=args.passage_prefix,
        corpus_scope=args.corpus_scope,
        source_manifest_path=args.source_manifest,
        item_universe=args.item_universe,
        catalog_snapshot_scope=args.catalog_snapshot_scope,
        text_policy=args.text_policy,
        dense_granularity=args.dense_granularity,
        embedding_dtype=args.embedding_dtype,
        fusion_method=args.fusion_method,
        item_text_compact_source_only=not args.allow_non_compact_item_text,
        overwrite=args.overwrite,
    )
    print(f"built {manifest['chunk_count']} chunks for {manifest['indexed_item_count']} items -> {manifest['index_path']}")


if __name__ == "__main__":
    main()
