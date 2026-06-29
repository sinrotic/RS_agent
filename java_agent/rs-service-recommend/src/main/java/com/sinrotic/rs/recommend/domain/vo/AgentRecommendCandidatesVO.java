package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Agent-facing recommendation candidates.
 */
public record AgentRecommendCandidatesVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("agent_id")
        String agentId,
        @JsonProperty("task_id")
        String taskId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        List<AgentRecommendCandidateItemVO> candidates
) {
}
