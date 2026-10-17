package com.sinrotic.rs.recommend.service.impl;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.HomeModelRanker;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import java.util.*;

@Service
public class RestHomeModelRanker implements HomeModelRanker {
    private final RestClient client;
    private final RecommendationInferenceCache cache;
    public RestHomeModelRanker(RestClient.Builder builder, @Value("${rs.model.base-url:http://rs-service-model:18105}") String baseUrl) {
        this(builder, baseUrl, RecommendationInferenceCache.disabled());
    }
    @org.springframework.beans.factory.annotation.Autowired
    public RestHomeModelRanker(RestClient.Builder builder, @Value("${rs.model.base-url:http://rs-service-model:18105}") String baseUrl,
                              RecommendationInferenceCache cache) {
        client = builder.baseUrl(baseUrl).build();
        this.cache = cache;
    }
    @Override public Map<String, Double> score(String requestId, String query, List<ItemEmbeddingText> candidates) {
        var snapshot = List.copyOf(candidates);
        var inputs = snapshot.stream().map(item -> new RecommendationInferenceCache.TextItem(item.itemId(), boundedText(item.embeddingText()))).toList();
        return cache.rankings(query, inputs, () -> compute(requestId, query, snapshot));
    }
    private Map<String, Double> compute(String requestId, String query, List<ItemEmbeddingText> candidates) {
        var response = client.post().uri("/internal/model/rank").body(Map.of(
                "model_key", "bge-reranker-v2-m3", "request_id", requestId + "_home_rank",
                "inputs", Map.of("query", query, "candidates", candidates.stream().map(item -> Map.of(
                        "item_id", item.itemId(), "text", boundedText(item.embeddingText()))).toList()),
                "options", Map.of("top_k", candidates.size()))).retrieve().body(RankResponse.class);
        if (response == null || response.items() == null) throw new IllegalStateException("empty model ranking");
        var expected = candidates.stream().map(ItemEmbeddingText::itemId).collect(java.util.stream.Collectors.toSet());
        Map<String, Double> scores = new HashMap<>();
        for (var item : response.items()) {
            if (!expected.contains(item.itemId()) || !Double.isFinite(item.score()) || scores.containsKey(item.itemId())) {
                throw new IllegalStateException("invalid model ranking identity or score");
            }
            // The deployed CrossEncoder returns sigmoid scores; do not apply sigmoid twice.
            if (item.score() < 0 || item.score() > 1) throw new IllegalStateException("model score is not normalized");
            scores.put(item.itemId(), item.score());
        }
        if (!scores.keySet().equals(expected)) throw new IllegalStateException("incomplete model ranking");
        return Map.copyOf(scores);
    }
    private String boundedText(String text) {
        return text == null ? "" : text.substring(0, Math.min(text.length(), 1200));
    }
    private record RankResponse(List<RankedItem> items) { }
    private record RankedItem(@JsonProperty("item_id") String itemId, double score) { }
}
