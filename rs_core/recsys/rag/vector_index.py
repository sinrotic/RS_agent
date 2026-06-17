from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np

from rs_core.recsys.rag.chunking import DEFAULT_RAG_FIELDS, RagItemChunk, chunk_item_record
from rs_core.recsys.rag.corpus import RAG_COMPACT_DENSE_FIELD
from rs_core.recsys.rag.schema import RagEvidence

LOCAL_TFIDF_VECTOR_METHOD = "local_tfidf_vector_v1"
LOCAL_VECTOR_METHOD = LOCAL_TFIDF_VECTOR_METHOD
SENTENCE_TRANSFORMER_VECTOR_METHOD = "sentence_transformer_dense_v1"
DEFAULT_DENSE_MODEL_NAME = "BAAI/bge-m3"
DEFAULT_RAG_CORPUS_SCOPE = "product_catalog"
RAG_RETRIEVAL_SCOPE = "candidate_item_ids"


class TextEmbeddingBackend(Protocol):
    def encode(self, texts: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray: ...


@dataclass
class SentenceTransformerEmbeddingBackend:
    model_name: str = DEFAULT_DENSE_MODEL_NAME
    query_prefix: str = ""
    passage_prefix: str = ""

    def encode(self, texts: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is required for dense RAG embeddings; "
                "install requirements-training.txt or use vector_method='tfidf'."
            ) from exc

        model = SentenceTransformer(self.model_name)
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
            show_progress_bar=False,
        )
        return np.asarray(embeddings, dtype=np.float32)

    def encode_query(self, query: str, *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        return self.encode([f"{self.query_prefix}{query}"], normalize=normalize, batch_size=batch_size)[0]

    def encode_passages(self, passages: list[str], *, normalize: bool = True, batch_size: int = 32) -> np.ndarray:
        return self.encode([f"{self.passage_prefix}{text}" for text in passages], normalize=normalize, batch_size=batch_size)


@dataclass
class LocalVectorIndex:
    vectorizer: Any
    matrix: Any
    chunks: list[RagItemChunk]
    metadata: dict[str, Any] = field(default_factory=dict)

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
        top_k_multiplier: int = 4,
        embedding_backend: TextEmbeddingBackend | None = None,
    ) -> list[RagEvidence]:
        candidate_ids = {str(item_id) for item_id in candidate_item_ids if str(item_id)}
        if not query or not candidate_ids:
            return []

        indices = [index for index, chunk in enumerate(self.chunks) if chunk.item_id in candidate_ids]
        if not indices:
            return []

        method = str(self.metadata.get("local_vector_method") or self.metadata.get("embedding_method") or LOCAL_TFIDF_VECTOR_METHOD)
        if method == LOCAL_TFIDF_VECTOR_METHOD:
            scored = self._tfidf_scores(query, indices)
        elif method == SENTENCE_TRANSFORMER_VECTOR_METHOD:
            scored = self._dense_scores(query, indices, embedding_backend=embedding_backend)
        else:
            raise ValueError(f"unsupported local vector method: {method}")

        limit = max(len(candidate_ids) * max(max_evidence_per_item, 1) * max(top_k_multiplier, 1), 20)
        scored.sort(key=lambda row: (-row[0], row[1].item_id, row[1].field, row[1].text))
        evidence: list[RagEvidence] = []
        for score, chunk in scored[:limit]:
            metadata = dict(chunk.metadata)
            metadata.update(
                {
                    "retriever": "hybrid_vector",
                    "vector_method": method,
                    "vector_score": score,
                    "embedding_model_name": self.metadata.get("embedding_model_name"),
                }
            )
            evidence.append(
                RagEvidence(
                    item_id=chunk.item_id,
                    field=chunk.field,
                    text=chunk.text,
                    source=chunk.source,
                    score=score,
                    metadata=metadata,
                )
            )
        return evidence

    def _tfidf_scores(self, query: str, indices: list[int]) -> list[tuple[float, RagItemChunk]]:
        query_vector = self.vectorizer.transform([query])
        scores = query_vector @ self.matrix[indices].T
        values = scores.toarray()[0]
        scored: list[tuple[float, RagItemChunk]] = []
        for score, chunk_index in zip(values, indices, strict=True):
            value = float(score)
            if value > 0.0:
                scored.append((value, self.chunks[chunk_index]))
        return scored

    def _dense_scores(
        self,
        query: str,
        indices: list[int],
        *,
        embedding_backend: TextEmbeddingBackend | None,
    ) -> list[tuple[float, RagItemChunk]]:
        backend = embedding_backend or SentenceTransformerEmbeddingBackend(
            model_name=str(self.metadata.get("embedding_model_name") or DEFAULT_DENSE_MODEL_NAME),
            query_prefix=str(self.metadata.get("query_prefix") or ""),
            passage_prefix=str(self.metadata.get("passage_prefix") or ""),
        )
        normalize = bool(self.metadata.get("normalize_embeddings", True))
        batch_size = int(self.metadata.get("embedding_batch_size", 32) or 32)
        if hasattr(backend, "encode_query"):
            query_vector = backend.encode_query(query, normalize=normalize, batch_size=batch_size)  # type: ignore[attr-defined]
        else:
            query_vector = backend.encode([query], normalize=normalize, batch_size=batch_size)[0]

        matrix = np.asarray(self.matrix, dtype=np.float32)
        values = matrix[indices] @ np.asarray(query_vector, dtype=np.float32)
        scored: list[tuple[float, RagItemChunk]] = []
        for score, chunk_index in zip(values, indices, strict=True):
            value = float(score)
            if value > 0.0:
                scored.append((value, self.chunks[chunk_index]))
        return scored


