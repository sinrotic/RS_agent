package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.Map;

public record PlatformInteractionEventVO(
        @JsonProperty("event_id")
        String eventId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("event_type")
        String eventType,
        @JsonProperty("event_value")
        Double eventValue,
        @JsonProperty("occurred_at")
        Instant occurredAt,
        @JsonProperty("metadata")
        Map<String, Object> metadata
) {
    public PlatformInteractionEventVO {
        metadata = metadata == null ? Map.of() : Map.copyOf(metadata);
        occurredAt = occurredAt == null ? Instant.now() : occurredAt;
    }
}
