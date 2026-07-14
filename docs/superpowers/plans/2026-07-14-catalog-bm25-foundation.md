# Catalog And BM25 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the canonical Java catalog from `amazon_items_base` and expose a Gateway-routed BM25 product search that returns real catalog cards.

**Architecture:** A resumable MySQL-to-MySQL projection owns raw-to-online mapping and leaves the raw table immutable. Recommend owns retrieval orchestration through provider and Catalog client interfaces; Elasticsearch returns ranked IDs and Catalog enriches them.

**Tech Stack:** Python 3 standard library, MySQL 8, Java 21, Spring Boot 4, Spring `RestClient`, MyBatis, Spring Cloud Gateway, JUnit 5, Mockito.

## Global Constraints

- `amazon_items_base` is read-only and remains the source of truth.
- Projection writes are idempotent upserts; no truncate is permitted.
- `rs_catalog_item` must contain 887,002 active distinct source IDs after the current import.
- Elasticsearch index `rs_agent_rag_bm25_v1` has only `item_id`, `field`, and `text` as searchable product fields.
- Catalog misses are filtered and counted, not represented by fabricated cards.
- Existing unrelated Agent persistence changes must never be staged or committed.

---

### Task 1: Resumable Catalog Projection Schema And Tool

**Files:**
- Modify: `java_agent/sql/rs_service_catalog_schema.sql`
- Create: `java_agent/scripts/project_catalog_to_mysql.py`
- Create: `java_agent/scripts/tests/test_project_catalog_to_mysql.py`

**Interfaces:**
- Consumes: MySQL tables `amazon_items_base` and `rs_catalog_item`; Docker container name and database credentials supplied as CLI arguments.
- Produces: `ProjectionRun`, `MysqlCli`, `next_batch_window()`, `build_projection_batch_sql()`, and a persisted row in `rs_catalog_projection_run`.

- [ ] **Step 1: Write failing projection tests**

```python
class ProjectionSqlTest(unittest.TestCase):
    def test_batch_sql_maps_nested_amazon_json_without_copying_raw_payload(self):
        sql = build_projection_batch_sql(7, "A000", "A999", 250)
        self.assertIn("JSON_TABLE(source.categories", sql)
        self.assertIn("JSON_EXTRACT(source.images, '$[0].large')", sql)
        self.assertIn("JSON_OBJECT('dataset', source.dataset", sql)
        self.assertNotIn("source.raw_json", sql)
        self.assertIn("WHERE source.parent_asin > 'A000'", sql)
        self.assertIn("source.parent_asin <= 'A999'", sql)

    def test_resume_uses_last_committed_item_id(self):
        mysql = FakeMysql(["7\tFAILED\tA050\t50\t100"])
        run = load_projection_run(mysql, 7)
        self.assertEqual("A050", run.last_source_item_id)
        self.assertEqual(50, run.processed_rows)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest java_agent.scripts.tests.test_project_catalog_to_mysql -v`

Expected: import failure because `project_catalog_to_mysql` does not exist.

- [ ] **Step 3: Add projection-run schema**

```sql
CREATE TABLE IF NOT EXISTS rs_catalog_projection_run (
    run_id BIGINT PRIMARY KEY AUTO_INCREMENT,
    status VARCHAR(16) NOT NULL,
    last_source_item_id VARCHAR(128) NOT NULL DEFAULT '',
    processed_rows BIGINT NOT NULL DEFAULT 0,
    source_rows BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    INDEX idx_rs_catalog_projection_status_updated (status, updated_at DESC)
);
```

- [ ] **Step 4: Implement CLI orchestration and stable batch SQL**

```python
@dataclass(frozen=True)
class ProjectionRun:
    run_id: int
    status: str
    last_source_item_id: str
    processed_rows: int
    source_rows: int

@dataclass(frozen=True)
class BatchWindow:
    end_item_id: str
    row_count: int

def next_batch_window(mysql: MysqlCli, after_item_id: str, batch_size: int) -> BatchWindow | None:
    row = mysql.query_one(
        "SELECT COALESCE(MAX(parent_asin), ''), COUNT(*) FROM ("
        "SELECT parent_asin FROM amazon_items_base "
        f"WHERE parent_asin > {sql_text(after_item_id)} ORDER BY parent_asin LIMIT {batch_size}"
        ") batch_window"
    )
    return None if not row or int(row[1]) == 0 else BatchWindow(row[0], int(row[1]))
```

