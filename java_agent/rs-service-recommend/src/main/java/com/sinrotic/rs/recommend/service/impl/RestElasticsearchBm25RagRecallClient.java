package com.sinrotic.rs.recommend.service.impl;

import com.sinrotic.rs.recommend.domain.dto.RagPipelineRunRequestDTO;
import com.sinrotic.rs.recommend.domain.rag.RagEvidenceHit;
import com.sinrotic.rs.recommend.service.RagEvidenceRecallClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class RestElasticsearchBm25RagRecallClient implements RagEvidenceRecallClient {

    private static final String PROVIDER = "elasticsearch_bm25";

    private final RestClient restClient;
    private final String indexName;

    public RestElasticsearchBm25RagRecallClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.elasticsearch.base-url:http://127.0.0.1:9200}") String elasticsearchBaseUrl,
            @Value("${rs.recommend.rag.elasticsearch-index:rs_agent_rag_bm25_v1}") String indexName
    ) {
        this.restClient = restClientBuilder.baseUrl(elasticsearchBaseUrl).build();
        this.indexName = indexName;
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
        Map<String, Object> response = restClient.post()
                .uri("/" + indexName + "/_search")
                .body(searchBody(request))
                .retrieve()
                .body(Map.class);
        Object hits = response == null ? null : response.get("hits");
        Object rawRows = hits instanceof Map<?, ?> map ? map.get("hits") : null;
        if (!(rawRows instanceof List<?> rows)) {
            return List.of();
        }
        List<RagEvidenceHit> results = new ArrayList<>();
        int rank = 1;
        for (Object row : rows) {
            if (!(row instanceof Map<?, ?> hit)) {
                continue;
            }
            Object source = hit.get("_source");
            if (!(source instanceof Map<?, ?> payload)) {
                continue;
            }
            String itemId = text(payload.get("item_id"));
            String field = text(payload.get("field"));
            String text = text(payload.get("text"));
            if (itemId.isBlank() || text.isBlank()) {
                continue;
            }
            double score = number(hit.get("_score"));
            results.add(new RagEvidenceHit(
                    PROVIDER,
                    itemId,
                    field,
                    text,
                    firstText(payload.get("source_name"), payload.get("source"), "catalog_rag_chunk"),
                    score,
                    rank++,
                    metadata(payload)
            ));
        }
        return results;
    }

    private Map<String, Object> searchBody(RagPipelineRunRequestDTO request) {
        return Map.of(
                "size", request.topKPerProvider(),
                "_source", List.of(
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
                ),
                "query", Map.of(
                        "bool", Map.of(
                                "must", List.of(Map.of(
                                        "multi_match", Map.of(
                                                "query", request.query(),
                                                "fields", List.of("text^3", "title^2", "summary", "description")
                                        )
                                )),
                                "filter", List.of(Map.of("terms", Map.of("item_id", request.candidateItemIds())))
                        )
                )
        );
    }

    private Map<String, Object> metadata(Map<?, ?> payload) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        metadata.put("es_index", indexName);
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
