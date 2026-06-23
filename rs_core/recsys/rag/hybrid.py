from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rs_core.recsys.rag.retriever import CandidateEvidenceRetriever

from rs_core.recsys.rag.bm25 import SQLiteBM25CandidateRetriever
from rs_core.recsys.rag.corpus import RAG_COMPACT_DENSE_FIELD, RAG_DEFAULT_FIELD_WEIGHTS, RAG_EVIDENCE_FIELD_QUOTAS, RAG_STANDARD_FIELDS
from rs_core.recsys.rag.schema import RagEvidence
from rs_core.recsys.rag.vector_index import LOCAL_VECTOR_METHOD, TextEmbeddingBackend, load_local_vector_index

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class HybridCandidateRetriever:
    index_path: str | Path
    vector_index_path: str | Path | None = None
    bm25_weight: float = 0.65
    vector_weight: float = 0.35
    vector_dim: int = 256
    vector_top_k_multiplier: int = 4
    fusion_method: str = "weighted"
    rrf_k: int = 60
    field_weights: dict[str, float] | None = None
    embedding_backend: TextEmbeddingBackend | None = None
    vector_backend: CandidateEvidenceRetriever | None = None

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        candidate_ids = [str(item_id) for item_id in candidate_item_ids if str(item_id)]
        if not candidate_ids or not query:
            return []

        bm25_evidence = []
        has_bm25_index = Path(self.index_path).exists()
        has_vector_fallback = self._has_configured_vector_fallback()
        if has_bm25_index:
            try:
                bm25_evidence = SQLiteBM25CandidateRetriever(self.index_path).retrieve(query, candidate_ids, max_evidence_per_item)
            except sqlite3.Error:
                if not has_vector_fallback:
                    raise
        elif not has_vector_fallback:
            return []
        vector_evidence = self._vector_evidence(query, candidate_ids, max_evidence_per_item)
        return self._fuse(bm25_evidence, vector_evidence, max_evidence_per_item)

    def _has_configured_vector_fallback(self) -> bool:
        return self.vector_backend is not None or self.vector_index_path is not None or _manifest_vector_index_path(Path(self.index_path)) is not None

    def _vector_evidence(self, query: str, candidate_ids: list[str], max_evidence_per_item: int) -> list[RagEvidence]:
        if self.vector_backend is not None:
            try:
                return self.vector_backend.retrieve(query, candidate_ids, max_evidence_per_item)
            except Exception:
                return []

        vector_index_path = self.vector_index_path or _manifest_vector_index_path(Path(self.index_path))
        if vector_index_path and Path(vector_index_path).exists():
            return load_local_vector_index(vector_index_path).retrieve(
                query,
                candidate_item_ids=candidate_ids,
                max_evidence_per_item=max_evidence_per_item,
                top_k_multiplier=self.vector_top_k_multiplier,
                embedding_backend=self.embedding_backend,
            )

        query_vector = text_to_hashed_vector(query, self.vector_dim)
        if not query_vector:
            return []

        chunks = _candidate_chunks(Path(self.index_path), candidate_ids)
        scored: list[RagEvidence] = []
        for item_id, field, text, source, metadata_json in chunks:
            score = cosine_score(query_vector, text_to_hashed_vector(text, self.vector_dim))
            if score <= 0.0:
                continue
            metadata = _loads(metadata_json)
            metadata.update(
                {
                    "retriever": "hybrid_vector",
                    "vector_method": "hashed_text_vector_v1",
                    "vector_score": score,
                    "vector_dim": self.vector_dim,
                }
            )
            scored.append(
                RagEvidence(
                    item_id=str(item_id),
                    field=str(field),
                    text=str(text),
                    source=str(source or "catalog_bm25"),
                    score=score,
                    metadata=metadata,
                )
            )

        limit = max(len(candidate_ids) * max(max_evidence_per_item, 1) * max(self.vector_top_k_multiplier, 1), 20)
        scored.sort(key=lambda row: (-(row.score or 0.0), row.item_id, row.field, row.text))
        return scored[:limit]

    def _fuse(
        self,
        bm25_evidence: list[RagEvidence],
        vector_evidence: list[RagEvidence],
        max_evidence_per_item: int,
    ) -> list[RagEvidence]:
        method = _normalize_fusion_method(self.fusion_method)
        bm25_scores = _score_by_key(bm25_evidence)
        vector_scores = _score_by_key(vector_evidence)
        bm25_norm = _min_max_normalize(bm25_scores)
        vector_norm = _min_max_normalize(vector_scores)
        bm25_ranks = _rank_by_key(bm25_evidence)
        vector_ranks = _rank_by_key(vector_evidence)
        vector_methods = {_evidence_key(row): row.metadata.get("vector_method", LOCAL_VECTOR_METHOD) for row in vector_evidence}
        rows: dict[tuple[str, str, str], RagEvidence] = {}
        for evidence in [*bm25_evidence, *vector_evidence]:
            key = _evidence_key(evidence)
            if key not in rows:
                rows[key] = evidence

        fused: list[RagEvidence] = []
        for key, evidence in rows.items():
            bm25_raw = bm25_scores.get(key, 0.0)
            vector_raw = vector_scores.get(key, 0.0)
            bm25_value = bm25_norm.get(key, 0.0)
            vector_value = vector_norm.get(key, 0.0)
            bm25_rrf = _rrf_score(bm25_ranks.get(key), self.rrf_k)
            vector_rrf = _rrf_score(vector_ranks.get(key), self.rrf_k)
            field_weight = _field_weight(self.field_weights, evidence.field)
            if method == "rrf":
                hybrid_score = field_weight * (self.bm25_weight * bm25_rrf + self.vector_weight * vector_rrf)
            else:
                hybrid_score = field_weight * (self.bm25_weight * bm25_value + self.vector_weight * vector_value)
            metadata = dict(evidence.metadata)
            metadata.update(
                {
                    "retriever": "hybrid",
                    "fusion_method": method,
                    "bm25_score": bm25_raw,
                    "bm25_norm": bm25_value,
                    "bm25_rank": bm25_ranks.get(key),
                    "bm25_rrf": bm25_rrf,
                    "vector_score": vector_raw,
                    "vector_norm": vector_value,
                    "vector_rank": vector_ranks.get(key),
                    "vector_rrf": vector_rrf,
                    "vector_method": vector_methods.get(key),
                    "hybrid_score": hybrid_score,
                    "bm25_weight": self.bm25_weight,
                    "vector_weight": self.vector_weight,
                    "field_weight": field_weight,
                }
            )
            fused.append(
                RagEvidence(
                    item_id=evidence.item_id,
                    field=evidence.field,
                    text=evidence.text,
                    source=evidence.source,
                    score=hybrid_score,
                    metadata=metadata,
                )
            )

        return _limit_per_item(fused, max_evidence_per_item)


