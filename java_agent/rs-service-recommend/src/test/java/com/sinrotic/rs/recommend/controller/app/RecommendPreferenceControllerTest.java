package com.sinrotic.rs.recommend.controller.app;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.service.impl.DefaultRecommendFeedbackService;
import com.sinrotic.rs.recommend.service.impl.DefaultRecommendationDeliveryService;
import com.sinrotic.rs.recommend.service.impl.InMemoryOnlinePreferenceStore;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationDeliveryStore;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationFeedbackEventStore;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.assertFalse;

class RecommendPreferenceControllerTest {

    @Test
    void longHistoryReportsPartialProgressAndCanContinueWithoutFalseSuccess() {
        var identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var delivery = new DefaultRecommendationDeliveryService(new InMemoryRecommendationDeliveryStore(),
                Clock.systemUTC(), Duration.ofHours(24));
        var item = new RecommendationDeliveryItem("item-1", 1, 0.8, "bags", "Acme", Map.of());
        var preferences = new InMemoryOnlinePreferenceStore();
        var events = new InMemoryRecommendationFeedbackEventStore();
        var feedback = new DefaultRecommendFeedbackService(delivery, events,
                preferences, Clock.systemUTC());
        for (int i = 0; i < 102; i++) {
            String request = "history-" + i;
            delivery.record(request, identity, "home", i, List.of(item));
            feedback.recordEvent(identity, new RecommendEventFeedbackRequestDTO(request, "session-1", "item-1",
                    i % 2 == 0 ? "like" : "dislike", 1.0, System.currentTimeMillis()).withDefaults());
        }
        var controller = new RecommendPreferenceController(new com.sinrotic.rs.recommend.service.impl.PreferenceFactReader(events), feedback);
        var first = controller.deleteItem("account-1", "profile-1", "item-1");
        assertTrue(first.accepted());
        assertFalse(first.operationComplete());
        assertFalse(controller.preferences("profile-1").items().isEmpty());
        assertTrue(controller.deleteItem("account-1", "profile-1", "item-1").operationComplete());
        assertTrue(controller.preferences("profile-1").items().isEmpty());
        assertTrue(controller.deleteItem("account-1", "profile-1", "item-1").operationComplete());
    }

    @Test
    void deletingAnItemRemovesItsWholeEffectivePreferenceHistory() {
        var identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var deliveryService = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
        var item = new RecommendationDeliveryItem("item-1", 1, 0.8, "bags", "Acme", Map.of());
        deliveryService.record("rec-like", identity, "home", 0, List.of(item));
        deliveryService.record("rec-dislike", identity, "home", 1, List.of(item));
        var preferenceStore = new InMemoryOnlinePreferenceStore();
        var events = new InMemoryRecommendationFeedbackEventStore();
        var feedbackService = new DefaultRecommendFeedbackService(
                deliveryService, events, preferenceStore, Clock.systemUTC());
        feedbackService.recordEvent(identity, new RecommendEventFeedbackRequestDTO(
                "rec-like", "session-1", "item-1", "like", 1.0, System.currentTimeMillis()).withDefaults());
        feedbackService.recordEvent(identity, new RecommendEventFeedbackRequestDTO(
                "rec-dislike", "session-1", "item-1", "dislike", -1.0, System.currentTimeMillis()).withDefaults());
        var controller = new RecommendPreferenceController(new com.sinrotic.rs.recommend.service.impl.PreferenceFactReader(events), feedbackService);

        controller.deleteItem("account-1", "profile-1", "item-1");

        assertTrue(controller.preferences("profile-1").items().isEmpty());
    }
}
