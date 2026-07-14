# BGE-M3 Milvus Hybrid Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mock query embeddings with real BGE-M3 vectors loaded from MinIO, add Milvus product recall, and fuse semantic and BM25 results with explicit degradation behavior.

**Architecture:** A MinIO initialization container materializes the uploaded BGE-M3 ONNX artifact into a persistent cache and the official Hugging Face Text Embeddings Inference runtime serves it. `rs-service-model` remains the Java gateway and validates every embedding; Recommend adds a conditional semantic provider to the Stage 1 RRF orchestrator.

**Tech Stack:** Hugging Face Text Embeddings Inference `cpu-1.9`, ONNX Runtime, MinIO Client, Docker Compose, Java 21, Spring Boot 4, Spring `RestClient`, Milvus REST v2, JUnit 5.

## Global Constraints

- The runtime source is `minio://rs-agent-models/embedding/bge-m3/BAAI/bge-m3/onnx/`.
- Query embeddings must contain exactly 1024 finite values with non-zero norm.
- Normalized query embeddings must have L2 norm between `0.99` and `1.01`.
- Semantic collection is `rs_agent_semantic_items_bge_m3_v1`, COSINE, field `vector`.
- Semantic failure must produce a visible BM25-only degraded response.
- The invalid `rs_agent_rag_chunks_milvus_v1` collection is not used or modified.
- Existing mock rank/chat behavior remains outside this slice; only embedding and embedding health become real.

---

### Task 1: MinIO-Backed TEI Runtime

**Files:**
- Modify: `java_agent/deploy/remote/app/docker-compose.yml`
- Modify: `java_agent/deploy/remote/app/.env.example`
- Modify: `java_agent/deploy/remote/app/README.md`

**Interfaces:**
- Consumes: MinIO prefix `embedding/bge-m3/BAAI/bge-m3/onnx/`.
- Produces: TEI HTTP `POST /embed`, `GET /health`, and `GET /info` at `http://rs-embedding-runtime:80`.

- [ ] **Step 1: Add explicit runtime configuration values**

```dotenv
RS_EMBEDDING_RUNTIME_HOST_PORT=18090
RS_EMBEDDING_RUNTIME_BASE_URL=http://rs-embedding-runtime:80
RS_EMBEDDING_MODEL_BUCKET=rs-agent-models
RS_EMBEDDING_MODEL_PREFIX=embedding/bge-m3/BAAI/bge-m3/onnx
RS_EMBEDDING_MODEL_CACHE=../data/model-cache/bge-m3-onnx
RS_RECOMMEND_SEARCH_SEMANTIC_ENABLED=true
```

- [ ] **Step 2: Add one-shot MinIO materialization service**

```yaml
rs-embedding-model-sync:
  image: minio/minio:RELEASE.2025-04-22T22-12-26Z
  restart: "no"
  networks:
    - rs-agent-java
  volumes:
    - ${RS_EMBEDDING_MODEL_CACHE:-../data/model-cache/bge-m3-onnx}:/model
  entrypoint: ["/bin/sh", "-lc"]
  command:
    - >-
      mc alias set source http://minio:9000 "$${MINIO_USER}" "$${MINIO_PASSWORD}" &&
      mc mirror --overwrite
      source/${RS_EMBEDDING_MODEL_BUCKET:-rs-agent-models}/${RS_EMBEDDING_MODEL_PREFIX:-embedding/bge-m3/BAAI/bge-m3/onnx}/
      /model/
  environment:
    MINIO_USER: ${RS_MINIO_USER:-rs_agent}
    MINIO_PASSWORD: ${RS_MINIO_PASSWORD:-rs_agent_minio_password}
```

- [ ] **Step 3: Add official TEI ONNX runtime**

```yaml
rs-embedding-runtime:
  image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.9
  container_name: rs-agent-java-embedding-runtime
  restart: unless-stopped
  depends_on:
    rs-embedding-model-sync:
      condition: service_completed_successfully
  networks:
    - rs-agent-java
  volumes:
    - ${RS_EMBEDDING_MODEL_CACHE:-../data/model-cache/bge-m3-onnx}:/model:ro
  command:
    - --model-id
    - /model
    - --dtype
    - float32
    - --pooling
    - cls
    - --max-input-length
    - "512"
    - --auto-truncate
  ports:
    - "127.0.0.1:${RS_EMBEDDING_RUNTIME_HOST_PORT:-18090}:80"
  shm_size: 1gb
```

- [ ] **Step 4: Validate Compose structure before commit**

