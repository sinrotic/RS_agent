package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Request body for Agent-facing recommendation tools.
 */
public record AgentRecommendToolRequestDTO(
        @JsonProperty("agent_id")
        String agentId,
        @JsonProperty("task_id")
        String taskId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        String query,
        @JsonProperty("candidate_item_ids")
        List<String> candidateItemIds,
        @JsonProperty("recall_limit")
        Integer recallLimit,
        @JsonProperty("return_count")
        Integer returnCount,
        @JsonProperty("diversity_required")
        Boolean diversityRequired,
        String scene,
        Map<String, Object> constraints
) {

    private static final String DEFAULT_SCENE = "agent";
    private static final int DEFAULT_RECALL_LIMIT = 100;
    private static final int MAX_RECALL_LIMIT = 200;
    private static final int DEFAULT_RETURN_COUNT = 20;
    private static final int MAX_RETURN_COUNT = 50;

    public AgentRecommendToolRequestDTO withSemanticDefaults() {
        return withDefaults(DEFAULT_RECALL_LIMIT, MAX_RECALL_LIMIT, DEFAULT_RETURN_COUNT, DEFAULT_RETURN_COUNT, false);
    }

    public AgentRecommendToolRequestDTO withProfileDefaults() {
        return withDefaults(null, null, DEFAULT_RETURN_COUNT, MAX_RETURN_COUNT, false);
    }

    public AgentRecommendToolRequestDTO withColdFallbackDefaults() {
        return withDefaults(null, null, DEFAULT_RETURN_COUNT, MAX_RETURN_COUNT, true);
    }

    public AgentRecommendToolRequestDTO withRerankDefaults() {
        return withDefaults(null, null, DEFAULT_RETURN_COUNT, MAX_RETURN_COUNT, false);
    }

    private AgentRecommendToolRequestDTO withDefaults(
            Integer defaultRecallLimit,
            Integer maxRecallLimit,
            int defaultReturnCount,
            int maxReturnCount,
            boolean defaultDiversityRequired
    ) {
        Integer normalizedRecallLimit = null;
        if (defaultRecallLimit != null) {
            int rawRecallLimit = recallLimit == null ? defaultRecallLimit : recallLimit;
            normalizedRecallLimit = Math.min(rawRecallLimit, maxRecallLimit);
        }
        int normalizedReturnCount = returnCount == null ? defaultReturnCount : Math.min(returnCount, maxReturnCount);
        return new AgentRecommendToolRequestDTO(
                agentId,
                taskId,
                sessionId,
                profileUserId,
                query == null ? "" : query,
                candidateItemIds == null ? List.of() : List.copyOf(candidateItemIds),
                normalizedRecallLimit,
                normalizedReturnCount,
                diversityRequired == null ? defaultDiversityRequired : diversityRequired,
                scene == null || scene.isBlank() ? DEFAULT_SCENE : scene,
                constraints == null ? Map.of() : Map.copyOf(constraints)
        );
    }
}
