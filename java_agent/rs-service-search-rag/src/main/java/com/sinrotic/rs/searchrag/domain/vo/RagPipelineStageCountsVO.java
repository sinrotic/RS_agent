package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Counts for major RAG pipeline stages.
 */
public record RagPipelineStageCountsVO(
        @JsonProperty("raw_recall_count")
        int rawRecallCount,
        @JsonProperty("merged_count")
        int mergedCount,
        @JsonProperty("rerank_count")
        int rerankCount,
        @JsonProperty("small2big_count")
        int small2bigCount,
        @JsonProperty("compressed_support_count")
        int compressedSupportCount
) {
}
