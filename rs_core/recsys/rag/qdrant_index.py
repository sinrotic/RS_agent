from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from rs_core.common.io import iter_jsonl, read_json
from rs_core.recsys.rag.chunking import DEFAULT_RAG_FIELDS, RagItemChunk, chunk_item_record
from rs_core.recsys.rag.vector_index import (
    DEFAULT_DENSE_MODEL_NAME,
    DEFAULT_RAG_CORPUS_SCOPE,
    RAG_RETRIEVAL_SCOPE,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    SentenceTransformerEmbeddingBackend,
    TextEmbeddingBackend,
)
from rs_core.recsys.vectorstores.qdrant_builders import (
    batched,
    build_store,
    created_at_utc,
    qdrant_collection_manifest_base,
    validate_qdrant_build_controls,
    write_manifest_if_requested,
)
from rs_core.recsys.vectorstores.qdrant_contracts import (
    DEFAULT_QDRANT_DISTANCE,
    DEFAULT_RAG_CHUNK_COLLECTION,
    QDRANT_RAG_CHUNK_INDEX_MANIFEST_SCHEMA_VERSION,
    QDRANT_RAG_CHUNK_SCHEMA_VERSION,
    QDRANT_RAG_PAYLOAD_INDEX_FIELDS,
    QdrantCollectionSpec,
)
from rs_core.recsys.vectorstores.qdrant_filters import corpus_scope_condition, index_build_id_condition, schema_version_condition
from rs_core.recsys.vectorstores.qdrant_payloads import rag_chunk_payload, stable_qdrant_point_id


