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
        boolean duplicate,
        @JsonProperty("application_status")
        String applicationStatus,
        @JsonProperty("preference_version")
        long preferenceVersion,
        @JsonProperty("operation_complete")
        Boolean operationComplete
) {

    public RecommendFeedbackAckVO(String feedbackId, boolean accepted, String feedbackType, int acceptedCount,
            boolean duplicate, String applicationStatus, long preferenceVersion) {
        this(feedbackId, accepted, feedbackType, acceptedCount, duplicate, applicationStatus, preferenceVersion, null);
    }

    public RecommendFeedbackAckVO withOperationComplete(boolean complete) {
        return new RecommendFeedbackAckVO(feedbackId, accepted, feedbackType, acceptedCount,
                duplicate, applicationStatus, preferenceVersion, complete);
    }

    public RecommendFeedbackAckVO(String feedbackId, boolean accepted, String feedbackType, int acceptedCount) {
        this(feedbackId, accepted, feedbackType, acceptedCount, false, "NOT_APPLICABLE", 0L);
    }

    public RecommendFeedbackAckVO(
            String feedbackId,
            boolean accepted,
            String feedbackType,
            int acceptedCount,
            boolean duplicate
    ) {
        this(feedbackId, accepted, feedbackType, acceptedCount, duplicate, "NOT_APPLICABLE", 0L);
    }
}
