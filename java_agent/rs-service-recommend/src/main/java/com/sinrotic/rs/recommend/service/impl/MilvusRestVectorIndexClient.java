package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.recommend.domain.recall.ItemVectorDocument;
import com.sinrotic.rs.recommend.domain.recall.VectorRecallItem;
import com.sinrotic.rs.recommend.service.ItemVectorIndexClient;
import com.sinrotic.rs.recommend.service.VectorRecallClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class MilvusRestVectorIndexClient implements ItemVectorIndexClient, VectorRecallClient {

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String token;

    public MilvusRestVectorIndexClient(
            RestClient.Builder restClientBuilder,
            ObjectMapper objectMapper,
            @Value("${rs.milvus.base-url:http://127.0.0.1:19530}") String milvusBaseUrl,
            @Value("${rs.milvus.token:}") String token
    ) {
        this.restClient = restClientBuilder.baseUrl(milvusBaseUrl).build();
        this.objectMapper = objectMapper;
        this.token = token;
    }

    @Override
    public int upsertItems(String collectionName, List<ItemVectorDocument> documents) {
        if (documents.isEmpty()) {
            return 0;
        }
        Map<String, Object> body = Map.of(
                "collectionName", collectionName,
                "data", documents.stream().map(this::toMilvusRow).toList()
        );
        callMilvus("/v2/vectordb/entities/upsert", body);
        return documents.size();
    }

    @Override
    public List<VectorRecallItem> searchSimilarItems(String collectionName, List<Float> queryVector, int limit) {
        if (queryVector.isEmpty() || limit <= 0) {
            return List.of();
        }
        Map<String, Object> body = Map.of(
                "collectionName", collectionName,
                "data", List.of(queryVector),
                "annsField", "vector",
                "limit", limit,
                "outputFields", List.of("item_id")
        );
        Map<String, Object> response = callMilvus("/v2/vectordb/entities/search", body);
        Object data = response.get("data");
        if (!(data instanceof List<?> rows)) {
            return List.of();
        }
        return rows.stream()
                .filter(Map.class::isInstance)
                .map(Map.class::cast)
                .map(this::toVectorRecallItem)
                .toList();
    }

    private Map<String, Object> callMilvus(String path, Map<String, Object> body) {
        RestClient.RequestBodySpec request = restClient.post().uri(path);
        if (token != null && !token.isBlank()) {
            request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
        }
        Map<String, Object> response = request
                .body(body)
                .retrieve()
                .body(Map.class);
        return response == null ? Map.of() : response;
    }

    private Map<String, Object> toMilvusRow(ItemVectorDocument document) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("item_id", document.itemId());
        row.put("vector", document.vector());
        row.put("title", document.title());
        row.put("category", document.category());
        row.put("category_path", document.categoryPath());
        row.put("brand", document.brand());
        row.put("price", document.price());
        row.put("embedding_text", document.embeddingText());
        row.put("attributes_json", attributesJson(document.attributes()));
        return row;
    }

    private String attributesJson(Map<String, String> attributes) {
        try {
            return objectMapper.writeValueAsString(attributes == null ? Map.of() : attributes);
        } catch (JsonProcessingException ignored) {
            return "{}";
        }
    }

    private VectorRecallItem toVectorRecallItem(Map<?, ?> row) {
        Object id = firstNonNull(row.get("item_id"), row.get("id"));
        Object distance = firstNonNull(row.get("distance"), row.get("score"));
        double score = distance instanceof Number number ? number.doubleValue() : 0.0;
        return new VectorRecallItem(id == null ? "" : id.toString(), score);
    }

    private Object firstNonNull(Object primary, Object fallback) {
        return primary == null ? fallback : primary;
    }
}
