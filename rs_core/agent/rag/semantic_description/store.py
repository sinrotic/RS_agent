from __future__ import annotations

import json
import pickle
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rs_core.agent.rag.semantic_description.scoring import PreparedRecord, prepare_record

SEMANTIC_DESCRIPTION_INDEX_SCHEMA_VERSION = "semantic_description_sqlite_index_v1"
TOKENIZER_VERSION = "semantic_description_tokens_v1"
SQLITE_QUERY_BATCH_SIZE = 5_000


class SQLiteSemanticDescriptionStore:
    def __init__(self, index_path: str | Path) -> None:
        self.index_path = Path(index_path)
        self._conn: sqlite3.Connection | None = None
        self._column_cache: dict[str, set[str]] = {}

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()

    def load_query_buckets(self, query_tokens: set[str], *, per_token_limit: int) -> tuple[dict[str, list[str]], dict[str, int]]:
        if not query_tokens or not self.index_path.exists():
            return {}, {}
        placeholders = ",".join("?" for _ in query_tokens)
        sql = f"SELECT token, doc_freq, item_ids_json FROM semantic_postings WHERE token IN ({placeholders})"
        buckets: dict[str, list[str]] = {}
        doc_freq: dict[str, int] = {}
        rows = self._connection().execute(sql, list(query_tokens)).fetchall()
        for token, df, item_ids_json in rows:
            item_ids = json.loads(str(item_ids_json))
            if not isinstance(item_ids, list):
                continue
            token_text = str(token)
            doc_freq[token_text] = int(df)
            buckets[token_text] = [str(item_id) for item_id in item_ids[:per_token_limit]]
        return buckets, doc_freq

    def load_records(self, item_ids: set[str]) -> dict[str, dict[str, Any]]:
        ids = [str(item_id) for item_id in item_ids if str(item_id)]
        if not ids or not self.index_path.exists():
            return {}
        records: dict[str, dict[str, Any]] = {}
        conn = self._connection()
        for start in range(0, len(ids), SQLITE_QUERY_BATCH_SIZE):
            batch = ids[start : start + SQLITE_QUERY_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = conn.execute(
                f"SELECT item_id, record_json FROM semantic_records WHERE item_id IN ({placeholders})",
                batch,
            ).fetchall()
            for item_id, record_json in rows:
                record = json.loads(str(record_json))
                if isinstance(record, dict):
                    records[str(item_id)] = record
        return records

    def load_prepared_records(self, item_ids: set[str]) -> dict[str, PreparedRecord]:
        ids = [str(item_id) for item_id in item_ids if str(item_id)]
        if not ids or not self.index_path.exists():
            return {}
        prepared_records: dict[str, PreparedRecord] = {}
        conn = self._connection()
        if not self._table_has_column("semantic_records", "prepared_json"):
            return prepared_records
        has_display_columns = self._table_has_column("semantic_records", "title_clean")
        has_fast_payload = self._table_has_column("semantic_records", "prepared_fast_json")
        has_columnar_pickle = self._table_has_column("semantic_records", "prepared_columnar_pickle")
        has_columnar_payload = self._table_has_column("semantic_records", "field_counts_json")
        for start in range(0, len(ids), SQLITE_QUERY_BATCH_SIZE):
            batch = ids[start : start + SQLITE_QUERY_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            if has_display_columns:
                if has_columnar_pickle:
                    rows = conn.execute(
                        f"""
                        SELECT item_id, title_clean, main_category, categories_flat, prepared_columnar_pickle
                        FROM semantic_records
                        WHERE item_id IN ({placeholders})
                        """,
                        batch,
                    ).fetchall()
                    for item_id, title_clean, main_category, categories_flat, prepared_pickle in rows:
                        _add_pickle_prepared_record(
                            prepared_records,
                            item_id=item_id,
                            title_clean=title_clean,
                            main_category=main_category,
                            categories_flat=categories_flat,
                            prepared_pickle=prepared_pickle,
                        )
                    continue
                if has_columnar_payload:
                    rows = conn.execute(
                        f"""
                        SELECT item_id, title_clean, main_category, categories_flat,
                               field_counts_json, title_text, category_text, full_text
                        FROM semantic_records
                        WHERE item_id IN ({placeholders})
                        """,
                        batch,
                    ).fetchall()
                    for item_id, title_clean, main_category, categories_flat, field_counts_json, title_text, category_text, full_text in rows:
                        _add_columnar_prepared_record(
                            prepared_records,
                            item_id=item_id,
                            title_clean=title_clean,
                            main_category=main_category,
                            categories_flat=categories_flat,
                            field_counts_json=field_counts_json,
                            title_text=title_text,
                            category_text=category_text,
                            full_text=full_text,
                        )
                    continue
                if has_fast_payload:
                    rows = conn.execute(
                        f"""
                        SELECT item_id, title_clean, main_category, categories_flat, prepared_fast_json, prepared_json
                        FROM semantic_records
                        WHERE item_id IN ({placeholders})
                        """,
                        batch,
                    ).fetchall()
                    for item_id, title_clean, main_category, categories_flat, prepared_fast_json, prepared_json in rows:
                        _add_display_prepared_record(
                            prepared_records,
                            item_id=item_id,
                            title_clean=title_clean,
                            main_category=main_category,
                            categories_flat=categories_flat,
                            prepared_json=prepared_fast_json or prepared_json,
                        )
                    continue
                rows = conn.execute(
                    f"""
                    SELECT item_id, title_clean, main_category, categories_flat, prepared_json
                    FROM semantic_records
                    WHERE item_id IN ({placeholders})
                    """,
                    batch,
                ).fetchall()
                for item_id, title_clean, main_category, categories_flat, prepared_json in rows:
                    _add_display_prepared_record(
                        prepared_records,
                        item_id=item_id,
                        title_clean=title_clean,
                        main_category=main_category,
                        categories_flat=categories_flat,
                        prepared_json=prepared_json,
                    )
                continue
            rows = conn.execute(
                f"SELECT item_id, record_json, prepared_json FROM semantic_records WHERE item_id IN ({placeholders})",
                batch,
            ).fetchall()
            for item_id, record_json, prepared_json in rows:
                if not prepared_json:
                    continue
                record = json.loads(str(record_json))
                prepared_payload = json.loads(str(prepared_json))
                if isinstance(record, dict) and isinstance(prepared_payload, dict):
                    prepared_records[str(item_id)] = _prepared_record_from_payload(record, prepared_payload)
        return prepared_records

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.index_path)
        return self._conn

    def _table_has_column(self, table: str, column: str) -> bool:
        columns = self._column_cache.get(table)
        if columns is None:
            rows = self._connection().execute(f"PRAGMA table_info({table})").fetchall()
            columns = {str(row[1]) for row in rows}
            self._column_cache[table] = columns
        return column in columns


def build_sqlite_semantic_description_index(
    *,
    semantic_inputs_path: str | Path,
    inverted_index_path: str | Path,
    index_path: str | Path,
    manifest_path: str | Path | None = None,
    overwrite: bool = False,
    batch_size: int = 1000,
) -> dict[str, Any]:
    semantic_inputs_path = Path(semantic_inputs_path)
    inverted_index_path = Path(inverted_index_path)
    index_path = Path(index_path)
    manifest_path = Path(manifest_path) if manifest_path else index_path.with_suffix(index_path.suffix + ".manifest.json")
    if not semantic_inputs_path.is_file():
        raise FileNotFoundError(str(semantic_inputs_path))
    if not inverted_index_path.is_file():
        raise FileNotFoundError(str(inverted_index_path))
    if index_path.exists() and not overwrite:
        raise FileExistsError(f"index already exists: {index_path}")
    if manifest_path.exists() and not overwrite:
        raise FileExistsError(f"manifest already exists: {manifest_path}")

    index_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and index_path.exists():
        index_path.unlink()

    postings_count = 0
    records_count = 0
    with closing(sqlite3.connect(index_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _create_schema(conn)
        postings_rows: list[tuple[str, int, str]] = []
        with inverted_index_path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                token = str(row.get("token") or "").lower()
                if not token:
                    continue
                item_ids = row.get("parent_asins") or row.get("item_ids") or []
                if not isinstance(item_ids, list):
                    continue
                item_ids = [str(item_id) for item_id in item_ids]
                postings_rows.append((token, len(item_ids), json.dumps(item_ids, ensure_ascii=False, separators=(",", ":"))))
                postings_count += 1
                if len(postings_rows) >= batch_size:
                    _insert_postings(conn, postings_rows)
                    postings_rows.clear()
        if postings_rows:
            _insert_postings(conn, postings_rows)

        record_rows: list[tuple[str, str, str, str, str, str, str, str, str, str, str, bytes]] = []
        with semantic_inputs_path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                item_id = str(row.get("parent_asin") or row.get("item_id") or "")
                if not item_id:
                    continue
                prepared = prepare_record(row)
                record_rows.append(
                    (
                        item_id,
                        json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                        json.dumps(_prepared_record_payload(prepared), ensure_ascii=False, separators=(",", ":")),
                        str(row.get("title_clean") or ""),
                        str(row.get("main_category") or ""),
                        json.dumps(row.get("categories_flat"), ensure_ascii=False, separators=(",", ":")),
                        json.dumps(_prepared_record_fast_payload(prepared), ensure_ascii=False, separators=(",", ":")),
                        json.dumps({field: dict(counts) for field, counts in prepared.field_counts.items()}, ensure_ascii=False, separators=(",", ":")),
                        prepared.title_text,
                        prepared.category_text,
                        prepared.full_text,
                        _prepared_record_pickle(prepared),
                    )
                )
                records_count += 1
                if len(record_rows) >= batch_size:
                    _insert_records(conn, record_rows)
                    record_rows.clear()
        if record_rows:
            _insert_records(conn, record_rows)
        conn.commit()

    manifest = {
        "schema_version": SEMANTIC_DESCRIPTION_INDEX_SCHEMA_VERSION,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "semantic_inputs_path": str(semantic_inputs_path),
        "inverted_index_path": str(inverted_index_path),
        "index_path": str(index_path),
        "manifest_path": str(manifest_path),
        "postings_count": postings_count,
        "records_count": records_count,
        "tokenizer_version": TOKENIZER_VERSION,
        "postings_order_preserved": True,
        "record_json_preserved": True,
        "prepared_record_cached": True,
        "prepared_fast_record_cached": True,
        "prepared_columnar_record_cached": True,
        "prepared_pickle_record_cached": True,
        "display_columns_cached": True,
        "artifact_role": "live_semantic_description_retrieval_acceleration",
        "eval_scope": "train_metadata_description_retrieval_index",
        "label_inputs_role": "not_used",
        "oracle_label_injection": False,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "pool1000_allowed": False,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS semantic_postings;
        DROP TABLE IF EXISTS semantic_records;
        CREATE TABLE semantic_postings (
            token TEXT PRIMARY KEY,
            doc_freq INTEGER NOT NULL,
            item_ids_json TEXT NOT NULL
        );
        CREATE TABLE semantic_records (
            item_id TEXT PRIMARY KEY,
            record_json TEXT NOT NULL,
            prepared_json TEXT,
            title_clean TEXT,
            main_category TEXT,
            categories_flat TEXT,
            prepared_fast_json TEXT,
            field_counts_json TEXT,
            title_text TEXT,
            category_text TEXT,
            full_text TEXT,
            prepared_columnar_pickle BLOB
        );
        """
    )


def _insert_postings(conn: sqlite3.Connection, rows: list[tuple[str, int, str]]) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO semantic_postings(token, doc_freq, item_ids_json) VALUES (?, ?, ?)",
        rows,
    )


def _insert_records(conn: sqlite3.Connection, rows: list[tuple[str, str, str, str, str, str, str, str, str, str, str, bytes]]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO semantic_records(
            item_id, record_json, prepared_json, title_clean, main_category, categories_flat,
            prepared_fast_json, field_counts_json, title_text, category_text, full_text, prepared_columnar_pickle
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _prepared_record_payload(record: PreparedRecord) -> dict[str, Any]:
    return {
        "field_texts": record.field_texts,
        "field_terms": record.field_terms,
        "field_counts": {field: dict(counts) for field, counts in record.field_counts.items()},
        "title_text": record.title_text,
        "category_text": record.category_text,
        "full_text": record.full_text,
    }


def _prepared_record_fast_payload(record: PreparedRecord) -> dict[str, Any]:
    return {
        "field_counts": {field: dict(counts) for field, counts in record.field_counts.items()},
        "title_text": record.title_text,
        "category_text": record.category_text,
        "full_text": record.full_text,
    }


def _prepared_record_pickle(record: PreparedRecord) -> bytes:
    return pickle.dumps(
        (
            {field: dict(counts) for field, counts in record.field_counts.items()},
            record.title_text,
            record.category_text,
            record.full_text,
        ),
        protocol=pickle.HIGHEST_PROTOCOL,
    )


def _add_display_prepared_record(
    prepared_records: dict[str, PreparedRecord],
    *,
    item_id: Any,
    title_clean: Any,
    main_category: Any,
    categories_flat: Any,
    prepared_json: Any,
) -> None:
    if not prepared_json:
        return
    prepared_payload = json.loads(str(prepared_json))
    if not isinstance(prepared_payload, dict):
        return
    record = _display_record(item_id, title_clean, main_category, categories_flat)
    prepared_records[str(item_id)] = _prepared_record_from_payload(record, prepared_payload)


def _add_pickle_prepared_record(
    prepared_records: dict[str, PreparedRecord],
    *,
    item_id: Any,
    title_clean: Any,
    main_category: Any,
    categories_flat: Any,
    prepared_pickle: Any,
) -> None:
    if not prepared_pickle:
        return
    field_counts_payload, title_text, category_text, full_text = pickle.loads(prepared_pickle)
    record = _display_record(item_id, title_clean, main_category, categories_flat)
    prepared_records[str(item_id)] = PreparedRecord(
        raw=record,
        field_texts={},
        field_terms={},
        field_counts={
            str(key): Counter({str(token): int(count) for token, count in value.items()})
            for key, value in field_counts_payload.items()
            if isinstance(value, dict)
        },
        title_text=str(title_text or ""),
        category_text=str(category_text or ""),
        full_text=str(full_text or ""),
    )


def _add_columnar_prepared_record(
    prepared_records: dict[str, PreparedRecord],
    *,
    item_id: Any,
    title_clean: Any,
    main_category: Any,
    categories_flat: Any,
    field_counts_json: Any,
    title_text: Any,
    category_text: Any,
    full_text: Any,
) -> None:
    if not field_counts_json:
        return
    field_counts_payload = json.loads(str(field_counts_json))
    if not isinstance(field_counts_payload, dict):
        return
    record = _display_record(item_id, title_clean, main_category, categories_flat)
    prepared_records[str(item_id)] = PreparedRecord(
        raw=record,
        field_texts={},
        field_terms={},
        field_counts={
            str(key): Counter({str(token): int(count) for token, count in value.items()})
            for key, value in field_counts_payload.items()
            if isinstance(value, dict)
        },
        title_text=str(title_text or ""),
        category_text=str(category_text or ""),
        full_text=str(full_text or ""),
    )


def _display_record(item_id: Any, title_clean: Any, main_category: Any, categories_flat: Any) -> dict[str, Any]:
    return {
        "parent_asin": str(item_id),
        "title_clean": title_clean,
        "main_category": main_category,
        "categories_flat": json.loads(str(categories_flat)) if categories_flat else None,
    }


def _prepared_record_from_payload(record: dict[str, Any], payload: dict[str, Any]) -> PreparedRecord:
    field_counts = {
        str(key): Counter({str(token): int(count) for token, count in value.items()})
        for key, value in (payload.get("field_counts") or {}).items()
        if isinstance(value, dict)
    }
    return PreparedRecord(
        raw=record,
        field_texts={str(key): str(value) for key, value in (payload.get("field_texts") or {}).items()},
        field_terms={str(key): [str(item) for item in value] for key, value in (payload.get("field_terms") or {}).items() if isinstance(value, list)},
        field_counts=field_counts,
        title_text=str(payload.get("title_text") or ""),
        category_text=str(payload.get("category_text") or ""),
        full_text=str(payload.get("full_text") or ""),
    )


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(row[1]) == column for row in rows)


__all__ = [
    "SEMANTIC_DESCRIPTION_INDEX_SCHEMA_VERSION",
    "TOKENIZER_VERSION",
    "SQLiteSemanticDescriptionStore",
    "build_sqlite_semantic_description_index",
]
