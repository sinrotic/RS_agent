package com.sinrotic.rs.catalog.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.util.Map;

public record CatalogItemEmbeddingTextVO(
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("embedding_text")
        String embeddingText,
        String title,
        String category,
        @JsonProperty("category_path")
        String categoryPath,
        String brand,
        BigDecimal price,
        Map<String, String> attributes
) {
}
