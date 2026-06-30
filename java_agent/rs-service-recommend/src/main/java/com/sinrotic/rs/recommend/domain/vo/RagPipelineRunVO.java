package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Full recommendation RAG pipeline result.
 */
public record RagPipelineRunVO(
        @JsonProperty("request_id")
        String requestId,
        String stage,
        List<RagPipelineProviderStatusVO> providers,
        @JsonProperty("source_distribution")
        Map<String, Integer> sourceDistribution,
        @JsonProperty("stage_counts")
        RagPipelineStageCountsVO stageCounts,
        List<RagSupportSnippetVO> support
) {
}
