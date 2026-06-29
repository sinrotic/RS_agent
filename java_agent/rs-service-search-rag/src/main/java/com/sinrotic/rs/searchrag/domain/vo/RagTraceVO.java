package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Platform-facing RAG pipeline trace summary.
 */
public record RagTraceVO(
        @JsonProperty("request_id")
        String requestId,
        String query,
        @JsonProperty("query_rewrite")
        String queryRewrite,
        List<RagPipelineProviderStatusVO> providers,
        @JsonProperty("source_distribution")
        Map<String, Integer> sourceDistribution,
        @JsonProperty("stage_counts")
        RagPipelineStageCountsVO stageCounts,
        @JsonProperty("fallback_reason")
        String fallbackReason,
        @JsonProperty("latency_ms")
        long latencyMs
) {
}
