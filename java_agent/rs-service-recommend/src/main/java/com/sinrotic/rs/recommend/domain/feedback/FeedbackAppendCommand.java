package com.sinrotic.rs.recommend.domain.feedback;

import com.sinrotic.rs.recommend.domain.delivery.RecommendationDeliveryItem;
import com.sinrotic.rs.recommend.domain.delivery.RecommendationIdentity;

import java.time.Instant;

public record FeedbackAppendCommand(
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
        RecommendationFeedbackEvent restoredPreferenceEvent
) {
    public FeedbackAppendCommand(
            String requestId,
            RecommendationIdentity identity,
            RecommendationDeliveryItem item,
            FeedbackEventType eventType,
            String reversesEventId,
            Instant occurredAt,
            Instant receivedAt
    ) {
        this(requestId, identity, item, eventType, reversesEventId, occurredAt, receivedAt,
                null, null, null, null);
    }

    public FeedbackAppendCommand(
            String requestId,
            RecommendationIdentity identity,
            RecommendationDeliveryItem item,
            FeedbackEventType eventType,
            String reversesEventId,
            Instant occurredAt,
            Instant receivedAt,
            RecommendationFeedbackEvent restoredPreferenceEvent
    ) {
        this(requestId, identity, item, eventType, reversesEventId, occurredAt, receivedAt,
                null, null, null, restoredPreferenceEvent);
    }

    public String idempotencyKey() {
        return eventType.apiValue() + "|" + identity.profileUserId() + "|" + identity.sessionId()
                + "|" + requestId + "|" + item.itemId()
                + (reversesEventId == null ? "" : "|" + reversesEventId);
    }
}
