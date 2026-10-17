package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.math.BigDecimal;

/**
 * Lightweight display fields used before catalog service card enrichment is available.
 */
public record RecommendDisplayVO(
        String title,
        String category,
        String store,
        @JsonProperty("image_url")
        String imageUrl,
        BigDecimal price
) {
    public RecommendDisplayVO(String title,String category,String store,String imageUrl) {
        this(title,category,store,imageUrl,null);
    }
}
