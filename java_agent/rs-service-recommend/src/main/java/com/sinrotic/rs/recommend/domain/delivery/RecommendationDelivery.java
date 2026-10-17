package com.sinrotic.rs.recommend.domain.delivery;

import java.time.Instant;
import java.util.List;

public record RecommendationDelivery(
        String requestId,
        RecommendationIdentity identity,
        String scene,
        long preferenceVersion,
        List<RecommendationDeliveryItem> items,
        Instant createdAt,
        Instant expiresAt
) {

    public RecommendationDelivery {
        if (requestId == null || requestId.isBlank()) {
            throw new IllegalArgumentException("requestId is required");
        }
        if (identity == null) {
            throw new IllegalArgumentException("identity is required");
        }
        scene = scene == null || scene.isBlank() ? "home" : scene;
        items = items == null ? List.of() : List.copyOf(items);
        if (createdAt == null || expiresAt == null || !expiresAt.isAfter(createdAt)) {
            throw new IllegalArgumentException("delivery timestamps are invalid");
        }
    }

    public boolean containsItem(String itemId) {
        return items.stream().anyMatch(item -> item.itemId().equals(itemId));
    }
}
