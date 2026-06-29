package com.sinrotic.rs.catalog.domain.entity;

import java.math.BigDecimal;
import java.util.Map;

/**
 * Stable catalog projection sourced from dataset metadata or rs_catalog_item.
 */
public record CatalogItem(
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
        Map<String, String> attributes,
        String rawMetadataJson,
        String status
) {
}
