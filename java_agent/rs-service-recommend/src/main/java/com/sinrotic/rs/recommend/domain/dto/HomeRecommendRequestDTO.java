package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Request body for the homepage recommendation entry point.
 */
public record HomeRecommendRequestDTO(
        @JsonProperty("session_id")
        String sessionId,
        String scene,
        @JsonProperty("page_size")
        Integer pageSize,
        String cursor,
        Boolean debug
) {

    private static final String DEFAULT_SCENE = "home";
    private static final int DEFAULT_PAGE_SIZE = 20;
    private static final int MAX_PAGE_SIZE = 20;

    public HomeRecommendRequestDTO withDefaults() {
        int normalizedPageSize = pageSize == null ? DEFAULT_PAGE_SIZE : Math.min(pageSize, MAX_PAGE_SIZE);
        return new HomeRecommendRequestDTO(
                sessionId,
                scene == null || scene.isBlank() ? DEFAULT_SCENE : scene,
                normalizedPageSize,
                cursor == null ? "" : cursor,
                debug != null && debug
        );
    }
}
