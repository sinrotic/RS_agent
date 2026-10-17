package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.domain.dto.RecommendEventFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureFeedbackRequestDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendExposureItemDTO;
import com.sinrotic.rs.recommend.domain.dto.RecommendFeedbackReversalRequestDTO;
import com.sinrotic.rs.recommend.domain.feedback.FeedbackApplicationStatus;
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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RecommendFeedbackClosedLoopServiceTest {

    @Test
    void reversingAnOlderLikePreservesTheNewerDislike() {
        var identity = new RecommendationIdentity("account", "profile", "session");
        var delivery = new DefaultRecommendationDeliveryService(new InMemoryRecommendationDeliveryStore(),
                Clock.systemUTC(), Duration.ofHours(24));
        var item = new RecommendationDeliveryItem("A", 1, 1, "bags", "brand", Map.of());
        delivery.record("first", identity, "home", 0, List.of(item));
        delivery.record("second", identity, "home", 1, List.of(item));
        var preferences = new InMemoryOnlinePreferenceStore();
        var service = new DefaultRecommendFeedbackService(delivery, new InMemoryRecommendationFeedbackEventStore(), preferences, Clock.systemUTC());
        var like = service.recordEvent(identity, new RecommendEventFeedbackRequestDTO("first", "session", "A", "like", 1.0, null));
        service.recordEvent(identity, new RecommendEventFeedbackRequestDTO("second", "session", "A", "dislike", -1.0, null));
        service.reverse(identity, new RecommendFeedbackReversalRequestDTO(like.feedbackId()));
        assertEquals("dislike", preferences.load(identity).itemPreferences().get("A").eventType());
    }

    @Test
    void exposureRetainsClientVisibilityEvidenceInTheDurableEvent() {
        RecommendationIdentity identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var deliveryService = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
        deliveryService.record("rec-exposure", identity, "home", 0, List.of(
                new RecommendationDeliveryItem("item-1", 3, 0.8, "bags", "Acme", Map.of())
        ));
        var eventStore = new InMemoryRecommendationFeedbackEventStore();
        var service = new DefaultRecommendFeedbackService(
                deliveryService, eventStore, new InMemoryOnlinePreferenceStore(), Clock.systemUTC());

        var ack = service.recordExposure(identity, new RecommendExposureFeedbackRequestDTO(
                "rec-exposure", "session-1", List.of(), System.currentTimeMillis(),
                List.of(new RecommendExposureItemDTO("item-1", 3, 0.75, 1200L))).withDefaults());

        var event = eventStore.findByEventId(ack.feedbackId()).orElseThrow();
        assertEquals(3, event.position());
        assertEquals(0.75, event.visibleRatio());
        assertEquals(1200L, event.visibleDurationMs());
    }

    @Test
    void explicitFeedbackAllocatesOneVersionAndIsIdempotent() {
        RecommendationIdentity identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var deliveryService = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
        deliveryService.record("rec-1", identity, "home", 0, List.of(
                new RecommendationDeliveryItem("item-1", 1, 0.8, "bags", "Acme", Map.of("color", "black"))
        ));
        var eventStore = new InMemoryRecommendationFeedbackEventStore();
        var preferences = new InMemoryOnlinePreferenceStore();
        var service = new DefaultRecommendFeedbackService(deliveryService, eventStore, preferences, Clock.systemUTC());
        var request = new RecommendEventFeedbackRequestDTO(
                "rec-1", "session-1", "item-1", "like", 1.0, System.currentTimeMillis()).withDefaults();

        var first = service.recordEvent(identity, request);
        var duplicate = service.recordEvent(identity, request);

        assertEquals(FeedbackApplicationStatus.APPLIED.name(), first.applicationStatus());
        assertEquals(1L, first.preferenceVersion());
        assertEquals(first.feedbackId(), duplicate.feedbackId());
        assertTrue(duplicate.duplicate());
        assertEquals(1L, preferences.load(identity).version());
        assertEquals("like", preferences.load(identity).itemPreferences().get("item-1").eventType());
    }

    @Test
    void whyIsDurableButDoesNotChangePreferenceVersion() {
        RecommendationIdentity identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var deliveryService = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
        deliveryService.record("rec-2", identity, "home", 0, List.of(
                new RecommendationDeliveryItem("item-2", 1, 0.8, "bags", "Acme", Map.of())
        ));
        var preferences = new InMemoryOnlinePreferenceStore();
        var service = new DefaultRecommendFeedbackService(
                deliveryService, new InMemoryRecommendationFeedbackEventStore(), preferences, Clock.systemUTC());

        var ack = service.recordEvent(identity, new RecommendEventFeedbackRequestDTO(
                "rec-2", "session-1", "item-2", "why", 1.0, System.currentTimeMillis()).withDefaults());

        assertEquals(FeedbackApplicationStatus.NOT_APPLICABLE.name(), ack.applicationStatus());
        assertEquals(0L, ack.preferenceVersion());
        assertEquals(0L, preferences.load(identity).version());
    }

    @Test
    void reversalRemovesCurrentExplicitPreferenceAndAllocatesNewVersion() {
        RecommendationIdentity identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var deliveryService = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
        deliveryService.record("rec-3", identity, "home", 0, List.of(
                new RecommendationDeliveryItem("item-3", 1, 0.8, "bags", "Acme", Map.of())
        ));
        var preferences = new InMemoryOnlinePreferenceStore();
        var service = new DefaultRecommendFeedbackService(
                deliveryService, new InMemoryRecommendationFeedbackEventStore(), preferences, Clock.systemUTC());
        var like = service.recordEvent(identity, new RecommendEventFeedbackRequestDTO(
                "rec-3", "session-1", "item-3", "like", 1.0, System.currentTimeMillis()).withDefaults());

        var reversal = service.reverse(identity, new RecommendFeedbackReversalRequestDTO(like.feedbackId()));

        assertEquals(FeedbackApplicationStatus.APPLIED.name(), reversal.applicationStatus());
        assertEquals(2L, reversal.preferenceVersion());
        assertFalse(preferences.load(identity).itemPreferences().containsKey("item-3"));
    }

    @Test
    void reversalRestoresThePreviousEffectiveExplicitPreference() {
        RecommendationIdentity identity = new RecommendationIdentity("account-1", "profile-1", "session-1");
        var deliveryService = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(), Clock.systemUTC(), Duration.ofHours(24));
        RecommendationDeliveryItem item = new RecommendationDeliveryItem(
                "item-4", 1, 0.8, "bags", "Acme", Map.of());
        deliveryService.record("rec-4-like", identity, "home", 0, List.of(item));
        deliveryService.record("rec-4-dislike", identity, "home", 1, List.of(item));
        var preferences = new InMemoryOnlinePreferenceStore();
        var service = new DefaultRecommendFeedbackService(
                deliveryService, new InMemoryRecommendationFeedbackEventStore(), preferences, Clock.systemUTC());
        service.recordEvent(identity, new RecommendEventFeedbackRequestDTO(
                "rec-4-like", "session-1", "item-4", "like", 1.0, System.currentTimeMillis()).withDefaults());
        var dislike = service.recordEvent(identity, new RecommendEventFeedbackRequestDTO(
                "rec-4-dislike", "session-1", "item-4", "dislike", -1.0, System.currentTimeMillis()).withDefaults());

        var reversal = service.reverse(identity, new RecommendFeedbackReversalRequestDTO(dislike.feedbackId()));

        assertEquals(3L, reversal.preferenceVersion());
        assertEquals("like", preferences.load(identity).itemPreferences().get("item-4").eventType());
    }
}
