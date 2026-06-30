package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Request for running the recommendation RAG evidence pipeline.
 */
public record RagPipelineRunRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("session_id")
        String sessionId,
        String query,
        @JsonProperty("candidate_item_ids")
        List<String> candidateItemIds,
        List<String> providers,
        @JsonProperty("top_k_per_provider")
        Integer topKPerProvider,
        @JsonProperty("merged_top_k")
        Integer mergedTopK,
        @JsonProperty("rerank_top_k")
        Integer rerankTopK,
        Boolean small2big
) {

    private static final int DEFAULT_TOP_K_PER_PROVIDER = 50;
    private static final int DEFAULT_MERGED_TOP_K = 80;
    private static final int DEFAULT_RERANK_TOP_K = 8;
    private static final List<String> DEFAULT_PROVIDERS = List.of("elasticsearch_bm25", "milvus_vector");

    public RagPipelineRunRequestDTO withDefaults() {
        return new RagPipelineRunRequestDTO(
                requestId,
                sessionId,
                query,
                candidateItemIds == null ? List.of() : candidateItemIds,
                providers == null || providers.isEmpty() ? DEFAULT_PROVIDERS : providers,
                topKPerProvider == null ? DEFAULT_TOP_K_PER_PROVIDER : Math.max(1, topKPerProvider),
                mergedTopK == null ? DEFAULT_MERGED_TOP_K : Math.max(1, mergedTopK),
                rerankTopK == null ? DEFAULT_RERANK_TOP_K : Math.max(1, rerankTopK),
                small2big == null || small2big
        );
    }
}
