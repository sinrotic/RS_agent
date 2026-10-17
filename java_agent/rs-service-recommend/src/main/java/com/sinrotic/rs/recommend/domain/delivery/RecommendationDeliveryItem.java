package com.sinrotic.rs.recommend.domain.delivery;

import java.util.Map;

public record RecommendationDeliveryItem(
        String itemId,
        int rank,
        double baseScore,
        String category,
        String brand,
        Map<String, String> attributes
) {

    public RecommendationDeliveryItem {
        if (itemId == null || itemId.isBlank()) {
            throw new IllegalArgumentException("itemId is required");
        }
        if (rank <= 0) {
            throw new IllegalArgumentException("rank must be positive");
        }
        category = category == null ? "" : category;
        brand = brand == null ? "" : brand;
        attributes = attributes == null ? Map.of() : Map.copyOf(attributes);
    }
}
