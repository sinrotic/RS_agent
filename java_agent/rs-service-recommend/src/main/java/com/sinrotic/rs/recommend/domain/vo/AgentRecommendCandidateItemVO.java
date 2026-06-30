package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;

/**
 * Answer-ready product candidate attributes needed by JavaAgent reasoning.
 */
public record AgentRecommendCandidateItemVO(
        @JsonProperty("item_id")
        String itemId,
        String title,
        @JsonProperty("category_path")
        String categoryPath,
        BigDecimal price,
        @JsonProperty("rating_summary")
        String ratingSummary,
        @JsonProperty("short_text")
        String shortText,
        @JsonProperty("reason_hint")
        String reasonHint
) {
}
