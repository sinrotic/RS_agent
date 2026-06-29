package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.Map;

/**
 * Request body for agent-facing recommendation candidates.
 */
public record AgentRecommendCandidatesRequestDTO(
        @JsonProperty("agent_id")
        String agentId,
        @JsonProperty("task_id")
        String taskId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        String scene,
        Integer limit,
        Map<String, Object> constraints
) {

    private static final String DEFAULT_SCENE = "home";
    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 20;

    public AgentRecommendCandidatesRequestDTO withDefaults() {
        int normalizedLimit = limit == null ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        return new AgentRecommendCandidatesRequestDTO(
                agentId,
                taskId,
                profileUserId,
                scene == null || scene.isBlank() ? DEFAULT_SCENE : scene,
                normalizedLimit,
                constraints == null ? Map.of() : constraints
        );
    }
}
