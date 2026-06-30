from __future__ import annotations

from rs_core.agent.rag.bm25 import (
    SQLiteBM25CandidateRetriever,
    SQLiteBM25QueryPlanningRetriever,
    SQLiteBM25Unavailable,
    build_sqlite_bm25_index,
)
from rs_core.agent.rag.context import build_empty_rag_context
from rs_core.agent.rag.corpus import (
    RAG_COMPACT_DENSE_FIELD,
    RAG_PARENT_PROFILE_FIELD,
    RAG_STANDARD_FIELDS,
    build_compact_item_text,
    build_parent_profile_text,
    normalize_item_record,
)
from rs_core.agent.rag.elasticsearch_bm25 import (
    DEFAULT_ELASTICSEARCH_BM25_INDEX,
    ELASTICSEARCH_BM25_QUERY_PLANNING_RETRIEVER,
    ELASTICSEARCH_BM25_RETRIEVER,
    ELASTICSEARCH_BM25_SCHEMA_VERSION,
    ElasticsearchBM25CandidateRetriever,
    ElasticsearchBM25QueryPlanningRetriever,
    ElasticsearchBM25Unavailable,
    build_elasticsearch_client,
    bulk_index_elasticsearch_documents,
    elasticsearch_bm25_mapping,
    elasticsearch_candidate_query,
    elasticsearch_document_for_chunk,
    elasticsearch_query_planning_query,
    ensure_elasticsearch_bm25_index,
    iter_elasticsearch_documents,
)
from rs_core.agent.rag.hybrid import HybridCandidateRetriever, cosine_score, text_to_hashed_vector
from rs_core.agent.rag.milvus_index import build_milvus_rag_chunk_index
from rs_core.agent.rag.milvus_vector import MilvusCandidateRagVectorRetriever
from rs_core.agent.rag.retriever import (
    EvidencePolicyViolation,
    InMemoryCandidateCardRetriever,
    QueryPlanningEvidenceRetriever,
    RagPolicy,
    Small2BigCandidateEvidenceRetriever,
    build_query_rag_context_for_planning,
    build_rag_context_for_ranked_candidates,
    evidence_policy_violation_tokens,
    validate_parent_profile_manifest,
)
from rs_core.agent.rag.schema import RagContext, RagEvidence
from rs_core.agent.rag.vector_index import (
    DEFAULT_DENSE_MODEL_NAME,
    DEFAULT_RAG_CORPUS_SCOPE,
    LOCAL_TFIDF_VECTOR_METHOD,
    LOCAL_VECTOR_METHOD,
    RAG_RETRIEVAL_SCOPE,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    SentenceTransformerEmbeddingBackend,
    TextEmbeddingBackend,
    build_local_vector_index,
    load_local_vector_index,
)
from rs_core.agent.rag.semantic_description import *  # noqa: F403 - compatibility facade

# RagAgent lives in rs_core.agent.adapters.rag; keep these exports lazy so importing
# rs_core.agent.rag does not create an adapter -> RAG circular import.
_RAG_AGENT_EXPORTS = {
    "RAG_AGENT_POST_RANKING_STAGE",
    "RAG_AGENT_PRE_RETRIEVAL_STAGE",
    "RAG_AGENT_QUERY_SUPPORT_SCHEMA_VERSION",
    "RAG_AGENT_SUPPORT_SCHEMA_VERSION",
    "RAG_AGENT_SYSTEM_PROMPT",
    "RagAgentAdapter",
    "RagAgentConfig",
    "RagAgentInvocation",
    "RagAgentMessageEnvelope",
    "RagAgentQuerySupport",
    "RagAgentResponse",
    "RagAgentShadowReport",
    "RagAgentSupport",
    "RagQueryRewriteConfig",
    "RagQueryRewriteResult",
    "RagQueryRewriter",
}

__all__ = [
    *_RAG_AGENT_EXPORTS,
    "DEFAULT_DENSE_MODEL_NAME",
    "DEFAULT_RAG_CORPUS_SCOPE",
    "DEFAULT_ELASTICSEARCH_BM25_INDEX",
    "ELASTICSEARCH_BM25_QUERY_PLANNING_RETRIEVER",
    "ELASTICSEARCH_BM25_RETRIEVER",
    "ELASTICSEARCH_BM25_SCHEMA_VERSION",
    "ElasticsearchBM25CandidateRetriever",
    "ElasticsearchBM25QueryPlanningRetriever",
    "ElasticsearchBM25Unavailable",
    "EvidencePolicyViolation",
    "HybridCandidateRetriever",
    "InMemoryCandidateCardRetriever",
    "MilvusCandidateRagVectorRetriever",
    "QueryPlanningEvidenceRetriever",
    "LOCAL_TFIDF_VECTOR_METHOD",
    "LOCAL_VECTOR_METHOD",
    "RagContext",
    "RagEvidence",
    "RAG_COMPACT_DENSE_FIELD",
    "RAG_PARENT_PROFILE_FIELD",
    "RAG_RETRIEVAL_SCOPE",
    "RAG_STANDARD_FIELDS",
    "RagPolicy",
    "Small2BigCandidateEvidenceRetriever",
    "SENTENCE_TRANSFORMER_VECTOR_METHOD",
    "SentenceTransformerEmbeddingBackend",
    "TextEmbeddingBackend",
    "SQLiteBM25CandidateRetriever",
    "SQLiteBM25QueryPlanningRetriever",
    "SQLiteBM25Unavailable",
    "build_compact_item_text",
    "build_parent_profile_text",
    "build_elasticsearch_client",
    "build_empty_rag_context",
    "build_local_vector_index",
    "build_milvus_rag_chunk_index",
    "build_query_rag_context_for_planning",
    "build_rag_context_for_ranked_candidates",
    "build_sqlite_bm25_index",
    "bulk_index_elasticsearch_documents",
    "cosine_score",
    "elasticsearch_bm25_mapping",
    "elasticsearch_candidate_query",
    "elasticsearch_document_for_chunk",
    "elasticsearch_query_planning_query",
    "ensure_elasticsearch_bm25_index",
    "evidence_policy_violation_tokens",
    "iter_elasticsearch_documents",
    "load_local_vector_index",
    "normalize_item_record",
    "text_to_hashed_vector",
    "validate_parent_profile_manifest",
]


def __getattr__(name: str) -> object:
    if name in _RAG_AGENT_EXPORTS:
        from rs_core.agent.adapters import rag as rag_adapter

        return getattr(rag_adapter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
