package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.sinrotic.rs.recommend.domain.rag.RagEvidenceHit;
import com.sinrotic.rs.recommend.service.RagRerankClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class RestModelBgeRerankClient implements RagRerankClient {

    private final RestClient restClient;

    public RestModelBgeRerankClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.model.base-url:http://rs-service-model}") String modelBaseUrl
    ) {
        this.restClient = restClientBuilder.baseUrl(modelBaseUrl).build();
    }

    @Override
    public List<RagEvidenceHit> rerank(String modelKey, String requestId, String query, List<RagEvidenceHit> candidates, int limit) {
        if (query == null || query.isBlank() || candidates.isEmpty() || limit <= 0) {
            return List.of();
        }
        Map<String, RagEvidenceHit> byEvidenceId = new LinkedHashMap<>();
        Map<String, RagEvidenceHit> byItemId = new LinkedHashMap<>();
        for (int i = 0; i < candidates.size(); i++) {
            RagEvidenceHit candidate = candidates.get(i);
            byEvidenceId.put(evidenceId(candidate, i), candidate);
            byItemId.putIfAbsent(candidate.itemId(), candidate);
        }
        ModelRankResponse response = restClient.post()
                .uri("/internal/model/rank")
                .body(Map.of(
                        "model_key", modelKey,
                        "request_id", requestId + "_bge_rerank",
                        "inputs", Map.of(
                                "query", query,
                                "candidates", byEvidenceId.entrySet().stream()
                                        .map(entry -> Map.of(
                                                "item_id", entry.getKey(),
                                                "original_item_id", entry.getValue().itemId(),
                                                "text", entry.getValue().text(),
                                                "field", entry.getValue().field(),
                                                "source", entry.getValue().source()
                                        ))
                                        .toList()
                        ),
                        "options", Map.of("top_k", limit)
                ))
                .retrieve()
                .body(ModelRankResponse.class);
        if (response == null || response.items() == null || response.items().isEmpty()) {
            return List.of();
        }
        return response.items().stream()
                .sorted(Comparator.comparingInt(RankedItem::rank))
                .map(item -> firstNonNull(byEvidenceId.get(item.itemId()), byItemId.get(item.itemId())))
                .filter(hit -> hit != null)
                .limit(limit)
                .toList();
    }

    private RagEvidenceHit firstNonNull(RagEvidenceHit primary, RagEvidenceHit fallback) {
        return primary == null ? fallback : primary;
    }

    private String evidenceId(RagEvidenceHit hit, int index) {
        return hit.itemId() + "#" + index;
    }

    private record ModelRankResponse(
            @JsonProperty("request_id")
            String requestId,
            @JsonProperty("model_key")
            String modelKey,
            List<RankedItem> items
    ) {
    }

    private record RankedItem(
            @JsonProperty("item_id")
            String itemId,
            double score,
            int rank,
            Map<String, Object> metadata
    ) {
    }
}
