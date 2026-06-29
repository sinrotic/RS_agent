from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from rs_core.common.io import iter_jsonl, read_json
from rs_core.agent.rag.build_utils import (
    contains_forbidden_token,
    encode_chunks,
    manifest_token_sources,
    reject_forbidden_path,
    validate_chunk_vectors,
)
from rs_core.agent.rag.chunking import DEFAULT_RAG_FIELDS, RagItemChunk, chunk_item_record
from rs_core.agent.rag.vector_index import (
    DEFAULT_DENSE_MODEL_NAME,
    DEFAULT_RAG_CORPUS_SCOPE,
    RAG_RETRIEVAL_SCOPE,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    SentenceTransformerEmbeddingBackend,
    TextEmbeddingBackend,
)
from rs_core.recsys.vectorstores.milvus_builders import (
    build_store,
    milvus_collection_manifest_base,
    validate_milvus_build_controls,
    write_manifest_if_requested,
)
from rs_core.recsys.vectorstores.milvus_contracts import (
    DEFAULT_MILVUS_INDEX_TYPE,
    DEFAULT_MILVUS_METRIC_TYPE,
    DEFAULT_MILVUS_RAG_CHUNK_COLLECTION,
    MILVUS_RAG_CHUNK_INDEX_MANIFEST_SCHEMA_VERSION,
    MILVUS_RAG_CHUNK_SCHEMA_VERSION,
    MILVUS_RAG_SCALAR_FIELDS,
    MilvusCollectionSpec,
    milvus_payload_for_schema,
)
from rs_core.recsys.vectorstores.milvus_filters import and_expr, corpus_scope_expr, ne_expr, schema_version_expr
from rs_core.recsys.vectorstores.payloads import rag_chunk_payload, stable_vector_point_id


