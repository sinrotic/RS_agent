from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.common.elasticsearch_config import elasticsearch_config_from_args, merge_elasticsearch_config
from rs_core.common.io import iter_jsonl, read_json, write_json
from rs_core.data.clients import DataClient, KnowledgeDataClient
from rs_core.agent.rag import (
    DEFAULT_ELASTICSEARCH_BM25_INDEX,
    DEFAULT_RAG_CORPUS_SCOPE,
    RAG_RETRIEVAL_SCOPE,
    RAG_STANDARD_FIELDS,
    build_elasticsearch_client,
    bulk_index_elasticsearch_documents,
    ensure_elasticsearch_bm25_index,
    iter_elasticsearch_documents,
)
from rs_core.agent.rag.build_utils import contains_forbidden_token, manifest_token_sources, reject_forbidden_path

DEFAULT_FIELDS = RAG_STANDARD_FIELDS


def build_rag_elasticsearch_bm25_index(
    *,
    items_path: str | Path,
    index_name: str = DEFAULT_ELASTICSEARCH_BM25_INDEX,
    manifest_path: str | Path | None = None,
    elasticsearch_config: dict[str, Any] | None = None,
    fields: list[str] | None = None,
    max_chunk_chars: int = 400,
    batch_size: int = 500,
    limit_items: int | None = None,
    source_manifest_path: str | Path | None = None,
    legacy_sqlite_bm25_index_path: str | Path | None = None,
    corpus_scope: str = DEFAULT_RAG_CORPUS_SCOPE,
    mode: str = "dry-run",
    drop_index: bool = False,
    refresh: bool = False,
    confirm_full_import: bool = False,
) -> dict[str, Any]:
    mode = _normalize_mode(mode)
    if mode == "full" and not confirm_full_import:
        raise ValueError("full Elasticsearch BM25 import requires --confirm-full-import")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    item_file = _resolve_path(items_path)
    if not item_file.is_file():
        raise FileNotFoundError(str(item_file))
    reject_forbidden_path(item_file, "items_path")
    source_manifest_file = _resolve_path(source_manifest_path) if source_manifest_path else None
    if source_manifest_file and not source_manifest_file.is_file():
        raise FileNotFoundError(str(source_manifest_file))
    if source_manifest_file:
        _validate_source_manifest(source_manifest_file, require_governance=mode != "dry-run")
    elif mode != "dry-run":
        raise ValueError("non-dry-run Elasticsearch BM25 build requires --source-manifest for provenance validation")

    selected_fields = list(fields or DEFAULT_FIELDS)
    effective_limit = limit_items
    if mode == "smoke" and effective_limit is None:
        effective_limit = 100
    index_build_id = f"rag-elasticsearch-bm25-{uuid4().hex}"
    items = _limited_items(item_file, effective_limit)
    documents = iter_elasticsearch_documents(
        items,
        fields=selected_fields,
        max_chunk_chars=max_chunk_chars,
        corpus_scope=corpus_scope,
        index_build_id=index_build_id,
    )

    item_row_count = 0
    indexed_item_ids: set[str] = set()
    chunk_count = 0
    indexed_chunk_count = 0
    if mode == "dry-run":
        for document in documents:
            chunk_count += 1
            indexed_item_ids.add(str(document.get("item_id") or ""))
        item_row_count = _count_items(item_file, effective_limit)
    else:
        config = merge_elasticsearch_config(elasticsearch_config or {}, {"index_name": index_name})
        client = build_elasticsearch_client(config)
        ensure_elasticsearch_bm25_index(client, index_name=index_name, drop_index=drop_index)

        def counted_documents():
            nonlocal chunk_count, indexed_chunk_count
            for document in documents:
                chunk_count += 1
                indexed_chunk_count += 1
                indexed_item_ids.add(str(document.get("item_id") or ""))
                yield document

        indexed_chunk_count, error_count = bulk_index_elasticsearch_documents(
            client,
            index_name=index_name,
            documents=counted_documents(),
            batch_size=batch_size,
            refresh=refresh,
        )
        if error_count:
            raise RuntimeError(f"Elasticsearch BM25 bulk indexing reported {error_count} errors")
        item_row_count = _count_items(item_file, effective_limit)

    knowledge_artifact = KnowledgeDataClient(DataClient(project_root=ROOT)).elasticsearch_rag_index_artifact(
        index_name,
        metadata={
            "candidate_scoped": True,
            "schema_version": "rag_elasticsearch_bm25_index_v1",
        },
    )
    manifest = {
        "schema_version": "rag_elasticsearch_bm25_index_v1",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "data_client": "KnowledgeDataClient",
        "knowledge_artifact": knowledge_artifact.to_dict(),
        "backend": "elasticsearch",
        "retriever": "elasticsearch_bm25",
        "index_name": str(index_name),
        "items_path": str(item_file),
        "source_manifest_path": str(source_manifest_file) if source_manifest_file else None,
        "legacy_sqlite_bm25_index_path": str(_resolve_path(legacy_sqlite_bm25_index_path)) if legacy_sqlite_bm25_index_path else None,
        "fields": selected_fields,
        "max_chunk_chars": int(max_chunk_chars),
        "item_row_count": item_row_count,
        "indexed_item_count": len({item_id for item_id in indexed_item_ids if item_id}),
        "chunk_count": chunk_count,
        "indexed_chunk_count": indexed_chunk_count,
        "mode": mode,
        "limit_items": effective_limit,
        "index_build_id": index_build_id,
        "corpus_scope": corpus_scope,
        "retrieval_scope": RAG_RETRIEVAL_SCOPE,
        "artifact_role": "rag_evidence",
        "knowledge_base_role": "rag_evidence",
        "candidate_scoped": True,
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "no_holdout": True,
        "build_policy": {
            "default_mode": "dry-run",
            "smoke_allowed": True,
            "full_index_allowed_by_default": False,
            "full_index_requires_confirm_full_import": True,
            "local_memory_cap_gb": 12,
        },
    }
    if manifest_path:
        write_json(_resolve_path(manifest_path), manifest)
    return manifest


