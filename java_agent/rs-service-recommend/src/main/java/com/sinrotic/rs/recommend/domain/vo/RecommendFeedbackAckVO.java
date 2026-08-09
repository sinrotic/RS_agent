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
        int acceptedCount,
        boolean duplicate
) {

    public RecommendFeedbackAckVO(String feedbackId, boolean accepted, String feedbackType, int acceptedCount) {
        this(feedbackId, accepted, feedbackType, acceptedCount, false);
    }
}
