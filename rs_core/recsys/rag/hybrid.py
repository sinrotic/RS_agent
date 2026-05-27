from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rs_core.recsys.rag.bm25 import SQLiteBM25CandidateRetriever
from rs_core.recsys.rag.schema import RagEvidence

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class HybridCandidateRetriever:
    index_path: str | Path
    bm25_weight: float = 0.65
    vector_weight: float = 0.35
    vector_dim: int = 256
    vector_top_k_multiplier: int = 4

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        candidate_ids = [str(item_id) for item_id in candidate_item_ids if str(item_id)]
        if not candidate_ids or not query or not Path(self.index_path).exists():
            return []

        bm25_evidence = SQLiteBM25CandidateRetriever(self.index_path).retrieve(query, candidate_ids, max_evidence_per_item)
        vector_evidence = self._vector_evidence(query, candidate_ids, max_evidence_per_item)
        return self._fuse(bm25_evidence, vector_evidence, max_evidence_per_item)

    def _vector_evidence(self, query: str, candidate_ids: list[str], max_evidence_per_item: int) -> list[RagEvidence]:
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
            metadata.update({"retriever": "hybrid_vector", "vector_score": score, "vector_dim": self.vector_dim})
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
        bm25_scores = _score_by_key(bm25_evidence)
        vector_scores = _score_by_key(vector_evidence)
        bm25_norm = _min_max_normalize(bm25_scores)
        vector_norm = _min_max_normalize(vector_scores)
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
            hybrid_score = self.bm25_weight * bm25_value + self.vector_weight * vector_value
            metadata = dict(evidence.metadata)
            metadata.update(
                {
                    "retriever": "hybrid",
                    "bm25_score": bm25_raw,
                    "bm25_norm": bm25_value,
                    "vector_score": vector_raw,
                    "vector_norm": vector_value,
                    "hybrid_score": hybrid_score,
                    "bm25_weight": self.bm25_weight,
                    "vector_weight": self.vector_weight,
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


def _candidate_chunks(index_path: Path, candidate_ids: list[str]) -> list[tuple[Any, ...]]:
    placeholders = ",".join("?" for _ in candidate_ids)
    sql = f"""
        SELECT item_id, field, text, source, metadata_json
        FROM rag_chunks
        WHERE item_id IN ({placeholders})
    """
    with sqlite3.connect(index_path) as conn:
        return conn.execute(sql, candidate_ids).fetchall()


def _score_by_key(evidence: list[RagEvidence]) -> dict[tuple[str, str, str], float]:
    scores: dict[tuple[str, str, str], float] = {}
    for row in evidence:
        key = _evidence_key(row)
        scores[key] = max(scores.get(key, 0.0), float(row.score or 0.0))
    return scores


def _min_max_normalize(scores: dict[tuple[str, str, str], float]) -> dict[tuple[str, str, str], float]:
    if not scores:
        return {}
    values = list(scores.values())
    minimum = min(values)
    maximum = max(values)
    if maximum == minimum:
        return {key: 1.0 for key in scores}
    return {key: (value - minimum) / (maximum - minimum) for key, value in scores.items()}


def _limit_per_item(evidence: list[RagEvidence], max_evidence_per_item: int) -> list[RagEvidence]:
    counts: dict[str, int] = {}
    limited: list[RagEvidence] = []
    for row in sorted(evidence, key=lambda item: (-(item.score or 0.0), item.item_id, item.field, item.text)):
        count = counts.get(row.item_id, 0)
        if count >= max_evidence_per_item:
            continue
        counts[row.item_id] = count + 1
        limited.append(row)
    return limited


def _evidence_key(evidence: RagEvidence) -> tuple[str, str, str]:
    return evidence.item_id, evidence.field, evidence.text


def _loads(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
