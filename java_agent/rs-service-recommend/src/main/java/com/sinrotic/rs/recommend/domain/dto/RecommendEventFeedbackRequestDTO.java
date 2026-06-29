package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request body for a single recommendation user event.
 */
public record RecommendEventFeedbackRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("event_type")
        String eventType,
        @JsonProperty("event_value")
        Double eventValue,
        @JsonProperty("occurred_at")
        Long occurredAt
) {

    private static final String DEFAULT_EVENT_TYPE = "click";

    public RecommendEventFeedbackRequestDTO withDefaults() {
        return new RecommendEventFeedbackRequestDTO(
                requestId,
                sessionId,
                itemId,
                eventType == null || eventType.isBlank() ? DEFAULT_EVENT_TYPE : eventType,
                eventValue == null ? 1.0 : eventValue,
                occurredAt
        );
    }
}