def build_local_vector_index(
    vector_index_path: str | Path,
    items: Iterable[dict[str, Any]],
    fields: Iterable[str] | None = None,
    max_chunk_chars: int = 400,
    vector_method: str = SENTENCE_TRANSFORMER_VECTOR_METHOD,
    embedding_model_name: str = DEFAULT_DENSE_MODEL_NAME,
    embedding_backend: TextEmbeddingBackend | None = None,
    embedding_batch_size: int = 32,
    normalize_embeddings: bool = True,
    query_prefix: str = "",
    passage_prefix: str = "",
    corpus_scope: str = DEFAULT_RAG_CORPUS_SCOPE,
    item_level: bool = False,
    storage_dtype: str = "float32",
) -> Path:
    path = Path(vector_index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    vector_fields = [RAG_COMPACT_DENSE_FIELD] if item_level else list(fields or DEFAULT_RAG_FIELDS)
    chunks: list[RagItemChunk] = []
    for item in items:
        chunks.extend(chunk_item_record(item, fields=vector_fields, max_chunk_chars=max_chunk_chars))

    method = _normalize_vector_method(vector_method)
    dtype = _normalize_storage_dtype(storage_dtype)
    texts = [chunk.text for chunk in chunks]
    if method == LOCAL_TFIDF_VECTOR_METHOD:
        index = _build_tfidf_index(chunks, texts, corpus_scope=corpus_scope, item_level=item_level, storage_dtype=dtype)
    elif method == SENTENCE_TRANSFORMER_VECTOR_METHOD:
        index = _build_sentence_transformer_index(
            chunks,
            texts,
            embedding_model_name=embedding_model_name,
            embedding_backend=embedding_backend,
            embedding_batch_size=embedding_batch_size,
            normalize_embeddings=normalize_embeddings,
            query_prefix=query_prefix,
            passage_prefix=passage_prefix,
            corpus_scope=corpus_scope,
            item_level=item_level,
            storage_dtype=dtype,
        )
    else:
        raise ValueError(f"unsupported vector_method: {vector_method}")

    with path.open("wb") as handle:
        pickle.dump(index, handle)
    return path


def load_local_vector_index(vector_index_path: str | Path) -> LocalVectorIndex:
    with Path(vector_index_path).open("rb") as handle:
        loaded = pickle.load(handle)
    if not isinstance(loaded, LocalVectorIndex):
        raise TypeError(f"unsupported vector index artifact: {type(loaded).__name__}")
    return loaded


def _build_tfidf_index(chunks: list[RagItemChunk], texts: list[str], *, corpus_scope: str, item_level: bool, storage_dtype: str) -> LocalVectorIndex:
    from sklearn.feature_extraction.text import TfidfVectorizer

    vectorizer = TfidfVectorizer(lowercase=True, token_pattern=r"(?u)\b\w\w+\b")
    matrix = vectorizer.fit_transform(texts or ["empty"])
    if not texts:
        matrix = matrix[:0]
    return LocalVectorIndex(
        vectorizer=vectorizer,
        matrix=matrix,
        chunks=chunks,
        metadata={
            "embedding_method": LOCAL_TFIDF_VECTOR_METHOD,
            "local_vector_method": LOCAL_TFIDF_VECTOR_METHOD,
            "chunk_count": len(chunks),
            "corpus_scope": corpus_scope,
            "retrieval_scope": RAG_RETRIEVAL_SCOPE,
            "artifact_role": "rag_evidence",
            "knowledge_base_role": "rag_evidence",
            "candidate_scoped": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "item_level": item_level,
            "storage_dtype": storage_dtype,
        },
    )


def _build_sentence_transformer_index(
    chunks: list[RagItemChunk],
    texts: list[str],
    *,
    embedding_model_name: str,
    embedding_backend: TextEmbeddingBackend | None,
    embedding_batch_size: int,
    normalize_embeddings: bool,
    query_prefix: str,
    passage_prefix: str,
    corpus_scope: str,
    item_level: bool,
    storage_dtype: str,
) -> LocalVectorIndex:
    backend = embedding_backend or SentenceTransformerEmbeddingBackend(
        model_name=embedding_model_name,
        query_prefix=query_prefix,
        passage_prefix=passage_prefix,
    )
    if texts:
        if hasattr(backend, "encode_passages"):
            matrix = backend.encode_passages(texts, normalize=normalize_embeddings, batch_size=embedding_batch_size)  # type: ignore[attr-defined]
        else:
            matrix = backend.encode(texts, normalize=normalize_embeddings, batch_size=embedding_batch_size)
    else:
        matrix = np.zeros((0, 0), dtype=np.float32)
    matrix_dtype = np.float16 if storage_dtype == "float16" else np.float32
    return LocalVectorIndex(
        vectorizer=None,
        matrix=np.asarray(matrix, dtype=matrix_dtype),
        chunks=chunks,
        metadata={
            "embedding_method": SENTENCE_TRANSFORMER_VECTOR_METHOD,
            "local_vector_method": SENTENCE_TRANSFORMER_VECTOR_METHOD,
            "embedding_model_name": embedding_model_name,
            "embedding_batch_size": embedding_batch_size,
            "normalize_embeddings": normalize_embeddings,
            "query_prefix": query_prefix,
            "passage_prefix": passage_prefix,
            "chunk_count": len(chunks),
            "corpus_scope": corpus_scope,
            "retrieval_scope": RAG_RETRIEVAL_SCOPE,
            "artifact_role": "rag_evidence",
            "knowledge_base_role": "rag_evidence",
            "candidate_scoped": True,
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "item_level": item_level,
            "storage_dtype": storage_dtype,
        },
    )


def _normalize_storage_dtype(value: str) -> str:
    dtype = value.strip().lower()
    if dtype in {"fp16", "float16"}:
        return "float16"
    if dtype in {"fp32", "float32"}:
        return "float32"
    raise ValueError(f"unsupported storage_dtype: {value}")


def _normalize_vector_method(value: str) -> str:
    method = value.strip().lower()
    if method in {"tfidf", "local_tfidf", LOCAL_TFIDF_VECTOR_METHOD}:
        return LOCAL_TFIDF_VECTOR_METHOD
    if method in {"dense", "sentence_transformer", "sentence-transformer", SENTENCE_TRANSFORMER_VECTOR_METHOD}:
        return SENTENCE_TRANSFORMER_VECTOR_METHOD
    return method
