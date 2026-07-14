# Catalog And Hybrid Retrieval Foundation Design

**Status:** Approved on 2026-07-14

## Goal

Build the first usable online product-search loop on top of the migrated Amazon
data. Java services must be able to return complete product cards for BM25 and
semantic retrieval results, while preserving the imported raw tables as the
source of truth.

This project delivers:

1. A canonical online catalog projection in `rs_catalog_item`.
2. Public Catalog routing through the API Gateway.
3. A BM25 search endpoint that resolves Elasticsearch hits into product cards.
4. A real BGE-M3 query-embedding runtime loaded from MinIO.
5. Milvus semantic retrieval and RRF fusion with BM25 fallback.

The invalid zero-vector RAG chunk collection is explicitly out of scope. It
will be rebuilt in a separate RAG-data project.

## Existing Assets And Constraints

- `amazon_items_base` contains 887,002 distinct products and remains immutable.
- Elasticsearch index `rs_agent_rag_bm25_v1` contains product text and usable
  BM25 postings.
- Milvus collection `rs_agent_semantic_items_bge_m3_v1` contains 321,536 usable
  normalized 1024-dimensional item vectors.
- MinIO bucket `rs-agent-models` contains the complete BGE-M3 artifact.
- `rs-service-catalog` already reads `rs_catalog_item`, but the table is empty.
- `rs-service-recommend` already has Elasticsearch and Milvus client
  boundaries, while `rs-service-model` currently returns mock 3-dimensional
  embeddings.
- The current worktree contains unrelated Agent persistence changes. This
  project must not modify or include them in commits.

## Considered Approaches

### 1. Canonical projection with staged retrieval (selected)

Project raw products into the existing online catalog schema, then deliver
BM25 and semantic retrieval in two independently testable stages. This keeps
dataset concerns out of application queries and gives the system a working
fallback before model serving is enabled.

### 2. Read `amazon_items_base` directly from Catalog

This avoids a copy, but couples every online query to source JSON parsing and
the current dataset schema. It also makes future source changes and online
status fields harder to manage.

### 3. Rebuild every index before exposing search

This can maximize eventual coverage, but it delays a usable endpoint and mixes
catalog projection, model serving, index construction, and RAG repair into one
high-risk release.

## Architecture

### Catalog projection

An idempotent, resumable projection job streams rows from
`amazon_items_base` in stable `parent_asin` order and batch-upserts them into
`rs_catalog_item`. It records progress and a run manifest so interruption does
not require truncation or restarting from the first row.

The projection maps:

- `parent_asin` to canonical `item_id`.
- title, category, category path, brand, store, price, image URL, summary, and
  description to typed online columns.
- selected source details to a flat string attribute map.
- source identity and compact provenance to `raw_metadata` without duplicating
  unnecessary source payloads.
- missing titles to the item ID so every active row is displayable.

The source table is never updated or deleted. Re-running the projection uses
upsert semantics and converges on the same online rows.

### Public Catalog access

The Gateway adds an `/api/catalog/**` route to the registered Catalog service.
Existing Catalog detail, batch, text, and category APIs remain the ownership
boundary for product data. Retrieval services exchange item IDs and use batch
Catalog APIs to enrich results.

### BM25 search

`rs-service-recommend` owns a public product-search endpoint. For a text query
it calls Elasticsearch, normalizes hit scores, preserves rank, and batch-loads
matching product cards from Catalog. Missing catalog IDs are removed from the
response and counted in diagnostics.

BM25 is the required baseline provider and can operate before model serving is
available.

### Semantic search

`rs-service-model` replaces the mock embedding behavior for the BGE-M3 model
with a real runtime that:

1. Downloads the configured model prefix from MinIO into a versioned local
   cache when absent.
2. Loads the model once during service startup.
3. Produces exactly 1024 finite, non-zero dimensions for each query.
4. Normalizes embeddings consistently with the Milvus collection.

