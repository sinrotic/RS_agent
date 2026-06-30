from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.data.vectorstores.build_utils import created_at_utc, write_manifest_if_requested  # noqa: E402
from rs_core.data.vectorstores.milvus_client import PRIMARY_KEY_FIELD, VECTOR_FIELD, build_milvus_client  # noqa: E402
from rs_core.data.vectorstores.milvus_contracts import (  # noqa: E402
    DEFAULT_MILVUS_METRIC_TYPE,
    DEFAULT_MILVUS_RAG_CHUNK_COLLECTION,
    MilvusCollectionSpec,
)
from rs_core.data.vectorstores.milvus_client import MilvusVectorStore  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Copy a Milvus collection from one URI to another by scanning source rows.")
    parser.add_argument("--source-uri", required=True, help="Source Milvus URI, e.g. a Milvus Lite .db file.")
    parser.add_argument("--target-uri", required=True, help="Target Milvus URI, e.g. http://localhost:19530.")
    parser.add_argument("--collection-name", default=DEFAULT_MILVUS_RAG_CHUNK_COLLECTION)
    parser.add_argument("--target-collection-name", default=None, help="Defaults to --collection-name.")
    parser.add_argument("--source-token", default=None)
    parser.add_argument("--target-token", default=None)
    parser.add_argument("--source-db-name", default=None)
    parser.add_argument("--target-db-name", default=None)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=None, help="Optional smoke limit. Omit for full copy.")
    parser.add_argument("--drop-target", action="store_true", help="Drop the target collection before copying.")
    parser.add_argument("--manifest", default=None, help="Optional output manifest path.")
    return parser


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive when provided")

    target_collection = args.target_collection_name or args.collection_name
    source_client = build_milvus_client(uri=args.source_uri, token=args.source_token, db_name=args.source_db_name, timeout=args.timeout)
    target_client = build_milvus_client(uri=args.target_uri, token=args.target_token, db_name=args.target_db_name, timeout=args.timeout)
    target_store = MilvusVectorStore(target_client)

    if args.drop_target and target_client.has_collection(collection_name=target_collection):
        target_client.drop_collection(collection_name=target_collection)

    source_description = source_client.describe_collection(args.collection_name)
    vector_size, metric_type, scalar_fields = _collection_spec_from_description(source_description)
    if vector_size is None:
        raise ValueError(f"source collection {args.collection_name!r} does not expose vector dimension")
    target_store.ensure_collection(
        MilvusCollectionSpec(
            collection_name=target_collection,
            vector_size=vector_size,
            metric_type=metric_type or DEFAULT_MILVUS_METRIC_TYPE,
            scalar_fields=tuple(scalar_fields),
        )
    )

    if hasattr(source_client, "load_collection"):
        source_client.load_collection(collection_name=args.collection_name)

    copied = 0
    iterator = source_client.query_iterator(
        collection_name=args.collection_name,
        batch_size=int(args.batch_size),
        output_fields=_output_fields(scalar_fields),
    )
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            rows = [dict(row) for row in batch]
            if args.limit is not None:
                rows = rows[: max(0, args.limit - copied)]
            if rows:
                target_client.upsert(collection_name=target_collection, data=rows)
                copied += len(rows)
            if args.limit is not None and copied >= args.limit:
                break
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()

    _safe_flush(target_client, target_collection)
    target_stats = _safe_collection_stats(target_client, target_collection)
    manifest = {
        "schema_version": "milvus_collection_copy_manifest_v1",
        "created_at": created_at_utc(),
        "source_backend": "milvus",
        "target_backend": "milvus",
        "source_uri_kind": _uri_kind(args.source_uri),
        "target_uri_kind": _uri_kind(args.target_uri),
        "source_collection_name": args.collection_name,
        "target_collection_name": target_collection,
        "vector_size": vector_size,
        "metric_type": metric_type or DEFAULT_MILVUS_METRIC_TYPE,
        "scalar_fields": list(scalar_fields),
        "copied_row_count": copied,
        "limit": args.limit,
        "target_stats": target_stats,
    }
    write_manifest_if_requested(args.manifest, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def _collection_spec_from_description(description: Any) -> tuple[int | None, str | None, list[str]]:
    fields = _get(description, "fields") or _get(_get(description, "schema"), "fields") or []
    vector_size: int | None = None
    scalar_fields: list[str] = []
    for field in fields:
        name = _get(field, "name") or _get(field, "field_name")
        if not name or name == PRIMARY_KEY_FIELD:
            continue
        if name == VECTOR_FIELD:
            params = _get(field, "params") or {}
            dim = _get(params, "dim") or _get(field, "dim")
            vector_size = int(dim) if dim is not None else None
        else:
            scalar_fields.append(str(name))
    metric_type = None
    indexes = _get(description, "indexes") or _get(description, "index_descriptions") or []
    for index in indexes:
        params = _get(index, "params") or _get(index, "index_param") or index
        metric_type = _get(params, "metric_type") or _get(index, "metric_type")
        if metric_type:
            break
    return vector_size, str(metric_type) if metric_type else None, scalar_fields


def _output_fields(scalar_fields: list[str]) -> list[str]:
    dynamic_fields = [
        "field",
        "text",
        "source",
        "corpus_scope",
        "chunk_index",
        "embedding_method",
        "embedding_model_name",
        "artifact_scope",
        "ranking_input_replacement_allowed",
        "promotion_allowed",
    ]
    return [PRIMARY_KEY_FIELD, VECTOR_FIELD, *scalar_fields, *dynamic_fields]


def _safe_flush(client: Any, collection_name: str) -> None:
    try:
        client.flush(collection_name=collection_name)
    except TypeError:
        client.flush(collection_name)
    except Exception:
        return


def _safe_collection_stats(client: Any, collection_name: str) -> dict[str, Any]:
    try:
        return dict(client.get_collection_stats(collection_name=collection_name))
    except Exception:
        return {}


def _uri_kind(uri: str) -> str:
    value = str(uri)
    if value.startswith(("http://", "https://")):
        return "server"
    if value.endswith(".db"):
        return "milvus_lite_db"
    return "path"


def _get(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


if __name__ == "__main__":
    main()
