package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RecommendExposureItemDTO(
        @JsonProperty("item_id") String itemId,
        Integer position,
        @JsonProperty("visible_ratio") Double visibleRatio,
        @JsonProperty("visible_duration_ms") Long visibleDurationMs
) {
}