Run: `docker compose -f java_agent/deploy/remote/app/docker-compose.yml --env-file java_agent/deploy/remote/app/.env.example config --quiet`

Expected: exit 0 and no unresolved variables.

- [ ] **Step 5: Commit runtime deployment slice**

```bash
git add java_agent/deploy/remote/app/docker-compose.yml java_agent/deploy/remote/app/.env.example java_agent/deploy/remote/app/README.md
git commit -m "feat: add minio backed bge embedding runtime"
```

### Task 2: Real Java Embedding Gateway And Quality Validation

**Files:**
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/EmbeddingRuntimeClient.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/TeiEmbeddingRuntimeClient.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/EmbeddingVectorValidator.java`
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/DefaultModelGatewayService.java`
- Modify: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/MockModelGatewayService.java`
- Create: `java_agent/rs-service-model/src/test/java/com/sinrotic/rs/model/service/impl/DefaultModelGatewayServiceTest.java`
- Create: `java_agent/rs-service-model/src/test/java/com/sinrotic/rs/model/service/impl/TeiEmbeddingRuntimeClientTest.java`

**Interfaces:**
- Produces: `EmbeddingRuntimeClient.embed(List<String>, boolean)` and real `ModelGatewayService.embed(ModelEmbedRequestDTO)` for `bge-m3`.
- Consumes: TEI response `List<List<Double>>`.

- [ ] **Step 1: Write failing vector-quality tests**

```java
@Test
void embedReturnsValidatedBgeVectors() {
    List<Double> vector = unitVector(1024);
    DefaultModelGatewayService service = service((texts, normalize) -> List.of(vector));
    ModelEmbedVO result = service.embed(request("bge-m3", List.of("wireless headphones"), true));
    assertEquals(1024, result.vectors().getFirst().vector().size());
    assertEquals(1024, result.usage().get("dimension"));
}

@Test
void embedRejectsZeroOrWrongDimensionVectors() {
    assertThrows(IllegalStateException.class,
            () -> service((texts, normalize) -> List.of(Collections.nCopies(1024, 0.0))).embed(request()));
    assertThrows(IllegalStateException.class,
            () -> service((texts, normalize) -> List.of(List.of(1.0, 2.0))).embed(request()));
}
```

- [ ] **Step 2: Run Model tests and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-service-model -am -Dtest=DefaultModelGatewayServiceTest,TeiEmbeddingRuntimeClientTest -Dsurefire.failIfNoSpecifiedTests=false test`

- [ ] **Step 3: Implement TEI client**

```java
public interface EmbeddingRuntimeClient {
    List<List<Double>> embed(List<String> texts, boolean normalize);
}

@Override
public List<List<Double>> embed(List<String> texts, boolean normalize) {
    List<List<Double>> response = restClient.post()
            .uri("/embed")
            .body(Map.of("inputs", texts, "normalize", normalize, "truncate", true))
            .retrieve()
            .body(new ParameterizedTypeReference<>() {});
    return response == null ? List.of() : response;
}
```

- [ ] **Step 4: Implement gateway validation and preserve non-embedding mocks**

Remove `@Service` from `MockModelGatewayService`. Register
`DefaultModelGatewayService` as the sole `ModelGatewayService`; delegate infer,
rank, rank-signals, chat, and stream-chat to the existing mock instance. For
embed, require `model_key=bge-m3`, extract `inputs.texts`, cap batches at 32,
call TEI once, require count equality, validate each vector, and return IDs
`text_0..text_n` with runtime `tei_onnx`.

```java
double norm = Math.sqrt(vector.stream().mapToDouble(value -> value * value).sum());
if (vector.size() != 1024 || !Double.isFinite(norm) || norm == 0.0) {
    throw new IllegalStateException("invalid bge-m3 embedding vector");
}
if (normalized && (norm < 0.99 || norm > 1.01)) {
    throw new IllegalStateException("bge-m3 embedding is not normalized");
}
```

