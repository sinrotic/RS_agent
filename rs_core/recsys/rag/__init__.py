from rs_core.recsys.rag.bm25 import (
    SQLiteBM25CandidateRetriever,
    SQLiteBM25QueryPlanningRetriever,
    SQLiteBM25Unavailable,
    build_sqlite_bm25_index,
)
from rs_core.recsys.rag.context import build_empty_rag_context
from rs_core.recsys.rag.corpus import (
    RAG_COMPACT_DENSE_FIELD,
    RAG_PARENT_PROFILE_FIELD,
    RAG_STANDARD_FIELDS,
    build_compact_item_text,
    build_parent_profile_text,
    normalize_item_record,
)
from rs_core.recsys.rag.hybrid import HybridCandidateRetriever, cosine_score, text_to_hashed_vector
from rs_core.recsys.rag.qdrant_index import build_qdrant_rag_chunk_index
from rs_core.recsys.rag.qdrant_vector import QdrantCandidateRagVectorRetriever
from rs_core.recsys.rag.vector_index import (
    DEFAULT_DENSE_MODEL_NAME,
    DEFAULT_RAG_CORPUS_SCOPE,
    LOCAL_TFIDF_VECTOR_METHOD,
    LOCAL_VECTOR_METHOD,
    RAG_RETRIEVAL_SCOPE,
    SENTENCE_TRANSFORMER_VECTOR_METHOD,
    SentenceTransformerEmbeddingBackend,
    build_local_vector_index,
    load_local_vector_index,
)
from rs_core.recsys.rag.retriever import (
    EvidencePolicyViolation,
    InMemoryCandidateCardRetriever,
    QueryPlanningEvidenceRetriever,
    RagPolicy,
    Small2BigCandidateEvidenceRetriever,
    validate_parent_profile_manifest,
    build_query_rag_context_for_planning,
    build_rag_context_for_ranked_candidates,
    evidence_policy_violation_tokens,
)
from rs_core.recsys.rag.schema import RagContext, RagEvidence

__all__ = [
    "DEFAULT_DENSE_MODEL_NAME",
    "DEFAULT_RAG_CORPUS_SCOPE",
    "EvidencePolicyViolation",
    "HybridCandidateRetriever",
    "InMemoryCandidateCardRetriever",
    "QdrantCandidateRagVectorRetriever",
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
    "SQLiteBM25CandidateRetriever",
    "SQLiteBM25QueryPlanningRetriever",
    "SQLiteBM25Unavailable",
    "build_compact_item_text",
    "build_parent_profile_text",
    "build_empty_rag_context",
    "build_local_vector_index",
    "build_qdrant_rag_chunk_index",
    "build_query_rag_context_for_planning",
    "build_rag_context_for_ranked_candidates",
    "build_sqlite_bm25_index",
    "cosine_score",
    "evidence_policy_violation_tokens",
    "load_local_vector_index",
    "normalize_item_record",
    "text_to_hashed_vector",
    "validate_parent_profile_manifest",
]
