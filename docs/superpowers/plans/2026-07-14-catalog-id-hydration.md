# Catalog ID Hydration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate `rs_catalog_item` and implement Redis-first exact-ID product hydration with MySQL fallback and stable batch ordering.

**Architecture:** A standard-library Python job performs resumable MySQL-to-MySQL projection. Catalog uses a cache interface with Redis and no-op implementations; the service performs cache-aside hydration without changing controller contracts. Gateway exposes Catalog publicly.

**Tech Stack:** Python 3, MySQL 8, Java 21, Spring Boot 4, MyBatis, Spring Data Redis, Jackson, Spring Cloud Gateway, JUnit 5.

## Global Constraints

- Never modify `amazon_items_base`.
- Never truncate `rs_catalog_item`.
- Preserve request order and duplicate IDs.
- Redis failure must fall back to MySQL.
- Do not modify retrieval, model, Agent, or trade services.
- Do not stage unrelated files.

---

### Task 1: Resumable Catalog Projection

**Files:**
- Modify: `java_agent/sql/rs_service_catalog_schema.sql`
- Create: `java_agent/scripts/project_catalog_to_mysql.py`
- Create: `java_agent/scripts/tests/test_project_catalog_to_mysql.py`

**Interfaces:**
- Produces: `MysqlCli.query_rows(sql)`, `next_batch_window(mysql, after, size)`,
  `build_projection_batch_sql(run_id, after, end, count)`, and CLI `main()`.
- Consumes: container-local `MYSQL_USER`, `MYSQL_PASSWORD`, and
  `MYSQL_DATABASE` environment variables.

- [ ] Write tests asserting stable keyset batches, safe SQL quoting, compact
  provenance, image/brand extraction, transactional checkpoint updates, and
  resume from the last committed ID.
- [ ] Run `python -m unittest discover -s java_agent/scripts/tests -v` and
  observe the expected missing-module failure.
- [ ] Add `rs_catalog_projection_run` and implement the minimal projection job.
- [ ] Re-run the Python tests and observe all tests passing.
- [ ] Commit only schema, script, and script tests.

### Task 2: Nested Attribute Mapping

**Files:**
- Modify: `java_agent/rs-service-catalog/src/main/java/com/sinrotic/rs/catalog/repository/MyBatisCatalogItemRepository.java`
- Create: `java_agent/rs-service-catalog/src/test/java/com/sinrotic/rs/catalog/repository/MyBatisCatalogItemRepositoryTest.java`

**Interfaces:**
- Produces: deterministic `Map<String,String>` values from scalar or nested
  `attributes_json` values.

- [ ] Write a failing repository test with a nested `Best Sellers Rank` value.
- [ ] Run the focused Maven test and observe the current empty-map behavior.
- [ ] Parse through `JsonNode`, using `asText()` for scalars and compact JSON
  for arrays/objects.
- [ ] Run all Catalog tests and commit the repository slice.

### Task 3: Redis Cache Adapter

**Files:**
- Modify: `java_agent/rs-service-catalog/pom.xml`
- Create: `java_agent/rs-service-catalog/src/main/java/com/sinrotic/rs/catalog/cache/CatalogItemCache.java`
- Create: `java_agent/rs-service-catalog/src/main/java/com/sinrotic/rs/catalog/cache/NoopCatalogItemCache.java`
- Create: `java_agent/rs-service-catalog/src/main/java/com/sinrotic/rs/catalog/cache/RedisCatalogItemCache.java`
- Create: `java_agent/rs-service-catalog/src/test/java/com/sinrotic/rs/catalog/cache/RedisCatalogItemCacheTest.java`

**Interfaces:**

```java
public interface CatalogItemCache {
    Map<String, CatalogItem> getAll(List<String> itemIds);
    void putAll(Collection<CatalogItem> items);
}
```

- [ ] Write failing tests for key format, JSON round-trip, partial `multiGet`,
  malformed JSON eviction, TTL, and contained Redis exceptions.
- [ ] Run the focused test and observe missing cache classes.
- [ ] Add Spring Data Redis and implement Redis/no-op adapters with conditional
  beans.
- [ ] Run cache tests and Catalog regression; commit the cache adapter.

### Task 4: Cache-Aside Catalog Service

**Files:**
- Modify: `java_agent/rs-service-catalog/src/main/java/com/sinrotic/rs/catalog/service/impl/DefaultCatalogService.java`
- Modify: `java_agent/rs-service-catalog/src/test/java/com/sinrotic/rs/catalog/service/DefaultCatalogServiceTest.java`

**Interfaces:**
- Consumes: `CatalogItemCache.getAll()` and `CatalogItemRepository.findByItemIds()`.
- Produces: existing Catalog detail/card/detail-text methods with cache-aside
  behavior and unchanged JSON contracts.

- [ ] Write failing tests for full cache hit, partial miss, duplicate/order
  preservation, and cache failure fallback.
- [ ] Run focused tests and observe constructor/missing behavior failures.
- [ ] Implement one `loadItemsInOrder(List<String>)` cache-aside path used by
  detail and all exact-ID batch methods.
- [ ] Run all Catalog tests and commit service orchestration.

### Task 5: Gateway And Remote Configuration

**Files:**
- Modify: `java_agent/rs-api-gateway/src/main/resources/application.yml`
- Create: `java_agent/rs-api-gateway/src/test/java/com/sinrotic/rs/gateway/config/GatewayRouteConfigurationTest.java`
- Modify: `java_agent/deploy/remote/app/docker-compose.yml`
- Modify: `java_agent/deploy/remote/app/.env.example`
- Modify: `java_agent/deploy/remote/app/README.md`

**Interfaces:**
- Produces: `/api/catalog/** -> lb://rs-service-catalog` and Catalog Redis
  properties `enabled=true`, `item-ttl-seconds=86400`.

- [ ] Write a failing YAML route test.
- [ ] Run the focused Gateway test and observe the missing route.
- [ ] Add the route and Catalog cache environment variables.
- [ ] Run Gateway and Catalog regression and commit deployment configuration.

### Task 6: Remote Population And Acceptance

**Files:** none; commands operate on `/home/luo/RS_agent_java`.

- [ ] Package Catalog and Gateway with tests skipped only after a passing test
  run.
- [ ] Back up remote jars and app configuration before replacement.
- [ ] Apply the schema, copy the projection script, and run 5,000-row batches
  to completion.
- [ ] Verify source count, active count, distinct IDs, missing titles, and JSON
  validity.
- [ ] Deploy Catalog and Gateway only.
- [ ] Verify direct/Gateway detail and batch responses, Redis key creation,
  repeated cache hits, unknown-ID omission, and input-order preservation.
- [ ] Run final local regression and record remote evidence.
