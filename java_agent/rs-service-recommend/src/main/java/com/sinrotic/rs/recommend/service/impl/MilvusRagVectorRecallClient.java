package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.rag.RagEvidenceHit;
import com.sinrotic.rs.recommend.service.RagEvidenceRecallClient;
import com.sinrotic.rs.recommend.service.TextEmbeddingClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class MilvusRagVectorRecallClient implements RagEvidenceRecallClient {

    private static final String PROVIDER = "milvus_vector";

    private final TextEmbeddingClient textEmbeddingClient;
    private final RestClient restClient;
    private final String collectionName;
    private final String embeddingModelKey;
    private final String token;

    public MilvusRagVectorRecallClient(
            TextEmbeddingClient textEmbeddingClient,
            RestClient.Builder restClientBuilder,
            @Value("${rs.milvus.base-url:http://127.0.0.1:19530}") String milvusBaseUrl,
            @Value("${rs.milvus.token:}") String token,
            @Value("${rs.recommend.rag.milvus-collection:rs_agent_rag_chunks_milvus_v1}") String collectionName,
            @Value("${rs.recommend.rag.embedding-model-key:bge-m3}") String embeddingModelKey
    ) {
        this.textEmbeddingClient = textEmbeddingClient;
        this.restClient = restClientBuilder.baseUrl(milvusBaseUrl).build();
        this.token = token;
        this.collectionName = collectionName;
        this.embeddingModelKey = embeddingModelKey;
    }

    @Override
    public String providerName() {
        return PROVIDER;
    }

    @Override
    public List<RagEvidenceHit> retrieve(RagPipelineRunRequestDTO request) {
        if (request.query() == null || request.query().isBlank() || request.candidateItemIds().isEmpty()) {
            return List.of();
        }
        List<List<Float>> embeddings = textEmbeddingClient.embedTexts(
                embeddingModelKey,
                request.requestId() + "_rag_query_embed",
                List.of(request.query())
        );
        if (embeddings.isEmpty() || embeddings.getFirst().isEmpty()) {
            return List.of();
        }
        Map<String, Object> response = postMilvus(Map.of(
                "collectionName", collectionName,
                "data", List.of(embeddings.getFirst()),
                "annsField", "vector",
                "limit", request.topKPerProvider(),
                "filter", itemFilter(request.candidateItemIds()),
                "outputFields", List.of(
                        "item_id",
                        "field",
                        "text",
                        "source",
                        "source_name",
                        "full_text",
                        "parent_text",
                        "item_text",
                        "catalog_text",
                        "product_text",
                        "product_description",
                        "title",
                        "brand",
                        "category_path",
                        "categoryPath",
                        "category",
                        "attributes",
                        "summary",
                        "description"
                )
        ));
        Object data = response.get("data");
        List<?> rows = flattenRows(data);
        List<RagEvidenceHit> results = new ArrayList<>();
        int rank = 1;
        for (Object raw : rows) {
            if (!(raw instanceof Map<?, ?> row)) {
                continue;
            }
            Map<?, ?> payload = row.get("entity") instanceof Map<?, ?> entity ? entity : row;
            String itemId = text(firstNonNull(payload.get("item_id"), row.get("item_id"), row.get("id")));
            String field = text(payload.get("field"));
            String text = text(payload.get("text"));
            if (itemId.isBlank() || text.isBlank()) {
                continue;
            }
            results.add(new RagEvidenceHit(
                    PROVIDER,
                    itemId,
                    field,
                    text,
                    firstText(payload.get("source_name"), payload.get("source"), "catalog_rag_chunk"),
                    number(firstNonNull(row.get("distance"), row.get("score"))),
                    rank++,
                    metadata(payload)
            ));
        }
        return results;
    }

    private Map<String, Object> metadata(Map<?, ?> payload) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("milvus_collection", collectionName);
        copyIfPresent(metadata, payload, "full_text");
        copyIfPresent(metadata, payload, "parent_text");
        copyIfPresent(metadata, payload, "item_text");
        copyIfPresent(metadata, payload, "catalog_text");
        copyIfPresent(metadata, payload, "product_text");
        copyIfPresent(metadata, payload, "product_description");
        copyIfPresent(metadata, payload, "title");
        copyIfPresent(metadata, payload, "brand");
        copyIfPresent(metadata, payload, "category_path");
        copyIfPresent(metadata, payload, "categoryPath");
        copyIfPresent(metadata, payload, "category");
        copyIfPresent(metadata, payload, "attributes");
        copyIfPresent(metadata, payload, "summary");
        copyIfPresent(metadata, payload, "description");
        return metadata;
    }

    private void copyIfPresent(Map<String, Object> target, Map<?, ?> source, String key) {
        Object value = source.get(key);
        if (value != null && !value.toString().isBlank()) {
            target.put(key, value);
        }
    }

    private Map<String, Object> postMilvus(Map<String, Object> body) {
        RestClient.RequestBodySpec request = restClient.post().uri("/v2/vectordb/entities/search");
        if (token != null && !token.isBlank()) {
            request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        Map<String, Object> response = request.body(body).retrieve().body(Map.class);
        return response == null ? Map.of() : response;
    }

    private List<?> flattenRows(Object data) {
        if (!(data instanceof List<?> rows)) {
            return List.of();
        }
        if (rows.size() == 1 && rows.getFirst() instanceof List<?> nested) {
            return nested;
        }
        return rows;
    }

    private String itemFilter(List<String> itemIds) {
        String values = itemIds.stream()
                .map(value -> "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\"")
                .reduce((left, right) -> left + "," + right)
                .orElse("");
        return "item_id in [" + values + "]";
    }

    private Object firstNonNull(Object... values) {
        for (Object value : values) {
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private String firstText(Object primary, Object secondary, String fallback) {
        String primaryText = text(primary);
        if (!primaryText.isBlank()) {
            return primaryText;
        }
        String secondaryText = text(secondary);
        return secondaryText.isBlank() ? fallback : secondaryText;
    }

    private String text(Object value) {
        return value == null ? "" : value.toString();
    }

    private double number(Object value) {
        return value instanceof Number number ? number.doubleValue() : 0.0d;
    }
}
