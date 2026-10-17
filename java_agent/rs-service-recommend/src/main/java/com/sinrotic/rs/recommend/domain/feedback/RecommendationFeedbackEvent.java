package com.sinrotic.rs.recommend.domain.feedback;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;

import java.time.Instant;

public record RecommendationFeedbackEvent(
        String eventId,
        String idempotencyKey,
        String requestId,
        RecommendationIdentity identity,
        RecommendationDeliveryItem item,
        FeedbackEventType eventType,
        String reversesEventId,
        Instant occurredAt,
        Instant receivedAt,
        Integer position,
        Double visibleRatio,
        Long visibleDurationMs,
        long preferenceVersion
) {
    public RecommendationFeedbackEvent(
            String eventId,
            String idempotencyKey,
            String requestId,
            RecommendationIdentity identity,
            RecommendationDeliveryItem item,
            FeedbackEventType eventType,
            String reversesEventId,
            Instant occurredAt,
            Instant receivedAt,
            long preferenceVersion
    ) {
        this(eventId, idempotencyKey, requestId, identity, item, eventType, reversesEventId,
                occurredAt, receivedAt, null, null, null, preferenceVersion);
    }
}
