# Catalog ID Hydration Design

**Status:** Approved on 2026-07-14

## Goal

Turn ranked item IDs produced by any recall provider into complete product
records with a bounded Caffeine L1, Redis L2, and MySQL as the source of truth.

This slice does not change BM25, Milvus, two-tower recall, RRF, reranking, or
model serving. Those systems produce `item_id`, score, and rank. Catalog owns
the exact-ID lookup that follows recall.

## Data Flow

For one item:

```text
item_id -> Caffeine -> Redis GET -> cache miss -> MySQL rs_catalog_item
        -> Redis SET + Caffeine PUT -> response
```

For ranked candidates:

```text
ranked item_ids -> Caffeine bulk lookup -> Redis MGET -> MySQL IN(misses)
                -> backfill Redis/Caffeine -> restore input order -> product cards
```

Redis never determines relevance and does not alter recall scores or order.
The caller combines Catalog records with its existing score and source tags.

## Canonical MySQL Projection

`amazon_items_base` remains immutable. A resumable, idempotent projection job
batch-upserts its 887,002 products into `rs_catalog_item`, whose primary key is
`item_id`. This avoids coupling online Java reads to raw Amazon JSON and avoids
unindexed `parent_asin` lookups in the source table's composite primary key.

The projection maps title, category, category path, brand, store, price, first
image, first feature summary, description, details, and compact source
provenance. Missing titles fall back to `item_id`. Checkpoint advancement and
each batch upsert occur in one transaction.

## Cache Contract

- Redis key format: `rs:catalog:item:v2:{item_id}`.
- Value: JSON serialization of the canonical `CatalogItem` entity.
- Redis default TTL is 24 hours plus randomized jitter of up to one hour,
  configurable through `rs.catalog.cache.item-ttl-seconds` and
  `rs.catalog.cache.item-ttl-jitter-seconds`.
- Cache is enabled with `rs.catalog.cache.enabled=true`.
- Cache failures degrade to MySQL for the current request.
- The local positive cache is bounded to 10,000 entries with a five-minute
  TTL. Unknown IDs use a separate bounded 30-second negative cache.
- A fixed striped-lock set coalesces concurrent misses for the same IDs. Locks
  are acquired by sorted stripe index so multi-ID requests cannot deadlock.
- Batch reads deduplicate database misses but preserve duplicate IDs and input
  order in the response.

## Components

`CatalogLocalCache` owns bounded positive and negative L1 entries.
`CatalogItemCache` defines L2 batch get/put operations, and
`RedisCatalogItemCache` owns Redis keys, JSON serialization, and TTL jitter.
No-op implementations keep deployments usable when either cache is disabled.
`DefaultCatalogService` owns cache-aside orchestration and concurrent miss
coalescing while keeping the public and internal Catalog contracts unchanged.

Gateway adds `/api/catalog/** -> lb://rs-service-catalog`. Recall services use
the existing internal batch endpoint
`POST /internal/catalog/items/cards`; external callers can use
`POST /api/catalog/items/batch`.

## Failure Behavior

- Redis read/write errors are contained and logged; MySQL remains available.
- MySQL errors propagate as service errors rather than fabricated empty data.
- Malformed cached JSON is evicted and treated as a cache miss.
- Empty and blank item IDs are ignored by the existing request normalization.
- Unknown IDs are omitted from results.

## Verification

Automated tests cover L1/L2 hits, partial misses, order restoration, duplicate
IDs, Redis failure fallback, local negative caching, concurrent miss
coalescing, nested attribute JSON, and Gateway routing.

Remote acceptance requires:

1. `rs_catalog_item` has 887,002 active distinct item IDs.
2. Direct Catalog detail and batch endpoints return real products.
3. Gateway Catalog detail and batch endpoints return the same products.
4. First lookup increases Redis keys and reads MySQL.
5. Repeated lookup succeeds from Redis when the matching MySQL row is
   temporarily made unavailable inside a rollback-only verification
   transaction or is proven through cache instrumentation.
6. Input order is preserved for mixed hit/miss batches.

## Out Of Scope

- Text or semantic relevance calculation.
- BM25, Milvus, two-tower, RRF, rerank, and small-to-big changes.
- Preloading all products into Redis.
- Cache invalidation from product-write events; source data is currently
  immutable and TTL expiry is sufficient for this slice.