def build_qdrant_rag_chunk_index(
    *,
    items_path: str | Path,
    collection_name: str = DEFAULT_RAG_CHUNK_COLLECTION,
    qdrant_config: dict[str, Any] | None = None,
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
    validate_qdrant_build_controls(batch_size=batch_size, limit_items=limit_items, dry_run=dry_run, qdrant_config=qdrant_config)
    item_file = Path(items_path).resolve()
    if not item_file.is_file():
        raise FileNotFoundError(str(item_file))
    _reject_forbidden_path(item_file, "items_path")
    source_manifest_file = Path(source_manifest_path).resolve() if source_manifest_path else None
    if source_manifest_file and not source_manifest_file.is_file():
        raise FileNotFoundError(str(source_manifest_file))
    if source_manifest_file:
        _validate_source_manifest(source_manifest_file, require_governance=not dry_run)
    elif not dry_run:
        raise ValueError("non-dry-run Qdrant RAG build requires --source-manifest for provenance validation")

    selected_fields = list(fields or DEFAULT_RAG_FIELDS)
    item_row_count = 0
    indexed_item_ids: set[str] = set()
    chunks: list[RagItemChunk] = []
    build_started_at = created_at_utc()
    index_build_id = stable_qdrant_point_id("rag_build", item_file, selected_fields, max_chunk_chars, limit_items or "all", corpus_scope, build_started_at)
    for item in iter_jsonl(item_file):
        if limit_items is not None and item_row_count >= limit_items:
            break
        item_row_count += 1
        item_chunks = chunk_item_record(
            item,
            fields=selected_fields,
            max_chunk_chars=max_chunk_chars,
            source="catalog_rag_chunk",
        )
        if item_chunks:
            indexed_item_ids.update(chunk.item_id for chunk in item_chunks)
            chunks.extend(item_chunks)

    vector_size: int | None = None
    upserted_chunk_count = 0
    if not dry_run and chunks:
        backend = embedding_backend or SentenceTransformerEmbeddingBackend(
            model_name=embedding_model_name,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
        )
        vectors = _encode_chunks(
            chunks,
            backend=backend,
            normalize_embeddings=normalize_embeddings,
            embedding_batch_size=embedding_batch_size,
        )
        _validate_vectors(chunks, vectors)
        vector_size = len(vectors[0])
        if vector_size:
            store = build_store(qdrant_config)
            store.ensure_collection(
                QdrantCollectionSpec(
                    collection_name=collection_name,
                    vector_size=vector_size,
                    distance=DEFAULT_QDRANT_DISTANCE,
                    schema_version=QDRANT_RAG_CHUNK_SCHEMA_VERSION,
                    payload_indexes=QDRANT_RAG_PAYLOAD_INDEX_FIELDS,
                )
            )
            for batch in batched(zip(chunks, vectors, strict=True), batch_size):
                store.upsert_points(
                    collection_name=collection_name,
                    points=[
                        (
                            stable_qdrant_point_id("rag", chunk.item_id, chunk.field, chunk.metadata.get("chunk_index", index)),
                            vector,
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
                        )
                        for index, (chunk, vector) in enumerate(batch)
                    ],
                )
                upserted_chunk_count += len(batch)
            store.delete_points_by_filter(
                collection_name=collection_name,
                query_filter=_stale_rag_build_filter(corpus_scope, index_build_id),
            )

    manifest = qdrant_collection_manifest_base(
        schema_version=QDRANT_RAG_CHUNK_INDEX_MANIFEST_SCHEMA_VERSION,
        collection_name=collection_name,
        collection_schema_version=QDRANT_RAG_CHUNK_SCHEMA_VERSION,
        vector_size=vector_size,
        distance=DEFAULT_QDRANT_DISTANCE,
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
            "chunk_count": len(chunks),
            "upserted_chunk_count": upserted_chunk_count,
            "index_build_id": index_build_id,
            "stale_chunks_deleted_for_corpus": bool(not dry_run and chunks),
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


def _encode_chunks(
    chunks: list[RagItemChunk],
    *,
    backend: TextEmbeddingBackend,
    normalize_embeddings: bool,
    embedding_batch_size: int,
) -> list[list[float]]:
    texts = [chunk.text for chunk in chunks]
    if hasattr(backend, "encode_passages"):
        encoded = backend.encode_passages(texts, normalize=normalize_embeddings, batch_size=embedding_batch_size)  # type: ignore[attr-defined]
    else:
        encoded = backend.encode(texts, normalize=normalize_embeddings, batch_size=embedding_batch_size)
    return [[float(value) for value in row] for row in np.asarray(encoded, dtype=np.float32).tolist()]


def _validate_limit_items(limit_items: int | None) -> None:
    if limit_items is not None and limit_items < 0:
        raise ValueError("limit_items must be non-negative")


def _validate_vectors(chunks: list[RagItemChunk], vectors: list[list[float]]) -> None:
    if len(vectors) != len(chunks):
        raise ValueError(f"RAG embedding backend returned {len(vectors)} vectors for {len(chunks)} chunks")
    if not vectors:
        raise ValueError("RAG Qdrant build requires at least one embedding vector")
    vector_size = len(vectors[0])
    if vector_size <= 0:
        raise ValueError("RAG embedding vectors must be non-empty")
    for index, vector in enumerate(vectors):
        if len(vector) != vector_size:
            raise ValueError(f"RAG embedding dimension mismatch at chunk {index}: expected {vector_size}, got {len(vector)}")
        if any(not math.isfinite(value) for value in vector):
            raise ValueError(f"RAG embedding contains non-finite value at chunk {index}")


def _validate_source_manifest(path: Path, *, require_governance: bool) -> None:
    manifest = read_json(path)
    _reject_forbidden_path(path, "source_manifest_path")
    if require_governance and (manifest.get("no_holdout") is not True or manifest.get("train_only") is not True):
        raise ValueError("RAG Qdrant source manifest must explicitly set train_only=true and no_holdout=true")
    for token_source in _manifest_token_sources(manifest):
        if _contains_forbidden_token(token_source):
            raise ValueError("RAG Qdrant source manifest references forbidden holdout/evaluation fields or paths")


def _stale_rag_build_filter(corpus_scope: str, index_build_id: str) -> Any:
    from rs_core.recsys.vectorstores.qdrant_client import qdrant_models

    models = qdrant_models()
    return models.Filter(
        must=[
            schema_version_condition(QDRANT_RAG_CHUNK_SCHEMA_VERSION),
            corpus_scope_condition(corpus_scope),
        ],
        must_not=[index_build_id_condition(index_build_id)],
    )



def _manifest_token_sources(value: Any) -> list[str]:
    rows: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) not in {"no_holdout", "train_only"}:
                rows.append(str(key))
            rows.extend(_manifest_token_sources(nested))
    elif isinstance(value, list):
        for nested in value:
            rows.extend(_manifest_token_sources(nested))
    elif isinstance(value, str):
        rows.append(value)
    return rows



def _reject_forbidden_path(path: Path, field_name: str) -> None:
    if _is_forbidden_path(path):
        raise ValueError(f"forbidden RAG Qdrant {field_name}: {path}")


def _is_forbidden_path(path: Path) -> bool:
    in_pytest_tmp = False
    for part in path.parts:
        lowered = part.lower()
        if lowered.startswith("pytest-") or lowered.startswith("pytest_of_") or lowered.startswith("pytest-of-"):
            in_pytest_tmp = True
            continue
        if in_pytest_tmp and lowered.startswith("test_"):
            continue
        if _contains_forbidden_token(part):
            return True
    return False


def _contains_forbidden_token(value: str) -> bool:
    normalized = str(value).lower()
    for separator in ("/", "\\", "-", ".", "_"):
        normalized = normalized.replace(separator, "_")
    tokens = {token for token in normalized.split("_") if token}
    return bool(tokens & {"valid", "validation", "test", "holdout", "eval", "oracle", "label", "ground", "truth", "target"})
