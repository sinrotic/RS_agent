package com.sinrotic.rs.catalog.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;

public record CatalogItemCardVO(
        @JsonProperty("item_id")
        String itemId,
        String title,
        String category,
        String brand,
        @JsonProperty("store_name")
        String storeName,
        BigDecimal price,
        @JsonProperty("image_url")
        String imageUrl,
        String summary
) {
}
