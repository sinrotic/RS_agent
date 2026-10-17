package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.dto.HomeRecommendRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.recall.ItemEmbeddingText;
import com.sinrotic.rs.recommend.service.impl.DefaultHomeRecommendService;
import com.sinrotic.rs.recommend.service.impl.DefaultRecommendFeedbackService;
import com.sinrotic.rs.recommend.service.impl.DefaultRecommendationDeliveryService;
import com.sinrotic.rs.recommend.service.impl.InMemoryOnlinePreferenceStore;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationDeliveryStore;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationFeedbackEventStore;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendTraceService;
import com.sinrotic.rs.recommend.service.impl.PreferenceAwareFinalReranker;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OnlineFeedbackVerticalSliceTest {

    @Test
    void dislikeIsAppliedAndTheDeliveredItemDisappearsFromTheNextRecommendation() {
        var identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var deliveryService = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
        var preferences = new InMemoryOnlinePreferenceStore();
        var events = new InMemoryRecommendationFeedbackEventStore();
        var home = new DefaultHomeRecommendService(
                new InMemoryRecommendTraceService(),
                (cursor, limit) -> List.of(item("item-1", "Acme"), item("item-2", "Other")),
                deliveryService,
                preferences,
                new PreferenceAwareFinalReranker());
        var feedback = new DefaultRecommendFeedbackService(
                deliveryService, events, preferences, Clock.systemUTC());
        var request = new HomeRecommendRequestDTO("session-1", "home", 20, "", false);

        var first = home.recommendHome(identity, request);
        var ack = feedback.recordEvent(identity, new RecommendEventFeedbackRequestDTO(
                first.requestId(), "session-1", "item-1", "dislike", -1.0,
                System.currentTimeMillis()).withDefaults());
        var second = home.recommendHome(identity, request);

        assertEquals("APPLIED", ack.applicationStatus());
        assertFalse(second.items().stream().anyMatch(item -> item.itemId().equals("item-1")));
        assertTrue(second.items().stream().anyMatch(item -> item.itemId().equals("item-2")));
        assertEquals(ack.preferenceVersion(), second.preferenceVersion());
        assertTrue(second.appliedFeedbackEventIds().contains(ack.feedbackId()));
    }

    private ItemEmbeddingText item(String itemId, String brand) {
        return new ItemEmbeddingText(
                itemId, itemId, itemId, "Bags", "Bags", brand, BigDecimal.TEN, Map.of());
    }
}
