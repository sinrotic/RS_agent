package com.sinrotic.rs.catalog.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.util.Map;

public record CatalogItemDetailVO(
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("source_item_id")
        String sourceItemId,
        String title,
        String category,
        @JsonProperty("category_path")
        String categoryPath,
        String brand,
        @JsonProperty("store_name")
        String storeName,
        BigDecimal price,
        @JsonProperty("image_url")
        String imageUrl,
        String summary,
        String description,
        Map<String, String> attributes
) {
}
