package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.domain.vo.HomeRecommendVO;
import com.sinrotic.rs.recommend.domain.vo.RecommendTraceVO;
import com.sinrotic.rs.recommend.service.impl.DefaultHomeRecommendService;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendTraceService;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class DefaultHomeRecommendServiceTest {

    @Test
    void paginationContinuesAfterDislikeWithoutRepeatingReorderedItems() {
        var identity = new com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity("account", "profile", "session");
        var preferences = new com.sinrotic.rs.recommend.service.impl.InMemoryOnlinePreferenceStore();
        preferences.apply(OnlinePreferenceRecoveryTest.event("A", 1,
                com.sinrotic.rs.recommend.domain.feedback.FeedbackEventType.DISLIKE));
        var all = java.util.stream.Stream.of("A", "B", "C", "D", "E")
                .map(id -> new ItemEmbeddingText(id, id, id, "category", "category", "", BigDecimal.ONE, Map.<String, String>of())).toList();
        var service = new DefaultHomeRecommendService(new InMemoryRecommendTraceService(),
                (cursor, limit) -> all.stream().filter(item -> item.itemId().compareTo(cursor) > 0).limit(limit).toList(),
                new com.sinrotic.rs.recommend.service.impl.DefaultRecommendationDeliveryService(
                        new com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationDeliveryStore(),
                        java.time.Clock.systemUTC(), java.time.Duration.ofHours(24)),
                preferences, new com.sinrotic.rs.recommend.service.impl.PreferenceAwareFinalReranker());
        var first = service.recommendHome(identity, new HomeRecommendRequestDTO("session", "home", 2, "", false));
        org.junit.jupiter.api.Assertions.assertTrue(first.hasMore());
        assertEquals(java.util.Set.of("B", "C"), first.items().stream().map(item -> item.itemId()).collect(java.util.stream.Collectors.toSet()));
        assertEquals("C", first.nextCursor());
        var second = service.recommendHome(identity, new HomeRecommendRequestDTO("session", "home", 2, first.nextCursor(), false));
        assertEquals(java.util.Set.of("D", "E"), second.items().stream().map(item -> item.itemId()).collect(java.util.stream.Collectors.toSet()));
        org.junit.jupiter.api.Assertions.assertFalse(second.hasMore());
    }

    @Test
    void recommendHomeStoresTraceForGeneratedRequestId() {
        RecommendTraceService traceService = new InMemoryRecommendTraceService();
        DefaultHomeRecommendService homeRecommendService = new DefaultHomeRecommendService(
                traceService,
                (afterItemId, limit) -> List.of(new ItemEmbeddingText(
                        "REAL-001",
                        "Title: Real product",
                        "Real product",
                        "Accessories",
                        "Accessories",
                        "Example",
                        BigDecimal.TEN,
                        Map.of()
                ))
        );

        HomeRecommendVO response = homeRecommendService.recommendHome(new HomeRecommendRequestDTO(
                "sess_001",
                "home",
                20,
                "",
                false
        ));

        RecommendTraceVO trace = traceService.getTrace(response.requestId());
        assertNotNull(trace);
        assertEquals(response.requestId(), trace.requestId());
        assertEquals("sess_001", trace.sessionId());
        assertEquals("REAL-001", response.items().getFirst().itemId());
        assertEquals(1, trace.stageCounts().get("recall"));
        assertEquals(1, trace.stageCounts().get("coarse_rank"));
        assertEquals(1, trace.stageCounts().get("fine_rank"));
        assertEquals(1, trace.stageCounts().get("final"));
    }
}