`build_projection_batch_sql()` must perform one transaction containing the
`INSERT ... SELECT ... ON DUPLICATE KEY UPDATE` and the matching checkpoint
update. Category path and description use ordered `JSON_TABLE` aggregation;
brand and the first usable image use JSON extraction; `raw_metadata_json`
contains only dataset, source category/file/line, rating, and rating count.

- [ ] **Step 5: Run projection tests and verify GREEN**

Run: `python -m unittest java_agent.scripts.tests.test_project_catalog_to_mysql -v`

Expected: all projection tests pass.

- [ ] **Step 6: Commit projection slice**

```bash
git add java_agent/sql/rs_service_catalog_schema.sql java_agent/scripts/project_catalog_to_mysql.py java_agent/scripts/tests/test_project_catalog_to_mysql.py
git commit -m "feat: add resumable catalog projection"
```

### Task 2: Tolerant Catalog Attribute Mapping

**Files:**
- Modify: `java_agent/rs-service-catalog/src/main/java/com/sinrotic/rs/catalog/repository/MyBatisCatalogItemRepository.java`
- Create: `java_agent/rs-service-catalog/src/test/java/com/sinrotic/rs/catalog/repository/MyBatisCatalogItemRepositoryTest.java`

**Interfaces:**
- Consumes: nested JSON from `attributes_json`.
- Produces: a deterministic `Map<String,String>` where scalar values use text and nested values use compact JSON.

- [ ] **Step 1: Write failing nested-attribute test**

```java
@Test
void nestedAttributeValuesArePreservedAsCompactStrings() {
    CatalogItemMapper mapper = mock(CatalogItemMapper.class);
    when(mapper.selectByItemId("A1")).thenReturn(new CatalogItemRow(
            "A1", "A1", "Title", "Office", "Office > Supplies", "Brand", "Store",
            BigDecimal.TEN, null, "Summary", "Description",
            "{\"Color\":\"Black\",\"Best Sellers Rank\":{\"Office\":42}}", "{}", "active"));
    CatalogItem item = new MyBatisCatalogItemRepository(mapper, new ObjectMapper())
            .findByItemId("A1").orElseThrow();
    assertEquals("Black", item.attributes().get("Color"));
    assertEquals("{\"Office\":42}", item.attributes().get("Best Sellers Rank"));
}
```

- [ ] **Step 2: Run focused Catalog test and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-service-catalog -am -Dtest=MyBatisCatalogItemRepositoryTest -Dsurefire.failIfNoSpecifiedTests=false test`

Expected: nested value causes an empty attributes map.

- [ ] **Step 3: Parse attributes through `JsonNode`**

```java
private Map<String, String> parseAttributes(String json) {
    if (json == null || json.isBlank()) return Map.of();
    try {
        JsonNode root = objectMapper.readTree(json);
        if (!root.isObject()) return Map.of();
        Map<String, String> values = new LinkedHashMap<>();
        root.fields().forEachRemaining(entry -> values.put(
                entry.getKey(),
                entry.getValue().isValueNode() ? entry.getValue().asText() : entry.getValue().toString()
        ));
        return Map.copyOf(values);
    } catch (JsonProcessingException ignored) {
        return Map.of();
    }
}
```

- [ ] **Step 4: Run all Catalog tests and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-service-catalog -am -DskipTests=false test`

Expected: Catalog module and dependency tests pass.

```bash
git add java_agent/rs-service-catalog/src/main/java/com/sinrotic/rs/catalog/repository/MyBatisCatalogItemRepository.java java_agent/rs-service-catalog/src/test/java/com/sinrotic/rs/catalog/repository/MyBatisCatalogItemRepositoryTest.java
git commit -m "fix: preserve nested catalog attributes"
```

