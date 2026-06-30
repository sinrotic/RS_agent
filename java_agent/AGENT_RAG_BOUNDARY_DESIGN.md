# Agent RAG Boundary Design

## Current Decision

`rs-service-search-rag` has been removed as a standalone microservice.

Recommendation-scoped search, RAG evidence lookup, RAG pipeline execution, and RAG trace observation are part of `rs-service-recommend`.

The long-term service boundary is:

```text
rs-service-agent
  - owns agent loop
  - reads model streams
  - detects tool_use
  - dispatches tools
  - feeds tool_result back into the next loop
  - emits final structured answer

rs-service-recommend
  - owns recommendation candidates
  - owns recall, ranking, reranking
  - owns recommendation-scoped RAG evidence
  - owns candidate evidence compression
  - owns recommendation explanation context

rs-service-platform-trace
  - observes recommendation traces
  - observes agent tool calls
  - observes RAG provider readiness and RAG pipeline traces
```

## Why RAG Belongs To Recommend

The current RAG requirement is not a general knowledge-base Q&A service. It is tied to the recommendation workflow.

The RAG inputs are recommendation-domain inputs:

- user query
- session id
- profile user id
- candidate item ids
- recommendation request id
- ranking and reranking stage
- item metadata and product text

Keeping RAG as a separate microservice would force `recommend` to send recommendation context to another service and then merge the result back. That creates an artificial boundary.

Putting RAG inside `rs-service-recommend` keeps the owner of candidates, ranking, evidence, and explanation in one service.

## Agent Tool Routing

The agent should call recommendation-semantic tools, not low-level retrieval services.

```text
tool_use: recommend_candidates
  -> service: rs-service-recommend

tool_use: rag_support
  -> service: rs-service-recommend

tool_use: rag_evidence_search
  -> service: rs-service-recommend
```

The agent loop does not know whether evidence comes from Elasticsearch, Milvus, a Python bridge, vLLM embeddings, or local mock data. That detail belongs behind the recommendation service interface.

## Replacement Endpoints

The migrated recommendation RAG endpoints are:

```text
POST /agent/recommend/rag/support
POST /internal/recommend/rag/batch-evidence
POST /internal/recommend/rag/pipeline/run
GET  /api/platform/recommend/rag/{requestId}/trace
GET  /api/platform/recommend/rag/health
```

The old `rs-service-search-rag` endpoints were removed:

```text
POST /agent/rag/support
POST /internal/rag/batch-evidence
POST /internal/rag/pipeline/run
GET  /api/platform/rag/{requestId}/trace
GET  /api/platform/rag/health
```

## Runtime Flow

```text
1. User asks for products
   -> rs-service-agent receives the chat request

2. Model emits tool_use: recommend_candidates
   -> rs-service-agent dispatches to rs-service-recommend

3. Recommendation candidates return
   -> agent loop feeds tool_result back to the model

4. Model emits tool_use: rag_support
   -> rs-service-agent dispatches to rs-service-recommend

5. Recommendation RAG evidence returns
   -> agent loop feeds item evidence back to the model

6. Model emits tool_use: emit_final_answer
   -> rs-service-agent streams structured answer blocks to the frontend
```

## Deprecation Plan

1. `rs-service-agent` routes all RAG tools to `rs-service-recommend`.
2. `rs-service-recommend` exposes agent, internal, and platform RAG endpoints.
3. Parent Maven build no longer includes `rs-service-search-rag`.
4. Gateway routes no longer reference `rs-service-search-rag`.
5. The old `rs-service-search-rag` module directory has been physically deleted.

## Interview Talking Point

The design keeps the agent generic and the retrieval implementation hidden behind recommendation-domain tools.

This is better than exposing Elasticsearch or Milvus directly to the agent because tool names and payloads remain stable while the retrieval implementation can evolve from mock data to BM25, vector retrieval, rerank, small2big compression, and structured evidence storage.
