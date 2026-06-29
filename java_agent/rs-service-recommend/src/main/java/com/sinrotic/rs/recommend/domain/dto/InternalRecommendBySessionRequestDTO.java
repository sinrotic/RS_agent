package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Internal request for fetching recommendation results by session.
 */
public record InternalRecommendBySessionRequestDTO(
        @JsonProperty("session_id")
        String sessionId,
        String scene,
        Integer limit,
        @JsonProperty("include_trace")
        Boolean includeTrace
) {

    private static final String DEFAULT_SCENE = "home";
    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 20;

    public InternalRecommendBySessionRequestDTO withDefaults() {
        int normalizedLimit = limit == null ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        return new InternalRecommendBySessionRequestDTO(
                sessionId,
                scene == null || scene.isBlank() ? DEFAULT_SCENE : scene,
                normalizedLimit,
                includeTrace != null && includeTrace
        );
    }
}
