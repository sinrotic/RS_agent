package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * One ranked recommendation item.
 */
public record RecommendItemVO(
        @JsonProperty("item_id")
        String itemId,
        int rank,
        double score,
        String reason,
        @JsonProperty("source_tags")
        List<String> sourceTags,
        RecommendDisplayVO display
) {
}
