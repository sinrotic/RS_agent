package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Acknowledgement for accepted recommendation feedback.
 */
public record RecommendFeedbackAckVO(
        @JsonProperty("feedback_id")
        String feedbackId,
        boolean accepted,
        @JsonProperty("feedback_type")
        String feedbackType,
        @JsonProperty("accepted_count")
        int acceptedCount
) {
}