The model API keeps the existing Java service boundary. Recommend obtains a
query vector from Model, searches
`rs_agent_semantic_items_bge_m3_v1` with COSINE distance, and resolves returned
item IDs through Catalog.

### Hybrid fusion

Recommend runs BM25 and semantic retrieval independently and merges available
ranked lists with Reciprocal Rank Fusion. Item IDs are deduplicated before
Catalog enrichment. The response reports active providers and degradation
reasons so callers can distinguish hybrid results from BM25-only fallback.

The first implementation uses a fixed RRF rank constant from configuration and
does not add reranking or small-to-big expansion. Those are later pipeline
stages after the retrieval foundation is measured.

## Data Flow

1. The projection job reads `amazon_items_base` and upserts
   `rs_catalog_item`.
2. A client sends a search request through Gateway to Recommend.
3. Recommend sends the query to Elasticsearch and, when healthy, to Model and
   Milvus.
4. Recommend fuses ranked item IDs with RRF.
5. Recommend batch-fetches product cards from Catalog.
6. Recommend returns deduplicated cards plus provider diagnostics.

## Failure Handling

- Projection batches retry bounded transient failures and persist the last
  committed key only after a successful transaction.
- Re-running a failed projection is safe and does not truncate valid rows.
- Model timeout, invalid vector dimension, zero norm, or non-finite values
  disables semantic retrieval for that request.
- Milvus timeout or unavailable collection also degrades to BM25.
- Elasticsearch failure returns a service-unavailable response when no other
  provider succeeds; no empty success is fabricated.
- Catalog misses are filtered, logged, and exposed as a diagnostic count.
- Health checks validate embedding dimension and non-zero output, not only
  process reachability.

## Testing Strategy

Implementation follows test-driven slices:

1. Projection mapping and checkpoint tests with representative raw rows.
2. Catalog repository and controller tests against canonical rows.
3. Gateway route configuration tests.
4. BM25 orchestration tests for hit ordering, Catalog enrichment, and misses.
5. Model runtime contract tests for dimension, finite values, non-zero norm,
   cache behavior, and error propagation.
6. Semantic provider tests for Milvus request construction and ID mapping.
7. RRF tests for fusion, deduplication, deterministic tie handling, and
   degraded operation.
8. Remote smoke tests against MySQL, Elasticsearch, Model, Milvus, Catalog,
   Recommend, and Gateway.

## Deployment Sequence

### Stage 1: Catalog and BM25

1. Ship the projection schema/job and populate `rs_catalog_item`.
2. Verify all 887,002 source IDs have one active canonical row.
3. Deploy Catalog and Gateway routing.
4. Deploy the BM25 search endpoint and verify real product cards.

### Stage 2: BGE-M3, Milvus, and RRF

1. Deploy the real BGE-M3 model runtime from MinIO.
2. Enable semantic retrieval only after vector-quality health checks pass.
3. Deploy RRF fusion with provider diagnostics and BM25 fallback.
4. Run representative semantic and hybrid search smoke tests.

## Acceptance Criteria

1. `rs_catalog_item` has exactly 887,002 active, distinct item IDs.
2. Catalog category, detail, and batch APIs return real product data.
3. Catalog APIs are reachable through Gateway.
4. A BM25 query returns Elasticsearch IDs resolved into complete product cards.
5. Elasticsearch-to-Catalog join coverage is measured and reported.
6. Model embedding output is finite, non-zero, normalized, and exactly 1024
   dimensions.
7. Milvus semantic search returns scored item IDs that resolve through Catalog.
8. Hybrid results are deterministic, deduplicated, and report which providers
   contributed.
9. Model or Milvus failure produces an explicit BM25-only degraded response.
10. Focused tests and remote end-to-end smoke tests pass.

## Out Of Scope

- Rebuilding `rs_agent_rag_chunks_milvus_v1`.
- Review-text RAG indexing and small-to-big expansion.
- Cross-encoder reranking.
- Two-tower online serving.
- Candidate-store materialization.
- Authentication, order, inventory, payment, and Agent persistence work.