- [ ] **Step 5: Run Model tests and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-service-model -am -DskipTests=false test`

```bash
git add java_agent/rs-service-model/src/main java_agent/rs-service-model/src/test
git commit -m "feat: serve validated bge embeddings"
```

### Task 3: Real Embedding Health And Registry Metadata

**Files:**
- Create: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/DefaultModelHealthService.java`
- Modify: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/MockModelHealthService.java`
- Modify: `java_agent/rs-service-model/src/main/java/com/sinrotic/rs/model/service/impl/InMemoryModelRegistryService.java`
- Create: `java_agent/rs-service-model/src/test/java/com/sinrotic/rs/model/service/impl/DefaultModelHealthServiceTest.java`
- Modify: `java_agent/rs-service-model/src/test/java/com/sinrotic/rs/model/service/impl/InMemoryModelRegistryServiceTest.java`

**Interfaces:**
- Produces: truthful `GET /internal/model/bge-m3/health` and corrected model registry metadata.

- [ ] **Step 1: Write failing health and registry tests**

Assert a valid probe vector reports `UP/tei_onnx`; a runtime exception or zero
vector reports `DOWN`; registry entry `bge-m3` points to
`minio://rs-agent-models/embedding/bge-m3/BAAI/bge-m3/onnx/` and
`http://rs-embedding-runtime:80/embed`.

- [ ] **Step 2: Run tests and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-service-model -am -Dtest=DefaultModelHealthServiceTest,InMemoryModelRegistryServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`

- [ ] **Step 3: Implement a real BGE health probe**

Remove `@Service` from `MockModelHealthService`. Register
`DefaultModelHealthService`, delegate non-BGE keys to the old mock, and for
`bge-m3` call the runtime with `List.of("embedding health probe")`, validate the
vector, and report current ISO-8601 time plus measured latency. Do not report
`UP` based only on `/health` reachability.

- [ ] **Step 4: Run Model regression and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-service-model -am -DskipTests=false test`

```bash
git add java_agent/rs-service-model/src/main java_agent/rs-service-model/src/test
git commit -m "fix: report real embedding runtime health"
```

### Task 4: Conditional Milvus Semantic Product Provider

**Files:**
- Create: `java_agent/rs-service-recommend/src/main/java/com/sinrotic/rs/recommend/service/impl/MilvusSemanticProductRecallProvider.java`
- Create: `java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/MilvusSemanticProductRecallProviderTest.java`
- Modify: `java_agent/deploy/remote/app/docker-compose.yml`
- Modify: `java_agent/deploy/remote/app/.env.example`

**Interfaces:**
- Implements: `ProductRecallProvider` named `milvus_semantic`.
- Consumes: `TextEmbeddingClient.embedTexts()` and `VectorRecallClient.searchSimilarItems()`.

- [ ] **Step 1: Write failing semantic-provider tests**

```java
@Test
void semanticRecallEmbedsOnceAndPreservesMilvusRank() {
    TextEmbeddingClient embeddings = (model, requestId, texts) -> List.of(unitFloatVector(1024));
    VectorRecallClient milvus = (collection, vector, limit) -> List.of(
            new VectorRecallItem("B", 0.92), new VectorRecallItem("A", 0.87));
    var provider = new MilvusSemanticProductRecallProvider(
            embeddings, milvus, "bge-m3", "rs_agent_semantic_items_bge_m3_v1", 1024);
    assertEquals(List.of("B", "A"), provider.recall(request()).stream().map(ProductRecallHit::itemId).toList());
}
```

Also assert wrong dimension, zero vector, empty model response, and blank Milvus
IDs throw explicit exceptions that the search orchestrator can degrade.

