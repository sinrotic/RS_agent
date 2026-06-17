from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from rs_core.recsys.rag.chunking import DEFAULT_RAG_FIELDS, chunk_item_record
from rs_core.recsys.rag.corpus import RAG_DEFAULT_FIELD_WEIGHTS, RAG_EVIDENCE_FIELD_QUOTAS, RAG_STANDARD_FIELDS
from rs_core.recsys.rag.schema import RagEvidence

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class SQLiteBM25Unavailable(RuntimeError):
    pass


class SQLiteBM25CandidateRetriever:
    def __init__(self, index_path: str | Path) -> None:
        self.index_path = Path(index_path)

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        candidate_ids = [str(item_id) for item_id in candidate_item_ids if str(item_id)]
        fts_query = _fts_query(query)
        if not candidate_ids or not fts_query or not self.index_path.exists():
            return []

        placeholders = ",".join("?" for _ in candidate_ids)
        limit = max(len(candidate_ids) * max(max_evidence_per_item, 1) * 8, 50)
        sql = f"""
            SELECT
                c.item_id,
                c.field,
                c.text,
                c.source,
                c.metadata_json,
                bm25(rag_chunk_fts) AS bm25_score
            FROM rag_chunk_fts
            JOIN rag_chunks c ON c.chunk_id = rag_chunk_fts.chunk_id
            WHERE rag_chunk_fts MATCH ?
              AND c.item_id IN ({placeholders})
            ORDER BY bm25_score ASC
            LIMIT ?
        """
        with closing(sqlite3.connect(self.index_path)) as conn:
            rows = conn.execute(sql, [fts_query, *candidate_ids, limit]).fetchall()

        evidence = [
            _row_to_evidence(item_id, field, text, source, metadata_json, bm25_score, retriever="sqlite_bm25")
            for item_id, field, text, source, metadata_json, bm25_score in rows
            if str(field) in RAG_STANDARD_FIELDS
        ]
        return _limit_evidence(evidence, max_evidence_per_item)


