package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record AgentRagSupportRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        @JsonProperty("user_query")
        String userQuery,
        @JsonProperty("candidate_item_ids")
        List<String> candidateItemIds,
        String stage,
        @JsonProperty("top_k")
        Integer topK,
        @JsonProperty("rerank_top_k")
        Integer rerankTopK,
        List<String> providers,
        Boolean small2big,
        @JsonProperty("max_support_per_item")
        Integer maxSupportPerItem,
        @JsonProperty("max_text_chars")
        Integer maxTextChars
) {

    private static final String DEFAULT_STAGE = "post_ranking";
    private static final int DEFAULT_TOP_K = 20;
    private static final int DEFAULT_RERANK_TOP_K = 8;
    private static final int DEFAULT_MAX_SUPPORT_PER_ITEM = 3;
    private static final int DEFAULT_MAX_TEXT_CHARS = 1200;
    private static final List<String> DEFAULT_PROVIDERS = List.of("elasticsearch_bm25", "milvus_vector");

    public AgentRagSupportRequestDTO withDefaults() {
        return new AgentRagSupportRequestDTO(
                requestId,
                sessionId,
                userQuery,
                candidateItemIds == null ? List.of() : candidateItemIds,
                stage == null || stage.isBlank() ? DEFAULT_STAGE : stage,
                topK == null ? DEFAULT_TOP_K : Math.max(1, topK),
                rerankTopK == null ? DEFAULT_RERANK_TOP_K : Math.max(1, rerankTopK),
                providers == null || providers.isEmpty() ? DEFAULT_PROVIDERS : providers,
                small2big == null || small2big,
                maxSupportPerItem == null ? DEFAULT_MAX_SUPPORT_PER_ITEM : Math.max(1, maxSupportPerItem),
                maxTextChars == null ? DEFAULT_MAX_TEXT_CHARS : Math.max(1, maxTextChars)
        );
    }
}
