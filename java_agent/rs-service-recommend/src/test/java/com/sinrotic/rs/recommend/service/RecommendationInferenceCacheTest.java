package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.service.impl.RecommendationInferenceCache;
import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.*;

class RecommendationInferenceCacheTest {
    @Test void repeatedComputationIsImmutableAndQueryModelAndTextChangesMiss() {
        var cache = new RecommendationInferenceCache("embedding-v1", "rank-v1", 1_000_000, 300);
        var count = new AtomicInteger();
        java.util.function.Supplier<List<List<Float>>> embed = () -> { count.incrementAndGet(); return List.of(List.of(.1f, .2f)); };
        var first = cache.embeddings("bge", List.of("query"), embed);
        assertThat(cache.embeddings("bge", List.of("query"), embed)).isEqualTo(first);
        assertThat(count).hasValue(1);
        assertThatThrownBy(() -> first.getFirst().set(0, 5f)).isInstanceOf(UnsupportedOperationException.class);
        cache.embeddings("other-model", List.of("query"), embed);
        cache.embeddings("bge", List.of("other-query"), embed); assertThat(count).hasValue(3);
        var ranked = new AtomicInteger();
        java.util.function.Supplier<Map<String, Double>> rank = () -> { ranked.incrementAndGet(); return Map.of("id", .8); };
        var items = List.of(new RecommendationInferenceCache.TextItem("id", "original text"));
        cache.rankings("query", items, rank); cache.rankings("query", items, rank);
        cache.rankings("query", List.of(new RecommendationInferenceCache.TextItem("id", "changed text")), rank);
        cache.rankings("other query", items, rank); assertThat(ranked).hasValue(3);
    }

    @Test void missingVersionAndOversizedEntryDoNotReuseResults() {
        var calls = new AtomicInteger();
        var cache = RecommendationInferenceCache.disabled();
        for (int i = 0; i < 2; i++) cache.embeddings("bge", List.of("query"), () -> {
            calls.incrementAndGet(); return List.of(List.of(.1f));
        });
        assertThat(calls).hasValue(2);
        var small = new RecommendationInferenceCache("v1", "v1", 1, 300);
        for (int i = 0; i < 2; i++) small.embeddings("bge", List.of("query"), () -> {
            calls.incrementAndGet(); return List.of(List.of(.1f));
        });
        assertThat(calls).hasValue(4);
    }

    @Test void failedOrMalformedEmbeddingIsNotCached() {
        var cache = new RecommendationInferenceCache("v1", "v1", 1_000_000, 300);
        assertThatThrownBy(() -> cache.embeddings("bge", List.of("query"), () -> List.of()))
                .isInstanceOf(IllegalStateException.class);
        assertThatThrownBy(() -> cache.embeddings("bge", List.of("query"), () -> List.of(List.of(Float.NaN))))
                .isInstanceOf(IllegalStateException.class);
        assertThat(cache.embeddings("bge", List.of("query"), () -> List.of(List.of(.3f))))
                .isEqualTo(List.of(List.of(.3f)));
    }

    @Test void eightConcurrentCallersComputeOneSharedEmbedding() throws Exception {
        var cache = new RecommendationInferenceCache("v1", "v1", 1_000_000, 300);
        var ready = new CountDownLatch(8); var start = new CountDownLatch(1); var computing = new CountDownLatch(1);
        var release = new CountDownLatch(1); var calls = new AtomicInteger();
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = new java.util.ArrayList<Future<List<List<Float>>>>();
            for (int i = 0; i < 8; i++) futures.add(workers.submit(() -> {
                ready.countDown();
                if (!start.await(3, TimeUnit.SECONDS)) throw new IllegalStateException("start timed out");
                return cache.embeddings("bge", List.of("same-query"), () -> {
                    calls.incrementAndGet(); computing.countDown();
                    try { if (!release.await(3, TimeUnit.SECONDS)) throw new IllegalStateException("timed out"); }
                    catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); throw new IllegalStateException(interrupted); }
                    return List.of(List.of(.4f));
                });
            }));
            assertThat(ready.await(3, TimeUnit.SECONDS)).isTrue(); start.countDown();
            assertThat(computing.await(3, TimeUnit.SECONDS)).isTrue(); release.countDown();
            for (var future : futures) assertThat(future.get(3, TimeUnit.SECONDS)).isEqualTo(List.of(List.of(.4f)));
            assertThat(calls).hasValue(1);
        } finally { start.countDown(); release.countDown(); }
    }
}