class SQLiteBM25QueryPlanningRetriever:
    def __init__(self, index_path: str | Path, fields: Iterable[str] | None = None) -> None:
        self.index_path = Path(index_path)
        self.fields = [str(field) for field in fields or [] if str(field)]

    def retrieve(
        self,
        query: str,
        max_evidence_total: int = 12,
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        fts_query = _fts_query(query)
        if not fts_query or not self.index_path.exists():
            return []

        params: list[Any] = [fts_query]
        field_clause = ""
        if self.fields:
            placeholders = ",".join("?" for _ in self.fields)
            field_clause = f" AND c.field IN ({placeholders})"
            params.extend(self.fields)
        limit = max(max(max_evidence_total, 1) * max(max_evidence_per_item, 1) * 4, 50)
        params.append(limit)
        sql = f"""
            SELECT
                c.item_id,
                c.field,
                c.text,
                c.source,
                c.metadata_json,
                bm25(rag_chunk_fts) AS bm25_score
            FROM rag_chunk_fts
            JOIN rag_chunks c ON c.chunk_id = rag_chunk_fts.chunk_id
            WHERE rag_chunk_fts MATCH ?{field_clause}
            ORDER BY bm25_score ASC
            LIMIT ?
        """
        with closing(sqlite3.connect(self.index_path)) as conn:
            rows = conn.execute(sql, params).fetchall()

        evidence = [
            _row_to_evidence(
                item_id,
                field,
                text,
                source,
                metadata_json,
                bm25_score,
                retriever="sqlite_bm25_query_planning",
                extra_metadata={
                    "retrieval_scope": "query_planning",
                    "candidate_generation_allowed": False,
                    "ranking_input_replacement_allowed": False,
                    "promotion_allowed": False,
                },
            )
            for item_id, field, text, source, metadata_json, bm25_score in rows
            if str(field) in RAG_STANDARD_FIELDS
        ]
        return _limit_evidence(evidence, max_evidence_per_item)[:max_evidence_total]


def build_sqlite_bm25_index(
    index_path: str | Path,
    items: Iterable[dict[str, Any]],
    fields: Iterable[str] | None = None,
    max_chunk_chars: int = 400,
    batch_size: int = 1000,
) -> Path:
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    selected_fields = fields or DEFAULT_RAG_FIELDS

    with closing(sqlite3.connect(path)) as conn:
        _ensure_fts5(conn)
        conn.executescript(
            """
            DROP TABLE IF EXISTS rag_chunk_fts;
            DROP TABLE IF EXISTS rag_chunks;
            CREATE TABLE rag_chunks (
                chunk_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL,
                field TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE rag_chunk_fts USING fts5(
                chunk_id UNINDEXED,
                text,
                tokenize='unicode61'
            );
            """
        )
        chunk_rows: list[tuple[str, str, str, str, str, str]] = []
        fts_rows: list[tuple[str, str]] = []
        chunk_index = 0
        for item in items:
            for chunk in chunk_item_record(item, fields=selected_fields, max_chunk_chars=max_chunk_chars):
                chunk_id = f"{chunk.item_id}:{chunk_index}"
                metadata_json = json.dumps(chunk.metadata, ensure_ascii=False, sort_keys=True)
                chunk_rows.append((chunk_id, chunk.item_id, chunk.field, chunk.text, chunk.source, metadata_json))
                fts_rows.append((chunk_id, chunk.text))
                chunk_index += 1
                if len(chunk_rows) >= batch_size:
                    _insert_chunk_rows(conn, chunk_rows, fts_rows)
                    chunk_rows.clear()
                    fts_rows.clear()
        if chunk_rows:
            _insert_chunk_rows(conn, chunk_rows, fts_rows)
        _create_lookup_indexes(conn)
        conn.commit()
    return path


def _insert_chunk_rows(
    conn: sqlite3.Connection,
    chunk_rows: list[tuple[str, str, str, str, str, str]],
    fts_rows: list[tuple[str, str]],
) -> None:
    conn.executemany(
        "INSERT INTO rag_chunks(chunk_id, item_id, field, text, source, metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
        chunk_rows,
    )
    conn.executemany("INSERT INTO rag_chunk_fts(chunk_id, text) VALUES (?, ?)", fts_rows)


def _create_lookup_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_item_id ON rag_chunks(item_id)")


def _ensure_fts5(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts5_probe USING fts5(text)")
        conn.execute("DROP TABLE IF EXISTS rag_fts5_probe")
    except sqlite3.OperationalError as exc:
        raise SQLiteBM25Unavailable("SQLite FTS5 is not available in this Python environment") from exc


def _fts_query(query: str) -> str:
    tokens = _TOKEN_RE.findall(query.lower())
    unique_tokens = list(dict.fromkeys(tokens))[:12]
    return " OR ".join(unique_tokens)


def _row_to_evidence(
    item_id: Any,
    field: Any,
    text: Any,
    source: Any,
    metadata_json: str,
    bm25_score: float,
    *,
    retriever: str,
    extra_metadata: dict[str, Any] | None = None,
) -> RagEvidence:
    field_name = str(field)
    raw_score = float(-bm25_score)
    field_weight = _field_weight(field_name)
    metadata = _loads(metadata_json)
    metadata.update({
        "retriever": retriever,
        "bm25_raw_score": bm25_score,
        "field_weight": field_weight,
        "weighted_score": raw_score * field_weight,
    })
    if extra_metadata:
        metadata.update(extra_metadata)
    return RagEvidence(
        item_id=str(item_id),
        field=field_name,
        text=str(text),
        source=str(source or retriever),
        score=raw_score * field_weight,
        metadata=metadata,
    )


def _limit_evidence(evidence: list[RagEvidence], max_evidence_per_item: int) -> list[RagEvidence]:
    per_item_counts: dict[str, int] = {}
    per_item_field_counts: dict[tuple[str, str], int] = {}
    limited: list[RagEvidence] = []
    for row in sorted(evidence, key=lambda item: (-(item.score or 0.0), item.item_id, item.field, item.text)):
        if per_item_field_counts.get((row.item_id, row.field), 0) >= _field_quota(row.field):
            continue
        count = per_item_counts.get(row.item_id, 0)
        if count >= max_evidence_per_item:
            continue
        per_item_counts[row.item_id] = count + 1
        per_item_field_counts[(row.item_id, row.field)] = per_item_field_counts.get((row.item_id, row.field), 0) + 1
        limited.append(row)
    return limited


def _field_quota(field_name: str) -> int:
    return int(RAG_EVIDENCE_FIELD_QUOTAS.get(field_name, 10_000))


def _field_weight(field_name: str) -> float:
    return float(RAG_DEFAULT_FIELD_WEIGHTS.get(field_name, 1.0))


def _loads(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
