package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request body for internal recommendation by resolved profile user.
 */
public record InternalRecommendByProfileUserRequestDTO(
        @JsonProperty("profile_user_id")
        String profileUserId,
        String scene,
        Integer limit,
        @JsonProperty("include_trace")
        Boolean includeTrace
) {

    private static final String DEFAULT_SCENE = "home";
    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 20;

    public InternalRecommendByProfileUserRequestDTO withDefaults() {
        int normalizedLimit = limit == null ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        return new InternalRecommendByProfileUserRequestDTO(
                profileUserId,
                scene == null || scene.isBlank() ? DEFAULT_SCENE : scene,
                normalizedLimit,
                includeTrace != null && includeTrace
        );
    }
}
