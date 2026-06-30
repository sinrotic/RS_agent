from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from rs_core.agent.rag.chunking import RagItemChunk
from rs_core.agent.rag.vector_index import TextEmbeddingBackend


def encode_chunks(
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


def validate_chunk_vectors(chunks: list[RagItemChunk], vectors: list[list[float]]) -> None:
    if len(vectors) != len(chunks):
        raise ValueError(f"RAG embedding backend returned {len(vectors)} vectors for {len(chunks)} chunks")
    if not vectors:
        raise ValueError("RAG vector build requires at least one embedding vector")
    vector_size = len(vectors[0])
    if vector_size <= 0:
        raise ValueError("RAG embedding vectors must be non-empty")
    for index, vector in enumerate(vectors):
        if len(vector) != vector_size:
            raise ValueError(f"RAG embedding dimension mismatch at chunk {index}: expected {vector_size}, got {len(vector)}")
        if any(not math.isfinite(value) for value in vector):
            raise ValueError(f"RAG embedding contains non-finite value at chunk {index}")


def manifest_token_sources(value: Any) -> list[str]:
    rows: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key) not in {"no_holdout", "train_only"}:
                rows.append(str(key))
            rows.extend(manifest_token_sources(nested))
    elif isinstance(value, list):
        for nested in value:
            rows.extend(manifest_token_sources(nested))
    elif isinstance(value, str):
        rows.append(value)
    return rows


def reject_forbidden_path(path: Path, field_name: str) -> None:
    if is_forbidden_path(path):
        raise ValueError(f"forbidden RAG vector {field_name}: {path}")


def is_forbidden_path(path: Path) -> bool:
    in_pytest_tmp = False
    for part in path.parts:
        lowered = part.lower()
        if lowered.startswith("pytest-") or lowered.startswith("pytest_of_") or lowered.startswith("pytest-of-"):
            in_pytest_tmp = True
            continue
        if in_pytest_tmp and lowered.startswith("test_"):
            continue
        if contains_forbidden_token(part):
            return True
    return False


def contains_forbidden_token(value: str) -> bool:
    normalized = str(value).lower()
    for separator in ("/", "\\", "-", ".", "_"):
        normalized = normalized.replace(separator, "_")
    tokens = {token for token in normalized.split("_") if token}
    return bool(tokens & {"valid", "validation", "test", "holdout", "eval", "oracle", "label", "ground", "truth", "target"})
