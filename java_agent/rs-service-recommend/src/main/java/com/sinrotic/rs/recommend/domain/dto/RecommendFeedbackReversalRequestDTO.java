package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RecommendFeedbackReversalRequestDTO(
        @JsonProperty("feedback_event_id")
        String feedbackEventId
) {
}
