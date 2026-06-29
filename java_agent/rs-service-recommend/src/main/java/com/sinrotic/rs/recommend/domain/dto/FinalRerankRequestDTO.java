package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Request body for final rerank diagnostics.
 */
public record FinalRerankRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("profile_user_id")
        String profileUserId,
        @JsonProperty("candidate_item_ids")
        List<String> candidateItemIds,
        @JsonProperty("exclude_item_ids")
        List<String> excludeItemIds,
        Integer limit,
        Map<String, Object> diversity
) {

    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 20;

    public FinalRerankRequestDTO withDefaults() {
        int normalizedLimit = limit == null ? DEFAULT_LIMIT : Math.min(limit, MAX_LIMIT);
        List<String> normalizedCandidateItemIds = candidateItemIds == null ? List.of() : candidateItemIds;
        List<String> normalizedExcludeItemIds = excludeItemIds == null ? List.of() : excludeItemIds;
        Map<String, Object> normalizedDiversity = diversity == null ? Map.of() : diversity;
        return new FinalRerankRequestDTO(
                requestId,
                profileUserId,
                normalizedCandidateItemIds,
                normalizedExcludeItemIds,
                normalizedLimit,
                normalizedDiversity
        );
    }
}
