from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_MANIFEST = ROOT / "outputs/agent/rag/recent_window_compact_full/rag_elasticsearch_bm25_full_import_manifest.json"
DEFAULT_ES_URL = "http://localhost:9200"
DEFAULT_INDEX = "rs_agent_rag_bm25_v1"
DEFAULT_BATCH_DOCS = 5000
DEFAULT_BATCH_BYTES = 8 * 1024 * 1024


ELASTICSEARCH_BM25_INDEX_BODY = {
    "settings": {
        "index": {
            "number_of_replicas": 0,
            "refresh_interval": "-1",
        }
    },
    "mappings": {
        "dynamic": "false",
        "properties": {
            "chunk_id": {"type": "keyword"},
            "item_id": {"type": "keyword"},
            "field": {"type": "keyword"},
            "text": {"type": "text"},
            "source": {"type": "keyword"},
            "corpus_scope": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "schema_version": {"type": "keyword"},
            "index_build_id": {"type": "keyword"},
            "artifact_scope": {"type": "keyword"},
            "candidate_generation_allowed": {"type": "boolean"},
            "ranking_input_replacement_allowed": {"type": "boolean"},
            "promotion_allowed": {"type": "boolean"},
            "no_holdout": {"type": "boolean"},
            "metadata": {"type": "object", "enabled": False},
        },
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate an existing SQLite RAG BM25 index into Elasticsearch.")
    parser.add_argument("--sqlite-index", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--output-manifest", type=Path, default=DEFAULT_OUTPUT_MANIFEST)
    parser.add_argument("--elasticsearch-uri", default=DEFAULT_ES_URL)
    parser.add_argument("--index-name", default=DEFAULT_INDEX)
    parser.add_argument("--batch-docs", type=int, default=DEFAULT_BATCH_DOCS)
    parser.add_argument("--batch-bytes", type=int, default=DEFAULT_BATCH_BYTES)
    parser.add_argument("--limit", type=int, help="Optional row limit for smoke runs.")
    parser.add_argument("--drop-index", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--corpus-scope", default="train_catalog_rag")
    parser.add_argument("--index-build-id", default="sqlite-bm25-to-elasticsearch-full-20260628")
    parser.add_argument("--progress-every", type=int, default=100_000)
    args = parser.parse_args()

    sqlite_path = _resolve_path(args.sqlite_index)
    source_manifest_path = _resolve_path(args.source_manifest) if args.source_manifest else None
    output_manifest_path = _resolve_path(args.output_manifest)
    if not sqlite_path.is_file():
        raise FileNotFoundError(str(sqlite_path))
    if args.batch_docs <= 0:
        raise ValueError("--batch-docs must be positive")
    if args.batch_bytes <= 0:
        raise ValueError("--batch-bytes must be positive")

    es = ElasticsearchHttpClient(args.elasticsearch_uri.rstrip("/"))
    print("elasticsearch_health", json.dumps(es.request("GET", "/_cluster/health"), ensure_ascii=False), flush=True)
    if es.exists(f"/{args.index_name}"):
        if not args.drop_index:
            raise RuntimeError(f"Elasticsearch index already exists: {args.index_name}; pass --drop-index to rebuild it")
        print(f"deleting_existing_index {args.index_name}", flush=True)
        es.request("DELETE", f"/{args.index_name}")
    es.request("PUT", f"/{args.index_name}", ELASTICSEARCH_BM25_INDEX_BODY)
    print(f"created_index {args.index_name}", flush=True)

    started_at = time.time()
    with sqlite3.connect(str(sqlite_path)) as conn:
        conn.row_factory = sqlite3.Row
        total_chunks = _count_rows(conn, args.limit)
        total_items = _count_items(conn, args.limit)
        print(f"source chunks={total_chunks} items={total_items} limit={args.limit}", flush=True)
        indexed_chunks, indexed_items = _stream_rows_to_elasticsearch(
            conn,
            es,
            index_name=args.index_name,
            corpus_scope=args.corpus_scope,
            index_build_id=args.index_build_id,
            batch_docs=args.batch_docs,
            batch_bytes=args.batch_bytes,
            progress_every=args.progress_every,
            total_chunks=total_chunks,
            limit=args.limit,
        )

    if args.refresh:
        es.request("PUT", f"/{args.index_name}/_settings", {"index": {"refresh_interval": "1s"}})
        es.request("POST", f"/{args.index_name}/_refresh")
    count = int(es.request("GET", f"/{args.index_name}/_count").get("count", 0))
    elapsed = time.time() - started_at
    manifest = {
        "schema_version": "rag_elasticsearch_bm25_index_v1",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "backend": "elasticsearch",
        "retriever": "elasticsearch_bm25",
        "index_name": args.index_name,
        "source_backend": "sqlite_bm25",
        "source_sqlite_bm25_index_path": str(sqlite_path),
        "source_sqlite_bm25_manifest_path": str(source_manifest_path) if source_manifest_path else None,
        "source_chunk_count": total_chunks,
        "source_item_count": total_items,
        "streamed_chunk_count": indexed_chunks,
        "streamed_item_count": len(indexed_items),
        "indexed_chunk_count": count,
        "corpus_scope": args.corpus_scope,
        "index_build_id": args.index_build_id,
        "candidate_scoped": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "no_holdout": True,
        "limit": args.limit,
        "storage": {
            "docker_service": "elasticsearch",
            "bind_mount": "db/elasticsearch:/usr/share/elasticsearch/data",
        },
        "elapsed_seconds": round(elapsed, 3),
    }
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("completed", json.dumps(manifest, ensure_ascii=False), flush=True)


def _stream_rows_to_elasticsearch(
    conn: sqlite3.Connection,
    es: "ElasticsearchHttpClient",
    *,
    index_name: str,
    corpus_scope: str,
    index_build_id: str,
    batch_docs: int,
    batch_bytes: int,
    progress_every: int,
    total_chunks: int,
    limit: int | None,
) -> tuple[int, set[str]]:
    started_at = time.time()
    indexed_chunks = 0
    indexed_items: set[str] = set()
    bulk_lines: list[str] = []
    bulk_docs = 0
    bulk_bytes = 0

    def flush() -> None:
        nonlocal bulk_lines, bulk_docs, bulk_bytes
        if not bulk_lines:
            return
        payload = ("\n".join(bulk_lines) + "\n").encode("utf-8")
        response = es.request("POST", "/_bulk", payload, content_type="application/x-ndjson", timeout=300)
        if response.get("errors"):
            errors = []
            for item in response.get("items", []):
                result = item.get("index") if isinstance(item, dict) else None
                if isinstance(result, dict) and result.get("error"):
                    errors.append(result["error"])
                    if len(errors) >= 3:
                        break
            raise RuntimeError(f"Elasticsearch bulk indexing errors: {errors}")
        bulk_lines = []
        bulk_docs = 0
        bulk_bytes = 0

    query = "SELECT chunk_id, item_id, field, text, source, metadata_json FROM rag_chunks"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    for row in conn.execute(query):
        metadata = _metadata(row["metadata_json"])
        doc = {
            "chunk_id": str(row["chunk_id"]),
            "item_id": str(row["item_id"]),
            "field": str(row["field"]),
            "text": str(row["text"]),
            "source": str(row["source"] or "catalog_bm25"),
            "corpus_scope": corpus_scope,
            "chunk_index": int(metadata.get("chunk_index", 0) or 0),
            "schema_version": "rag_elasticsearch_bm25_chunk_v1",
            "index_build_id": index_build_id,
            "artifact_scope": "candidate_internal",
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
            "no_holdout": True,
            "metadata": metadata,
        }
        action_line = json.dumps({"index": {"_index": index_name, "_id": doc["chunk_id"]}}, ensure_ascii=False, separators=(",", ":"))
        doc_line = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        bulk_lines.extend([action_line, doc_line])
        bulk_docs += 1
        bulk_bytes += len(action_line.encode("utf-8")) + len(doc_line.encode("utf-8")) + 2
        indexed_chunks += 1
        indexed_items.add(doc["item_id"])
        if bulk_docs >= batch_docs or bulk_bytes >= batch_bytes:
            flush()
        if progress_every > 0 and indexed_chunks % progress_every == 0:
            elapsed = time.time() - started_at
            rate = indexed_chunks / elapsed if elapsed > 0 else 0.0
            print(
                f"progress indexed={indexed_chunks}/{total_chunks} pct={indexed_chunks / max(total_chunks, 1):.2%} "
                f"items_seen={len(indexed_items)} rate={rate:.0f}/s elapsed_min={elapsed / 60:.1f}",
                flush=True,
            )
    flush()
    return indexed_chunks, indexed_items


class ElasticsearchHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def exists(self, path: str) -> bool:
        request = urllib.request.Request(self.base_url + path, method="HEAD")
        try:
            urllib.request.urlopen(request, timeout=30).close()
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise

    def request(self, method: str, path: str, body: object | bytes | None = None, *, content_type: str = "application/json", timeout: int = 120) -> dict[str, Any]:
        data = None
        headers = {}
        if body is not None:
            if isinstance(body, bytes):
                data = body
            else:
                data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))


def _count_rows(conn: sqlite3.Connection, limit: int | None) -> int:
    if limit is not None:
        return int(conn.execute("SELECT count(*) FROM (SELECT 1 FROM rag_chunks LIMIT ?)", (int(limit),)).fetchone()[0])
    return int(conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0])


def _count_items(conn: sqlite3.Connection, limit: int | None) -> int:
    if limit is not None:
        return int(conn.execute("SELECT count(DISTINCT item_id) FROM (SELECT item_id FROM rag_chunks LIMIT ?)", (int(limit),)).fetchone()[0])
    return int(conn.execute("SELECT count(DISTINCT item_id) FROM rag_chunks").fetchone()[0])


def _metadata(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path).resolve()


if __name__ == "__main__":
    main()