- [ ] **Step 2: Run provider test and verify RED**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=MilvusSemanticProductRecallProviderTest -Dsurefire.failIfNoSpecifiedTests=false test`

- [ ] **Step 3: Implement condition and vector checks**

```java
@Service
@ConditionalOnProperty(name = "rs.recommend.search.semantic-enabled", havingValue = "true")
public class MilvusSemanticProductRecallProvider implements ProductRecallProvider {
    public static final String PROVIDER = "milvus_semantic";
    // Embed request.query() once, validate 1024 finite non-zero values,
    // search the configured collection, and assign ranks from response order.
}
```

- [ ] **Step 4: Wire deployment flags**

```yaml
RS_EMBEDDING_RUNTIME_BASE_URL: ${RS_EMBEDDING_RUNTIME_BASE_URL:-http://rs-embedding-runtime:80}
RS_RECOMMEND_SEARCH_SEMANTIC_ENABLED: ${RS_RECOMMEND_SEARCH_SEMANTIC_ENABLED:-true}
RS_RECOMMEND_SEARCH_SEMANTIC_MODEL_KEY: ${RS_RECOMMEND_SEARCH_SEMANTIC_MODEL_KEY:-bge-m3}
RS_RECOMMEND_SEARCH_SEMANTIC_COLLECTION: ${RS_RECOMMEND_SEARCH_SEMANTIC_COLLECTION:-rs_agent_semantic_items_bge_m3_v1}
RS_RECOMMEND_SEARCH_SEMANTIC_DIMENSION: ${RS_RECOMMEND_SEARCH_SEMANTIC_DIMENSION:-1024}
```

- [ ] **Step 5: Run Recommend tests and commit**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -DskipTests=false test`

```bash
git add java_agent/rs-service-recommend java_agent/deploy/remote/app/docker-compose.yml java_agent/deploy/remote/app/.env.example
git commit -m "feat: add milvus semantic product recall"
```

### Task 5: Hybrid And Degradation Contract Regression

**Files:**
- Modify: `java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/DefaultProductSearchServiceTest.java`
- Modify: `java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/controller/app/ProductSearchControllerTest.java`

**Interfaces:**
- Verifies: hybrid RRF, duplicate suppression, semantic-only success, BM25-only fallback, and all-provider failure.

- [ ] **Step 1: Add full hybrid contract cases**

Tests must assert:

```text
both ready       -> degraded=false, tags include both providers
semantic down    -> degraded=true, BM25 cards remain
BM25 down        -> degraded=true, semantic cards remain
both down        -> HTTP 503
duplicate item   -> one card with deterministic fused rank
Catalog miss     -> missing_catalog_count increments
```

- [ ] **Step 2: Run focused tests**

Run: `mvn -f java_agent/pom.xml -pl rs-service-recommend -am -Dtest=DefaultProductSearchServiceTest,ProductSearchControllerTest,MilvusSemanticProductRecallProviderTest -Dsurefire.failIfNoSpecifiedTests=false test`

Expected: all cases pass.

- [ ] **Step 3: Commit regression contract**

```bash
git add java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/service/DefaultProductSearchServiceTest.java java_agent/rs-service-recommend/src/test/java/com/sinrotic/rs/recommend/controller/app/ProductSearchControllerTest.java
git commit -m "test: cover hybrid search degradation"
```

### Task 6: Stage 2 Build, Remote Runtime, And End-To-End Verification

**Files:**
- Modify: `java_agent/deploy/remote/app/README.md`

**Interfaces:**
- Produces: remote real embeddings and hybrid search through Gateway.

- [ ] **Step 1: Run local regression and package**

Run: `mvn -f java_agent/pom.xml -pl rs-service-model,rs-service-recommend,rs-service-catalog,rs-api-gateway -am -DskipTests=false package`

Expected: selected modules build and all tests pass.

- [ ] **Step 2: Copy jars and Compose configuration with backups**

Back up Model and Recommend jars under
`/home/luo/RS_agent_java/backups/catalog-search-stage2/`, then copy only the new
jars, Compose file, environment additions, and README.

- [ ] **Step 3: Materialize model and start TEI**

Run:

```bash
docker compose --env-file .env up rs-embedding-model-sync
docker compose --env-file .env up -d rs-embedding-runtime
```

Expected: cache contains `model.onnx`, `model.onnx_data`, tokenizer files, and
config; `/health` is 200; `/info` reports XLM-RoBERTa with CLS pooling.

- [ ] **Step 4: Validate raw runtime vectors**

Call `POST http://127.0.0.1:18090/embed` with English and Chinese product
queries. Verify each vector has 1024 finite values, non-zero norm, and norm
between 0.99 and 1.01.

- [ ] **Step 5: Restart Model and Recommend**

Run: `docker compose --env-file .env up -d rs-service-model rs-service-recommend`

Expected: Model registers in Nacos, BGE health reports `UP`, and no mock
dimension `3` response remains for `bge-m3`.

- [ ] **Step 6: Verify Milvus semantic recall**

Send a real query through Model, use its vector against
`rs_agent_semantic_items_bge_m3_v1`, and verify positive COSINE scores and item
IDs that resolve in Catalog.

- [ ] **Step 7: Verify hybrid Gateway search and forced fallback**

Call `POST http://127.0.0.1:18088/api/recommend/search` and verify both providers
are `READY`, results are deduplicated, and cards are complete. Then stop only
the embedding runtime, repeat the request, and verify a successful explicit
BM25-only degraded response; restart the runtime afterward.

- [ ] **Step 8: Record measured coverage and commit runbook**

Document Catalog count, ES distinct-item estimate, semantic collection count,
join sample misses, runtime vector dimension/norm, and representative latency.

```bash
git add java_agent/deploy/remote/app/README.md
git commit -m "docs: add hybrid search verification runbook"
```
