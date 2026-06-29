package com.sinrotic.rs.platformtrace.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.Instant;
import java.util.Map;

public record PlatformTimelineEventVO(
        @JsonProperty("event_id")
        String eventId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("event_type")
        String eventType,
        @JsonProperty("source")
        String source,
        @JsonProperty("entity_id")
        String entityId,
        @JsonProperty("summary")
        String summary,
        @JsonProperty("occurred_at")
        Instant occurredAt,
        @JsonProperty("data")
        Map<String, Object> data
) {
    public PlatformTimelineEventVO {
        data = data == null ? Map.of() : Map.copyOf(data);
        occurredAt = occurredAt == null ? Instant.now() : occurredAt;
    }
}
