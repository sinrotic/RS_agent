package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Request body for recommendation exposure feedback.
 */
public record RecommendExposureFeedbackRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("item_ids")
        List<String> itemIds,
        @JsonProperty("exposed_at")
        Long exposedAt
) {

    public RecommendExposureFeedbackRequestDTO withDefaults() {
        return new RecommendExposureFeedbackRequestDTO(
                requestId,
                sessionId,
                itemIds == null ? List.of() : itemIds,
                exposedAt
        );
    }
}
