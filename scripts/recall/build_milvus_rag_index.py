from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rs_core.data.clients import DataClient, KnowledgeDataClient  # noqa: E402
from rs_core.agent.rag import DEFAULT_DENSE_MODEL_NAME, DEFAULT_RAG_CORPUS_SCOPE, build_milvus_rag_chunk_index  # noqa: E402
from rs_core.common.milvus_config import merge_milvus_config, milvus_config_from_args, milvus_config_from_env  # noqa: E402
from rs_core.data.adapters import MilvusAdapter  # noqa: E402
from rs_core.recsys.vectorstores.milvus_builders import add_milvus_connection_args  # noqa: E402
from rs_core.recsys.vectorstores.milvus_contracts import DEFAULT_MILVUS_RAG_CHUNK_COLLECTION  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a candidate-scoped Milvus RAG chunk collection from item JSONL.")
    parser.add_argument("--items", required=True, help="Item JSONL path, e.g. canonical_items.jsonl")
    parser.add_argument("--collection-name", default=DEFAULT_MILVUS_RAG_CHUNK_COLLECTION)
    parser.add_argument("--manifest", default=None, help="Output Milvus migration manifest path")
    parser.add_argument("--fields", nargs="+", default=None, help="Item fields to chunk and index")
    parser.add_argument("--max-chunk-chars", type=int, default=400)
    parser.add_argument("--embedding-model-name", default=DEFAULT_DENSE_MODEL_NAME)
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    parser.add_argument("--no-normalize-embeddings", action="store_true")
    parser.add_argument("--query-prefix", default="")
    parser.add_argument("--passage-prefix", default="")
    parser.add_argument("--corpus-scope", default=DEFAULT_RAG_CORPUS_SCOPE)
    parser.add_argument("--source-manifest", default=None)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--limit-items", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    add_milvus_connection_args(parser)
    return parser


def main(argv: list[str] | None = None) -> dict[str, object]:
    parser = build_parser()
    args = parser.parse_args(argv)
    milvus_config = MilvusAdapter.from_config(
        merge_milvus_config(milvus_config_from_env(), milvus_config_from_args(args)),
        enabled=True,
    ).connection_config()
    manifest = build_milvus_rag_chunk_index(
        items_path=args.items,
        collection_name=args.collection_name,
        milvus_config=milvus_config,
        fields=list(args.fields) if args.fields else None,
        max_chunk_chars=args.max_chunk_chars,
        embedding_model_name=args.embedding_model_name,
        embedding_batch_size=args.embedding_batch_size,
        normalize_embeddings=not args.no_normalize_embeddings,
        query_prefix=args.query_prefix,
        passage_prefix=args.passage_prefix,
        corpus_scope=args.corpus_scope,
        source_manifest_path=args.source_manifest,
        manifest_path=args.manifest,
        batch_size=args.batch_size,
        limit_items=args.limit_items,
        dry_run=args.dry_run,
    )
    knowledge_artifact = KnowledgeDataClient(DataClient(project_root=ROOT)).milvus_rag_collection_artifact(
        args.collection_name,
        metadata={"candidate_scoped": True},
    )
    manifest["data_client"] = "KnowledgeDataClient"
    manifest["knowledge_artifact"] = knowledge_artifact.to_dict()
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    main()