def _limited_items(path: Path, limit_items: int | None):
    count = 0
    for item in iter_jsonl(path):
        if limit_items is not None and count >= limit_items:
            break
        count += 1
        yield item


def _count_items(path: Path, limit_items: int | None) -> int:
    count = 0
    for _item in iter_jsonl(path):
        if limit_items is not None and count >= limit_items:
            break
        count += 1
    return count


def _validate_source_manifest(path: Path, *, require_governance: bool) -> None:
    manifest = read_json(path)
    reject_forbidden_path(path, "source_manifest_path")
    if require_governance and (manifest.get("no_holdout") is not True or manifest.get("train_only") is not True):
        raise ValueError("RAG Elasticsearch BM25 source manifest must explicitly set train_only=true and no_holdout=true")
    for token_source in manifest_token_sources(manifest):
        if contains_forbidden_token(token_source):
            raise ValueError("RAG Elasticsearch BM25 source manifest references forbidden holdout/evaluation fields or paths")


def _resolve_path(path: str | Path | None) -> Path:
    if path is None:
        raise ValueError("path is required")
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def _normalize_mode(value: str) -> str:
    mode = str(value).strip().lower()
    if mode in {"dry_run", "dryrun"}:
        return "dry-run"
    if mode not in {"dry-run", "smoke", "full"}:
        raise ValueError(f"unsupported mode: {value}")
    return mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an Elasticsearch BM25 RAG index from item JSONL.")
    parser.add_argument("--items", required=True, help="Item JSONL path, e.g. data/processed/.../canonical_items.jsonl")
    parser.add_argument("--index-name", default=DEFAULT_ELASTICSEARCH_BM25_INDEX)
    parser.add_argument("--manifest", help="Output manifest path")
    parser.add_argument("--fields", nargs="+", default=DEFAULT_FIELDS, help="Item fields to chunk and index")
    parser.add_argument("--max-chunk-chars", type=int, default=400)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit-items", type=int)
    parser.add_argument("--source-manifest", help="Recent-window dataset manifest used to build this RAG catalog index")
    parser.add_argument("--legacy-sqlite-bm25-index")
    parser.add_argument("--corpus-scope", default=DEFAULT_RAG_CORPUS_SCOPE)
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "smoke", "full"])
    parser.add_argument("--drop-index", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--confirm-full-import", action="store_true")
    parser.add_argument("--elasticsearch-uri")
    parser.add_argument("--elasticsearch-username")
    parser.add_argument("--elasticsearch-password")
    parser.add_argument("--elasticsearch-api-key")
    parser.add_argument("--elasticsearch-timeout", type=int)
    args = parser.parse_args()
    manifest = build_rag_elasticsearch_bm25_index(
        items_path=args.items,
        index_name=args.index_name,
        manifest_path=args.manifest,
        elasticsearch_config=elasticsearch_config_from_args(args),
        fields=list(args.fields),
        max_chunk_chars=args.max_chunk_chars,
        batch_size=args.batch_size,
        limit_items=args.limit_items,
        source_manifest_path=args.source_manifest,
        legacy_sqlite_bm25_index_path=args.legacy_sqlite_bm25_index,
        corpus_scope=args.corpus_scope,
        mode=args.mode,
        drop_index=args.drop_index,
        refresh=args.refresh,
        confirm_full_import=args.confirm_full_import,
    )
    print(f"prepared {manifest['chunk_count']} chunks for {manifest['indexed_item_count']} items -> {manifest['index_name']} ({manifest['mode']})")


if __name__ == "__main__":
    main()
