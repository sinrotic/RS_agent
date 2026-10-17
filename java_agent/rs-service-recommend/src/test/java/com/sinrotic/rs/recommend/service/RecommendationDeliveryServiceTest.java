package com.sinrotic.rs.recommend.service;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDelivery;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;
import com.sinrotic.rs.recommend.service.impl.DefaultRecommendationDeliveryService;
import com.sinrotic.rs.recommend.service.impl.InMemoryRecommendationDeliveryStore;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class RecommendationDeliveryServiceTest {

    private static final Instant NOW = Instant.parse("2026-08-25T01:00:00Z");

    @Test
    void deliveredItemCanReceiveFeedbackOnlyFromItsTrustedOwner() {
        RecommendationDeliveryService service = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(),
                Clock.fixed(NOW, ZoneOffset.UTC),
                Duration.ofHours(24)
        );
        RecommendationIdentity owner = new RecommendationIdentity("acct-1", "profile-1", "sess-1");
        RecommendationDelivery delivery = service.record(
                "rec-1",
                owner,
                "home",
                7L,
                List.of(new RecommendationDeliveryItem(
                        "B001", 1, 0.8, "Audio / Headphones", "Sony", Map.of("wireless", "true")
                ))
        );

        RecommendationDelivery validated = service.requireFeedbackTarget(owner, "rec-1", "B001");

        assertEquals(delivery, validated);
        RecommendationFeedbackRejectedException error = assertThrows(
                RecommendationFeedbackRejectedException.class,
                () -> service.requireFeedbackTarget(
                        new RecommendationIdentity("acct-2", "profile-1", "sess-1"),
                        "rec-1",
                        "B001"
                )
        );
        assertEquals("DELIVERY_OWNERSHIP_MISMATCH", error.code());
    }

    @Test
    void itemOutsideTheDeliveryCannotPollutePreference() {
        RecommendationDeliveryService service = new DefaultRecommendationDeliveryService(
                new InMemoryRecommendationDeliveryStore(),
                Clock.fixed(NOW, ZoneOffset.UTC),
                Duration.ofHours(24)
        );
        RecommendationIdentity owner = new RecommendationIdentity("acct-1", "profile-1", "sess-1");
        service.record(
                "rec-1",
                owner,
                "home",
                0L,
                List.of(new RecommendationDeliveryItem("B001", 1, 0.0, "Audio", "", Map.of()))
        );

        RecommendationFeedbackRejectedException error = assertThrows(
                RecommendationFeedbackRejectedException.class,
                () -> service.requireFeedbackTarget(owner, "rec-1", "B999")
        );

        assertEquals("ITEM_NOT_DELIVERED", error.code());
    }
}
