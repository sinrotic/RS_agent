package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.util.List;

/**
 * Minimal product candidate attributes needed by JavaAgent reasoning.
 */
public record AgentRecommendCandidateItemVO(
        @JsonProperty("item_id")
        String itemId,
        int rank,
        double score,
        String title,
        @JsonProperty("category_path")
        String categoryPath,
        BigDecimal price,
        @JsonProperty("average_rating")
        Double averageRating,
        @JsonProperty("rating_number")
        Integer ratingNumber,
        @JsonProperty("source_tags")
        List<String> sourceTags,
        @JsonProperty("short_text")
        String shortText,
        @JsonProperty("confidence_level")
        String confidenceLevel
) {
}
