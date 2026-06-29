package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Request body for isolated rank-stage diagnostics.
 */
public record RankStageRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("candidate_item_ids")
        List<String> candidateItemIds,
        Integer limit
) {

    private static final int DEFAULT_LIMIT = 100;
    private static final int MAX_LIMIT = 100;

    public RankStageRequestDTO withDefaults() {
        int normalizedLimit = limit == null ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        List<String> normalizedCandidateItemIds = candidateItemIds == null ? List.of() : candidateItemIds;
        return new RankStageRequestDTO(requestId, profileUserId, normalizedCandidateItemIds, normalizedLimit);
    }
}
