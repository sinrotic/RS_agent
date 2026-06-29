package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Request body for running the recall stage in isolation.
 */
public record RecallRequestDTO(
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("session_id")
        String sessionId,
        Integer limit,
        List<String> sources
) {

    private static final int DEFAULT_LIMIT = 500;
    private static final int MAX_LIMIT = 500;
    private static final List<String> DEFAULT_SOURCES = List.of(
            "itemcf_strong",
            "itemcf_weak",
            "semantic",
            "category",
            "popular"
    );

    public RecallRequestDTO withDefaults() {
        int normalizedLimit = limit == null ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        List<String> normalizedSources = sources == null || sources.isEmpty() ? DEFAULT_SOURCES : sources;
        return new RecallRequestDTO(profileUserId, sessionId, normalizedLimit, normalizedSources);
    }
}
