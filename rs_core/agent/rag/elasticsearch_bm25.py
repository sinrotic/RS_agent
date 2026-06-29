from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from rs_core.common.elasticsearch_config import compact_elasticsearch_config
from rs_core.agent.rag.chunking import DEFAULT_RAG_FIELDS, RagItemChunk, chunk_item_record
from rs_core.agent.rag.corpus import RAG_DEFAULT_FIELD_WEIGHTS, RAG_EVIDENCE_FIELD_QUOTAS, RAG_STANDARD_FIELDS
from rs_core.agent.rag.schema import RagEvidence

ELASTICSEARCH_BM25_RETRIEVER = "elasticsearch_bm25"
ELASTICSEARCH_BM25_QUERY_PLANNING_RETRIEVER = "elasticsearch_bm25_query_planning"
ELASTICSEARCH_BM25_SCHEMA_VERSION = "rag_elasticsearch_bm25_chunk_v1"
DEFAULT_ELASTICSEARCH_BM25_INDEX = "rs_agent_rag_bm25_v1"


class ElasticsearchBM25Unavailable(RuntimeError):
    pass


@dataclass
class ElasticsearchBM25CandidateRetriever:
    config: Mapping[str, Any] | None = None
    client: Any | None = None
    fields: Iterable[str] | None = None

    def retrieve(
        self,
        query: str,
        candidate_item_ids: Iterable[str],
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        candidate_ids = [str(item_id) for item_id in candidate_item_ids if str(item_id)]
        if not query or not candidate_ids:
            return []
        config = compact_elasticsearch_config(dict(self.config or {}))
        index_name = _index_name(config)
        client = self.client or build_elasticsearch_client(config)
        limit = max(len(candidate_ids) * max(max_evidence_per_item, 1) * 8, 50)
        response = client.search(
            index=index_name,
            size=limit,
            query=elasticsearch_candidate_query(query, candidate_ids, fields=self.fields),
            source=True,
        )
        evidence = [_hit_to_evidence(hit, retriever=ELASTICSEARCH_BM25_RETRIEVER) for hit in _response_hits(response)]
        return _limit_evidence([row for row in evidence if row.field in RAG_STANDARD_FIELDS], max_evidence_per_item)


@dataclass
class ElasticsearchBM25QueryPlanningRetriever:
    config: Mapping[str, Any] | None = None
    client: Any | None = None
    fields: Iterable[str] | None = None

    def retrieve(
        self,
        query: str,
        max_evidence_total: int = 12,
        max_evidence_per_item: int = 3,
    ) -> list[RagEvidence]:
        if not query:
            return []
        config = compact_elasticsearch_config(dict(self.config or {}))
        index_name = _index_name(config)
        client = self.client or build_elasticsearch_client(config)
        limit = max(max(max_evidence_total, 1) * max(max_evidence_per_item, 1) * 4, 50)
        response = client.search(
            index=index_name,
            size=limit,
            query=elasticsearch_query_planning_query(query, fields=self.fields),
            source=True,
        )
        evidence = [
            _hit_to_evidence(
                hit,
                retriever=ELASTICSEARCH_BM25_QUERY_PLANNING_RETRIEVER,
                extra_metadata={
                    "retrieval_scope": "query_planning",
                    "candidate_generation_allowed": False,
                    "ranking_input_replacement_allowed": False,
                    "promotion_allowed": False,
                },
            )
            for hit in _response_hits(response)
        ]
        return _limit_evidence([row for row in evidence if row.field in RAG_STANDARD_FIELDS], max_evidence_per_item)[:max_evidence_total]


def build_elasticsearch_client(config: Mapping[str, Any] | None = None) -> Any:
    try:
        from elasticsearch import Elasticsearch
    except ImportError as exc:  # pragma: no cover - depends on optional dependency state
        raise ElasticsearchBM25Unavailable(
            "elasticsearch is required for Elasticsearch BM25 RAG backends; install the optional elasticsearch dependency before enabling this backend."
        ) from exc
    source = compact_elasticsearch_config(dict(config or {}))
    uri = source.get("uri") or source.get("url")
    hosts = source.get("hosts") or ([uri] if uri else None)
    kwargs: dict[str, Any] = {}
    if source.get("api_key"):
        kwargs["api_key"] = source["api_key"]
    elif source.get("username") or source.get("password"):
        kwargs["basic_auth"] = (str(source.get("username") or ""), str(source.get("password") or ""))
    timeout = source.get("timeout") or source.get("request_timeout")
    if timeout:
        kwargs["request_timeout"] = int(timeout)
    if "verify_certs" in source:
        kwargs["verify_certs"] = bool(source["verify_certs"])
    if not hosts:
        raise ElasticsearchBM25Unavailable("Elasticsearch BM25 backend requires uri/url/hosts config")
    return Elasticsearch(hosts=hosts, **kwargs)


def elasticsearch_bm25_mapping() -> dict[str, Any]:
    return {
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
    }


def elasticsearch_candidate_query(query: str, candidate_item_ids: Iterable[str], fields: Iterable[str] | None = None) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [
        {"terms": {"item_id": [str(item_id) for item_id in candidate_item_ids if str(item_id)]}},
        {"term": {"candidate_generation_allowed": False}},
        {"term": {"ranking_input_replacement_allowed": False}},
        {"term": {"promotion_allowed": False}},
        {"term": {"no_holdout": True}},
    ]
    selected_fields = [str(field) for field in fields or [] if str(field)]
    if selected_fields:
        filters.append({"terms": {"field": selected_fields}})
    return {"bool": {"must": [{"match": {"text": query}}], "filter": filters}}


def elasticsearch_query_planning_query(query: str, fields: Iterable[str] | None = None) -> dict[str, Any]:
    filters: list[dict[str, Any]] = [
        {"term": {"candidate_generation_allowed": False}},
        {"term": {"ranking_input_replacement_allowed": False}},
        {"term": {"promotion_allowed": False}},
        {"term": {"no_holdout": True}},
    ]
    selected_fields = [str(field) for field in fields or [] if str(field)]
    if selected_fields:
        filters.append({"terms": {"field": selected_fields}})
    return {"bool": {"must": [{"match": {"text": query}}], "filter": filters}}


def elasticsearch_document_for_chunk(
    chunk: RagItemChunk,
    *,
    chunk_id: str,
    corpus_scope: str,
    index_build_id: str,
    schema_version: str = ELASTICSEARCH_BM25_SCHEMA_VERSION,
) -> dict[str, Any]:
    metadata = dict(chunk.metadata)
    chunk_index = int(metadata.get("chunk_index", 0) or 0)
    return {
        "chunk_id": str(chunk_id),
        "item_id": str(chunk.item_id),
        "field": str(chunk.field),
        "text": str(chunk.text),
        "source": str(chunk.source or "catalog_bm25"),
        "corpus_scope": str(corpus_scope),
        "chunk_index": chunk_index,
        "schema_version": schema_version,
        "index_build_id": str(index_build_id),
        "artifact_scope": "candidate_internal",
        "candidate_generation_allowed": False,
        "ranking_input_replacement_allowed": False,
        "promotion_allowed": False,
        "no_holdout": True,
        "metadata": metadata,
    }


def iter_elasticsearch_documents(
    items: Iterable[dict[str, Any]],
    *,
    fields: Iterable[str] | None = None,
    max_chunk_chars: int = 400,
    corpus_scope: str = "train_catalog_rag",
    index_build_id: str = "rag-elasticsearch-bm25",
) -> Iterator[dict[str, Any]]:
    selected_fields = fields or DEFAULT_RAG_FIELDS
    chunk_counter = 0
    for item in items:
        for chunk in chunk_item_record(item, fields=selected_fields, max_chunk_chars=max_chunk_chars, source="catalog_bm25"):
            chunk_id = f"{chunk.item_id}:{chunk_counter}"
            yield elasticsearch_document_for_chunk(
                chunk,
                chunk_id=chunk_id,
                corpus_scope=corpus_scope,
                index_build_id=index_build_id,
            )
            chunk_counter += 1


def bulk_index_elasticsearch_documents(
    client: Any,
    *,
    index_name: str,
    documents: Iterable[dict[str, Any]],
    batch_size: int = 500,
    refresh: bool = False,
) -> tuple[int, int]:
    try:
        from elasticsearch import helpers
    except ImportError as exc:  # pragma: no cover - depends on optional dependency state
        raise ElasticsearchBM25Unavailable("elasticsearch helpers are required for bulk indexing") from exc

    def actions() -> Iterator[dict[str, Any]]:
        for document in documents:
            yield {"_index": index_name, "_id": document["chunk_id"], "_source": document}

    success, errors = helpers.bulk(client, actions(), chunk_size=int(batch_size), refresh=refresh, stats_only=True)
    return int(success), int(errors)


def ensure_elasticsearch_bm25_index(client: Any, *, index_name: str, drop_index: bool = False) -> None:
    exists = bool(client.indices.exists(index=index_name))
    if exists and drop_index:
        client.indices.delete(index=index_name)
        exists = False
    if not exists:
        client.indices.create(index=index_name, mappings=elasticsearch_bm25_mapping())


def _index_name(config: Mapping[str, Any]) -> str:
    value = config.get("index_name") or config.get("index") or config.get("alias")
    if not value:
        raise ElasticsearchBM25Unavailable("Elasticsearch BM25 backend requires index_name/index/alias config")
    return str(value)


def _response_hits(response: Any) -> list[dict[str, Any]]:
    if response is None:
        return []
    hits = _get(response, "hits")
    if isinstance(hits, Mapping):
        rows = hits.get("hits")
        return list(rows or []) if isinstance(rows, list) else []
    nested = _get(hits, "hits") if hits is not None else None
    return list(nested or []) if isinstance(nested, list) else []


def _hit_to_evidence(hit: Mapping[str, Any], *, retriever: str, extra_metadata: dict[str, Any] | None = None) -> RagEvidence:
    source = _get(hit, "_source") or _get(hit, "source") or {}
    score = float(_get(hit, "_score") or 0.0)
    field_name = str(_get(source, "field") or "")
    field_weight = _field_weight(field_name)
    metadata = _loads(_get(source, "metadata"))
    metadata.update(
        {
            "retriever": retriever,
            "bm25_backend": "elasticsearch",
            "bm25_raw_score": score,
            "field_weight": field_weight,
            "weighted_score": score * field_weight,
            "artifact_scope": "candidate_internal",
            "candidate_generation_allowed": False,
            "ranking_input_replacement_allowed": False,
            "promotion_allowed": False,
        }
    )
    if extra_metadata:
        metadata.update(extra_metadata)
    return RagEvidence(
        item_id=str(_get(source, "item_id") or ""),
        field=field_name,
        text=str(_get(source, "text") or ""),
        source=str(_get(source, "source") or retriever),
        score=score * field_weight,
        metadata=metadata,
    )


def _limit_evidence(evidence: list[RagEvidence], max_evidence_per_item: int) -> list[RagEvidence]:
    per_item_counts: dict[str, int] = {}
    per_item_field_counts: dict[tuple[str, str], int] = {}
    limited: list[RagEvidence] = []
    for row in sorted(evidence, key=lambda item: (-(item.score or 0.0), item.item_id, item.field, item.text)):
        if not row.item_id or not row.text:
            continue
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


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _get(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    body = getattr(value, "body", None)
    if isinstance(body, Mapping):
        return body.get(key)
    return getattr(value, key, None)