### Task 3: Gateway Catalog Route

**Files:**
- Modify: `java_agent/rs-api-gateway/src/main/resources/application.yml`
- Create: `java_agent/rs-api-gateway/src/test/java/com/sinrotic/rs/gateway/config/GatewayRouteConfigurationTest.java`

**Interfaces:**
- Consumes: requests matching `/api/catalog/**`.
- Produces: load-balanced forwarding to `lb://rs-service-catalog`.

- [ ] **Step 1: Write failing YAML route test**

```java
@Test
void catalogRouteTargetsCatalogService() throws IOException {
    Resource resource = new ClassPathResource("application.yml");
    PropertySource<?> source = new YamlPropertySourceLoader().load("gateway", resource).getFirst();
    assertEquals("rs-service-catalog", source.getProperty("spring.cloud.gateway.server.webflux.routes[2].id"));
    assertEquals("lb://rs-service-catalog", source.getProperty("spring.cloud.gateway.server.webflux.routes[2].uri"));
    assertEquals("Path=/api/catalog/**", source.getProperty("spring.cloud.gateway.server.webflux.routes[2].predicates[0]"));
}
```

- [ ] **Step 2: Run route test and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-api-gateway -am -Dtest=GatewayRouteConfigurationTest -Dsurefire.failIfNoSpecifiedTests=false test`

Expected: route properties are absent.

- [ ] **Step 3: Add route after the user routes**

```yaml
- id: rs-service-catalog
  uri: lb://rs-service-catalog
  predicates:
    - Path=/api/catalog/**
```

- [ ] **Step 4: Run Gateway tests and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-api-gateway -am -DskipTests=false test`

```bash
git add java_agent/rs-api-gateway/src/main/resources/application.yml java_agent/rs-api-gateway/src/test/java/com/sinrotic/rs/gateway/config/GatewayRouteConfigurationTest.java
git commit -m "feat: route catalog through gateway"
```

### Task 4: Product Search Contracts And RRF Orchestrator

**Files:**
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain/dto/ProductSearchRequestDTO.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain/recall/ProductRecallHit.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain/recall/ProductRecallRequest.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain/catalog/ProductCatalogCard.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain/vo/ProductSearchItemVO.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain/vo/ProductSearchProviderVO.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain/vo/ProductSearchVO.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/ProductRecallProvider.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/ProductCatalogClient.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/ProductSearchService.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/ProductSearchUnavailableException.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/DefaultProductSearchService.java`
- Create: `java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/DefaultProductSearchServiceTest.java`

**Interfaces:**
- Produces: `ProductSearchService.search(ProductSearchRequestDTO)` and provider method `recall(ProductRecallRequest)`.
- Consumes: ranked item IDs from all registered providers and cards from `ProductCatalogClient.fetchCards(List<String>)`.

- [ ] **Step 1: Write failing RRF and fallback tests**

```java
@Test
void searchUsesDeterministicRrfAndFiltersCatalogMisses() {
    ProductRecallProvider bm25 = provider("elasticsearch_bm25", hit("A", 1), hit("B", 2));
    ProductRecallProvider semantic = provider("milvus_semantic", hit("B", 1), hit("C", 2));
    ProductCatalogClient catalog = ids -> List.of(card("A"), card("B"));
    ProductSearchVO result = new DefaultProductSearchService(List.of(bm25, semantic), catalog, 60)
            .search(new ProductSearchRequestDTO("wireless headphones", 10));
    assertEquals(List.of("B", "A"), result.items().stream().map(ProductSearchItemVO::itemId).toList());
    assertEquals(1, result.missingCatalogCount());
    assertFalse(result.degraded());
}

@Test
void providerFailureProducesExplicitDegradedResult() {
    ProductRecallProvider down = new ProductRecallProvider() {
        @Override public String providerName() { return "milvus_semantic"; }
        @Override public List<ProductRecallHit> recall(ProductRecallRequest request) {
            throw new IllegalStateException("down");
        }
    };
    ProductSearchVO result = service(provider("elasticsearch_bm25", hit("A", 1)), down).search(request());
    assertTrue(result.degraded());
    assertEquals("DOWN", result.providers().get(1).status());
}
```

- [ ] **Step 2: Run service test and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=DefaultProductSearchServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`

Expected: product-search types do not exist.

- [ ] **Step 3: Implement contracts and deterministic RRF**

```java
public interface ProductRecallProvider {
    String providerName();
    List<ProductRecallHit> recall(ProductRecallRequest request);
}

public interface ProductCatalogClient {
    List<ProductCatalogCard> fetchCards(List<String> itemIds);
}

public record ProductRecallHit(String itemId, double score, int rank) {}
public record ProductRecallRequest(String requestId, String query, int limit) {}
```

`DefaultProductSearchService` must catch provider exceptions independently,
sum `1.0 / (rrfK + rank)` by item ID, sort by fused score descending then item
ID ascending, fetch at most 100 cards once, restore fused order, and mark
degraded when any registered provider is down. If every provider fails, throw
`ProductSearchUnavailableException` instead of returning an empty success.

- [ ] **Step 4: Run service tests and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=DefaultProductSearchServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`

```bash
git add java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/domain java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/DefaultProductSearchServiceTest.java
git commit -m "feat: add product search orchestration"
```

### Task 5: Elasticsearch And Catalog Providers

**Files:**
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/ElasticsearchProductBm25RecallProvider.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/RestProductCatalogClient.java`
- Create: `java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/ElasticsearchProductBm25RecallProviderTest.java`
- Create: `java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/RestProductCatalogClientTest.java`

**Interfaces:**
- Implements: `ProductRecallProvider` with provider name `elasticsearch_bm25`.
- Implements: `ProductCatalogClient` against `POST /internal/catalog/items/cards`.

- [ ] **Step 1: Write failing HTTP contract tests**

Use `MockRestServiceServer.bindTo(RestClient.builder())` and assert that the ES
request uses `match` on `text`, `collapse.field=item_id`, and `_source=[item_id]`.
Return two hits and assert ranks 1 and 2. For Catalog, assert the JSON request is
`{"item_ids":["A","B"]}` and snake-case fields deserialize into
`ProductCatalogCard`.

- [ ] **Step 2: Run provider tests and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=ElasticsearchProductBm25RecallProviderTest,RestProductCatalogClientTest -Dsurefire.failIfNoSpecifiedTests=false test`

Expected: provider classes do not exist.

- [ ] **Step 3: Implement ES query and Catalog client**

```java
Map<String, Object> body = Map.of(
        "size", request.limit(),
        "track_total_hits", false,
        "_source", List.of("item_id"),
        "collapse", Map.of("field", "item_id"),
        "query", Map.of("match", Map.of("text", Map.of("query", request.query())))
);
```

The provider must skip blank IDs and preserve ES hit order. The Catalog client
must return an empty list for empty input and use the configured
`rs.catalog.base-url`.

- [ ] **Step 4: Run provider and service tests and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=ElasticsearchProductBm25RecallProviderTest,RestProductCatalogClientTest,DefaultProductSearchServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`

```bash
git add java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/ElasticsearchProductBm25RecallProvider.java java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/RestProductCatalogClient.java java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/ElasticsearchProductBm25RecallProviderTest.java java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/RestProductCatalogClientTest.java
git commit -m "feat: connect product search to es and catalog"
```

### Task 6: Public Search Endpoint And Deployment Configuration

**Files:**
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/controller/app/ProductSearchController.java`
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/controller/app/ProductSearchExceptionHandler.java`
- Create: `java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/controller/app/ProductSearchControllerTest.java`
- Modify: `java_agent/deploy/remote/app/docker-compose.yml`
- Modify: `java_agent/deploy/remote/app/.env.example`

**Interfaces:**
- Produces: `POST /api/recommend/search`.
- Consumes: `{"query":"...","limit":20}`.

- [ ] **Step 1: Write failing controller contract tests**

Assert a valid request returns `request_id`, `degraded`, provider statuses,
`missing_catalog_count`, and complete product-card fields. Assert a blank query
returns HTTP 400 and `ProductSearchUnavailableException` returns HTTP 503.

- [ ] **Step 2: Run controller test and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=ProductSearchControllerTest -Dsurefire.failIfNoSpecifiedTests=false test`

- [ ] **Step 3: Implement endpoint and explicit status mapping**

```java
@RestController
@RequestMapping("/api/recommend")
public class ProductSearchController {
    @PostMapping("/search")
    ProductSearchVO search(@RequestBody ProductSearchRequestDTO request) {
        if (request == null || request.query() == null || request.query().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "query is required");
        }
        return productSearchService.search(request.withDefaults());
    }
}
```

- [ ] **Step 4: Add deployment properties**

```yaml
RS_RECOMMEND_SEARCH_ELASTICSEARCH_INDEX: ${RS_RECOMMEND_SEARCH_ELASTICSEARCH_INDEX:-rs_agent_rag_bm25_v1}
RS_RECOMMEND_SEARCH_RRF_K: ${RS_RECOMMEND_SEARCH_RRF_K:-60}
```

Add matching values to `.env.example`.

- [ ] **Step 5: Run Recommend regression tests and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -DskipTests=false test`

```bash
git add java_agent/rs-service-recommend/src/main java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/controller/app/ProductSearchControllerTest.java java_agent/deploy/remote/app/docker-compose.yml java_agent/deploy/remote/app/.env.example
git commit -m "feat: expose bm25 product search"
```

### Task 7: Stage 1 Build, Remote Projection, And Smoke Test

**Files:**
- Modify: `java_agent/deploy/remote/app/README.md`

**Interfaces:**
- Produces: populated remote catalog and reachable Gateway search endpoint.

- [ ] **Step 1: Run local regression**

Run: `mvn -f java_agent/pom.xml -pl rs-service-catalog,rs-service-recommend,rs-api-gateway -am -DskipTests=false test`

Expected: all selected modules pass.

- [ ] **Step 2: Build executable jars**

Run: `mvn -f java_agent/pom.xml -pl rs-service-catalog,rs-service-recommend,rs-api-gateway -am -DskipTests package`

Expected: three Spring Boot jars under module `target` directories.

- [ ] **Step 3: Copy schema, projection tool, jars, and app configuration**

Use `scp` to copy only this plan's artifacts into `/home/luo/RS_agent_java`.
Back up each replaced jar with a timestamp under
`/home/luo/RS_agent_java/backups/catalog-search-stage1/` before replacement.

- [ ] **Step 4: Apply schema and run the resumable projection**

Run the schema through `rs-agent-java-mysql`, then execute:

```bash
python3 /home/luo/RS_agent_java/scripts/project_catalog_to_mysql.py \
  --container rs-agent-java-mysql \
  --db-user rs_agent \
  --db-name rs_agent \
  --password-env MYSQL_PASSWORD \
  --batch-size 5000
```

Expected: projection status `COMPLETED`, processed rows `887002`.

- [ ] **Step 5: Verify catalog data quality**

Run exact SQL checks for source count, active count, distinct IDs, missing title,
valid JSON, and a 100-row ES-to-Catalog ID sample. Expected active and distinct
counts are `887002`; missing title is `0`; sampled join misses are `0`.

- [ ] **Step 6: Restart only affected Java services**

Run: `docker compose --env-file .env up -d rs-service-catalog rs-service-recommend rs-api-gateway`

Expected: all three containers become healthy/running and Catalog remains
registered in Nacos.

- [ ] **Step 7: Smoke test direct and Gateway APIs**

Verify:

```text
GET  http://127.0.0.1:18102/api/catalog/categories
GET  http://127.0.0.1:18088/api/catalog/items/0000306002
POST http://127.0.0.1:18088/api/recommend/search
     {"query":"wireless noise cancelling headphones","limit":10}
```

Expected: non-empty categories, a real item detail, and BM25 results with real
cards plus `elasticsearch_bm25=READY`.

- [ ] **Step 8: Document commands and commit**

```bash
git add java_agent/deploy/remote/app/README.md
git commit -m "docs: add catalog search deployment checks"
```
