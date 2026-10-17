package com.sinrotic.rs.recommend.service.impl;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/** Bounded computation caches. No user ranking, deliveries, prices or final results are cached. */
@Component
public final class RecommendationInferenceCache implements io.micrometer.core.instrument.binder.MeterBinder {
    private final String embeddingVersion;
    private final String rerankerVersion;
    private final long maxBytes;
    private final Cache<EmbeddingKey, List<List<Float>>> embeddings;
    private final Cache<RankingKey, Map<String, Double>> rankings;

    public RecommendationInferenceCache(
            @Value("${rs.recommend.inference-cache.embedding-version:${RS_RECOMMEND_INFERENCE_CACHE_EMBEDDING_VERSION:}}") String embeddingVersion,
            @Value("${rs.recommend.inference-cache.reranker-version:${RS_RECOMMEND_INFERENCE_CACHE_RERANKER_VERSION:}}") String rerankerVersion,
            @Value("${rs.recommend.inference-cache.max-bytes:${RS_RECOMMEND_INFERENCE_CACHE_MAX_BYTES:33554432}}") long maxBytes,
            @Value("${rs.recommend.inference-cache.ttl-seconds:${RS_RECOMMEND_INFERENCE_CACHE_TTL_SECONDS:300}}") long ttlSeconds) {
        this.embeddingVersion = embeddingVersion;
        this.rerankerVersion = rerankerVersion;
        this.maxBytes = maxBytes;
        if (maxBytes <= 0 || ttlSeconds <= 0) throw new IllegalArgumentException("invalid inference cache budget");
        embeddings = Caffeine.newBuilder().maximumWeight(maxBytes)
                .weigher((EmbeddingKey key, List<List<Float>> value) -> boundedWeight(
                        128L + key.texts().stream().mapToLong(text -> 2L * text.length() + 64).sum()
                                + value.stream().mapToLong(vector -> 24L * vector.size() + 64).sum()))
                .recordStats().expireAfterWrite(Duration.ofSeconds(ttlSeconds)).build();
        rankings = Caffeine.newBuilder().maximumWeight(maxBytes)
                .weigher((RankingKey key, Map<String, Double> value) -> boundedWeight(
                        128L + 2L * key.query().length() + key.items().stream().mapToLong(item ->
                                64L + 2L * item.id().length() + 2L * item.text().length()).sum()
                                + value.size() * 64L))
                .recordStats().expireAfterWrite(Duration.ofSeconds(ttlSeconds)).build();
    }

    public static RecommendationInferenceCache disabled() {
        return new RecommendationInferenceCache("", "", 33554432, 300);
    }

    public List<List<Float>> embeddings(String model, List<String> texts, Supplier<List<List<Float>>> compute) {
        if (embeddingVersion.isBlank() || 128L + texts.stream().mapToLong(text -> 2L * text.length() + 64).sum() > maxBytes)
            return compute.get();
        var key = new EmbeddingKey(model, embeddingVersion, List.copyOf(texts));
        var result = embeddings.get(key, ignored -> {
            var vectors = compute.get();
            if (vectors.size() != key.texts().size() || vectors.isEmpty() || vectors.getFirst().isEmpty()
                    || vectors.stream().anyMatch(vector -> vector.size() != vectors.getFirst().size()
                        || vector.stream().anyMatch(number -> number == null || !Float.isFinite(number))))
                throw new IllegalStateException("invalid embedding result");
            return vectors.stream().map(List::copyOf).toList();
        });
        if (128L + key.texts().stream().mapToLong(text -> 2L * text.length() + 64).sum()
                + result.stream().mapToLong(vector -> 24L * vector.size() + 64).sum() > maxBytes)
            embeddings.invalidate(key);
        return result;
    }

    public Map<String, Double> rankings(String query, List<TextItem> items, Supplier<Map<String, Double>> compute) {
        long inputBytes = 128L + 2L * query.length() + items.stream().mapToLong(item ->
                64L + 2L * item.id().length() + 2L * item.text().length()).sum();
        if (rerankerVersion.isBlank() || inputBytes > maxBytes) return compute.get();
        var key = new RankingKey(rerankerVersion, query, List.copyOf(items));
        var result = rankings.get(key, ignored -> Map.copyOf(compute.get()));
        if (inputBytes + result.size() * 64L > maxBytes) rankings.invalidate(key);
        return result;
    }

    private static int boundedWeight(long value) { return (int) Math.min(Integer.MAX_VALUE, value); }
    @Override public void bindTo(io.micrometer.core.instrument.MeterRegistry registry) {
        io.micrometer.core.instrument.binder.cache.CaffeineCacheMetrics.monitor(registry, embeddings, "recommend_query_embedding");
        io.micrometer.core.instrument.binder.cache.CaffeineCacheMetrics.monitor(registry, rankings, "recommend_bge_scores");
    }
    public record TextItem(String id, String text) { }
    private record EmbeddingKey(String model, String version, List<String> texts) { }
    private record RankingKey(String version, String query, List<TextItem> items) { }
}