def text_to_hashed_vector(text: str, dim: int = 256) -> dict[int, float]:
    values: dict[int, float] = {}
    for token in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if int.from_bytes(digest[4:], "big") % 2 == 0 else -1.0
        values[index] = values.get(index, 0.0) + sign
    norm = math.sqrt(sum(value * value for value in values.values()))
    if norm <= 0.0:
        return {}
    return {index: value / norm for index, value in values.items()}


def cosine_score(left: dict[int, float], right: dict[int, float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) > len(right):
        left, right = right, left
    return sum(value * right.get(index, 0.0) for index, value in left.items())


def _manifest_vector_index_path(index_path: Path) -> Path | None:
    manifest_path = index_path.with_suffix(index_path.suffix + ".manifest.json")
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = manifest.get("vector_index_path") if isinstance(manifest, dict) else None
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else manifest_path.parent / path


def _candidate_chunks(index_path: Path, candidate_ids: list[str]) -> list[tuple[Any, ...]]:
    placeholders = ",".join("?" for _ in candidate_ids)
    sql = f"""
        SELECT item_id, field, text, source, metadata_json
        FROM rag_chunks
        WHERE item_id IN ({placeholders})
    """
    with closing(sqlite3.connect(index_path)) as conn:
        return conn.execute(sql, candidate_ids).fetchall()


def _score_by_key(evidence: list[RagEvidence]) -> dict[tuple[str, str, str], float]:
    scores: dict[tuple[str, str, str], float] = {}
    for row in evidence:
        key = _evidence_key(row)
        scores[key] = max(scores.get(key, 0.0), float(row.score or 0.0))
    return scores


def _rank_by_key(evidence: list[RagEvidence]) -> dict[tuple[str, str, str], int]:
    ranks: dict[tuple[str, str, str], int] = {}
    for rank, row in enumerate(evidence, start=1):
        ranks.setdefault(_evidence_key(row), rank)
    return ranks


def _min_max_normalize(scores: dict[tuple[str, str, str], float]) -> dict[tuple[str, str, str], float]:
    if not scores:
        return {}
    values = list(scores.values())
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return {key: 1.0 for key in scores}
    return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}


def _rrf_score(rank: int | None, rrf_k: int) -> float:
    if rank is None:
        return 0.0
    return 1.0 / (max(rrf_k, 1) + rank)


def _field_weight(field_weights: dict[str, float] | None, field_name: str) -> float:
    if field_weights and field_name in field_weights:
        return float(field_weights[field_name])
    return float(RAG_DEFAULT_FIELD_WEIGHTS.get(field_name, 1.0))


def _normalize_fusion_method(value: str) -> str:
    method = value.strip().lower()
    if method in {"weighted", "score", "weighted_score"}:
        return "weighted"
    if method == "rrf":
        return "rrf"
    raise ValueError(f"unsupported hybrid fusion method: {value}")


def _limit_per_item(evidence: list[RagEvidence], max_evidence_per_item: int) -> list[RagEvidence]:
    counts: dict[str, int] = {}
    field_counts: dict[tuple[str, str], int] = {}
    limited: list[RagEvidence] = []
    for row in sorted(evidence, key=lambda item: (-(item.score or 0.0), item.item_id, item.field, item.text)):
        if row.field not in RAG_STANDARD_FIELDS and row.field != RAG_COMPACT_DENSE_FIELD:
            continue
        if field_counts.get((row.item_id, row.field), 0) >= _field_quota(row.field):
            continue
        count = counts.get(row.item_id, 0)
        if count >= max_evidence_per_item:
            continue
        counts[row.item_id] = count + 1
        field_counts[(row.item_id, row.field)] = field_counts.get((row.item_id, row.field), 0) + 1
        limited.append(row)
    return limited


def _field_quota(field_name: str) -> int:
    return int(RAG_EVIDENCE_FIELD_QUOTAS.get(field_name, 10_000))


def _evidence_key(evidence: RagEvidence) -> tuple[str, str, str]:
    return evidence.item_id, evidence.field, evidence.text


def _loads(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
