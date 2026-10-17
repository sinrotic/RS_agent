package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RecommendPreferenceItemVO(
        @JsonProperty("item_id") String itemId,
        String state,
        String category,
        String brand,
        @JsonProperty("feedback_event_id") String feedbackEventId,
        @JsonProperty("preference_version") long preferenceVersion
) {
}
