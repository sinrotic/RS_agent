package com.sinrotic.rs.recommend.domain.preference;

import java.time.Instant;
import java.util.Map;

public record ItemPreference(
        String eventId,
        String eventType,
        String itemId,
        String category,
        String brand,
        Map<String, String> attributes,
        long version,
        Instant updatedAt,
        String scope
) {
    public ItemPreference(
            String eventId,
            String eventType,
            String itemId,
            String category,
            String brand,
            Map<String, String> attributes,
            long version,
            Instant updatedAt
    ) {
        this(eventId, eventType, itemId, category, brand, attributes, version, updatedAt, "session");
    }

    public ItemPreference {
        attributes = attributes == null ? Map.of() : Map.copyOf(attributes);
        scope = scope == null || scope.isBlank() ? "session" : scope;
    }
}
