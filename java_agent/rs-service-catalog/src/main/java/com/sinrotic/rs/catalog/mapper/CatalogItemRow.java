package com.sinrotic.rs.catalog.mapper;

import java.math.BigDecimal;

public record CatalogItemRow(
        String itemId,
        String sourceItemId,
        String title,
        String category,
        String categoryPath,
        String brand,
        String storeName,
        BigDecimal price,
        String imageUrl,
        String summary,
        String description,
        String attributesJson,
        String rawMetadataJson,
        String status
) {
}