def build_milvus_rag_chunk_index(
    *,
    items_path: str | Path,
    collection_name: str = DEFAULT_MILVUS_RAG_CHUNK_COLLECTION,
    milvus_config: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    max_chunk_chars: int = 400,
    embedding_backend: TextEmbeddingBackend | None = None,
    embedding_model_name: str = DEFAULT_DENSE_MODEL_NAME,
    embedding_batch_size: int = 32,
    normalize_embeddings: bool = True,
    query_prefix: str = "",
    passage_prefix: str = "",
    corpus_scope: str = DEFAULT_RAG_CORPUS_SCOPE,
    source_manifest_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    batch_size: int = 128,
    limit_items: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    validate_milvus_build_controls(batch_size=batch_size, limit_items=limit_items, dry_run=dry_run, milvus_config=milvus_config)
    item_file = Path(items_path).resolve()
    if not item_file.is_file():
        raise FileNotFoundError(str(item_file))
    reject_forbidden_path(item_file, "items_path")
    source_manifest_file = Path(source_manifest_path).resolve() if source_manifest_path else None
    if source_manifest_file and not source_manifest_file.is_file():
        raise FileNotFoundError(str(source_manifest_file))
    if source_manifest_file:
        _validate_source_manifest(source_manifest_file, require_governance=not dry_run)
    elif not dry_run:
        raise ValueError("non-dry-run Milvus RAG build requires --source-manifest for provenance validation")

    selected_fields = list(fields or DEFAULT_RAG_FIELDS)
    index_build_id = stable_vector_point_id("milvus_rag_build", item_file, selected_fields, max_chunk_chars, limit_items or "all", corpus_scope, uuid4().hex)
    backend = None
    store = None
    if not dry_run:
        backend = embedding_backend or SentenceTransformerEmbeddingBackend(model_name=embedding_model_name, query_prefix=query_prefix, passage_prefix=passage_prefix)

    item_row_count = 0
    indexed_item_ids: set[str] = set()
    chunk_count = 0
    upserted_chunk_count = 0
    vector_size: int | None = None
    stale_chunks_deleted = False
    pending_chunks: list[RagItemChunk] = []

    def flush_pending() -> None:
        nonlocal store, upserted_chunk_count, vector_size
        if dry_run or not pending_chunks:
            pending_chunks.clear()
            return
        active_chunks = pending_chunks[:batch_size]
        assert backend is not None
        vectors = encode_chunks(active_chunks, backend=backend, normalize_embeddings=normalize_embeddings, embedding_batch_size=embedding_batch_size)
        validate_chunk_vectors(active_chunks, vectors)
        batch_vector_size = len(vectors[0])
        if vector_size is None:
            vector_size = batch_vector_size
            store = build_store(milvus_config)
            store.ensure_collection(
                MilvusCollectionSpec(
                    collection_name=collection_name,
                    vector_size=vector_size,
                    metric_type=DEFAULT_MILVUS_METRIC_TYPE,
                    index_type=DEFAULT_MILVUS_INDEX_TYPE,
                    schema_version=MILVUS_RAG_CHUNK_SCHEMA_VERSION,
                    scalar_fields=MILVUS_RAG_SCALAR_FIELDS,
                )
            )
        elif batch_vector_size != vector_size:
            raise ValueError(f"RAG embedding dimension mismatch: expected {vector_size}, got {batch_vector_size}")
        assert store is not None
        store.upsert_points(
            collection_name=collection_name,
            points=[
                (
                    stable_vector_point_id("milvus_rag", corpus_scope, chunk.item_id, chunk.field, chunk.metadata.get("chunk_index", index)),
                    vector,
                    milvus_payload_for_schema(
                        rag_chunk_payload(
                            item_id=chunk.item_id,
                            field=chunk.field,
                            text=chunk.text,
                            source=chunk.source,
                            chunk_index=int(chunk.metadata.get("chunk_index", index)),
                            corpus_scope=corpus_scope,
                            embedding_method=SENTENCE_TRANSFORMER_VECTOR_METHOD,
                            embedding_model_name=embedding_model_name,
                            index_build_id=index_build_id,
                            metadata=chunk.metadata,
                        ),
                        MILVUS_RAG_CHUNK_SCHEMA_VERSION,
                    ),
                )
                for index, (chunk, vector) in enumerate(zip(active_chunks, vectors, strict=True))
            ],
        )
        upserted_chunk_count += len(active_chunks)
        del pending_chunks[:batch_size]

    for item in iter_jsonl(item_file):
        if limit_items is not None and item_row_count >= limit_items:
            break
        item_row_count += 1
        item_chunks = chunk_item_record(item, fields=selected_fields, max_chunk_chars=max_chunk_chars, source="catalog_rag_chunk")
        if not item_chunks:
            continue
        indexed_item_ids.update(chunk.item_id for chunk in item_chunks)
        chunk_count += len(item_chunks)
        pending_chunks.extend(item_chunks)
        while len(pending_chunks) >= batch_size:
            flush_pending()
    flush_pending()
    if not dry_run and upserted_chunk_count > 0:
        if store is None:
            store = build_store(milvus_config)
        store.delete_points_by_filter(collection_name=collection_name, query_filter=_stale_rag_build_expr(corpus_scope, index_build_id), ignore_missing=True)
        stale_chunks_deleted = True

    manifest = milvus_collection_manifest_base(
        schema_version=MILVUS_RAG_CHUNK_INDEX_MANIFEST_SCHEMA_VERSION,
        collection_name=collection_name,
        collection_schema_version=MILVUS_RAG_CHUNK_SCHEMA_VERSION,
        vector_size=vector_size,
        metric_type=DEFAULT_MILVUS_METRIC_TYPE,
        index_type=DEFAULT_MILVUS_INDEX_TYPE,
        dry_run=dry_run,
    )
    manifest.update(
        {
            "items_path": str(item_file),
            "source_manifest_path": str(source_manifest_file) if source_manifest_file else None,
            "fields": selected_fields,
            "max_chunk_chars": int(max_chunk_chars),
            "item_row_count": item_row_count,
            "indexed_item_count": len(indexed_item_ids),
            "chunk_count": chunk_count,
            "upserted_chunk_count": upserted_chunk_count,
            "index_build_id": index_build_id,
            "stale_chunks_deleted_for_corpus": stale_chunks_deleted,
            "limit_items": limit_items,
            "embedding_method": SENTENCE_TRANSFORMER_VECTOR_METHOD,
            "embedding_model_name": embedding_model_name,
            "embedding_batch_size": int(embedding_batch_size),
            "normalize_embeddings": bool(normalize_embeddings),
            "query_prefix": query_prefix,
            "passage_prefix": passage_prefix,
            "corpus_scope": corpus_scope,
            "retrieval_scope": RAG_RETRIEVAL_SCOPE,
            "artifact_role": "rag_evidence",
            "knowledge_base_role": "rag_evidence",
            "candidate_scoped": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "no_holdout": True,
        }
    )
    write_manifest_if_requested(manifest_path, manifest)
    return manifest


def _validate_source_manifest(path: Path, *, require_governance: bool) -> None:
    manifest = read_json(path)
    reject_forbidden_path(path, "source_manifest_path")
    if require_governance and (manifest.get("no_holdout") is not True or manifest.get("train_only") is not True):
        raise ValueError("RAG Milvus source manifest must explicitly set train_only=true and no_holdout=true")
    for token_source in manifest_token_sources(manifest):
        if contains_forbidden_token(token_source):
            raise ValueError("RAG Milvus source manifest references forbidden holdout/evaluation fields or paths")


def _stale_rag_build_expr(corpus_scope: str, index_build_id: str) -> str:
    return and_expr(schema_version_expr(MILVUS_RAG_CHUNK_SCHEMA_VERSION), corpus_scope_expr(corpus_scope), ne_expr("index_build_id", index_build_id))
