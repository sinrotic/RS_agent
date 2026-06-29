package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Response for the isolated recall stage.
 */
public record PipelineRecallVO(
        @JsonProperty("request_id")
        String requestId,
        String stage,
        @JsonProperty("candidate_count")
        int candidateCount,
        @JsonProperty("source_distribution")
        Map<String, Integer> sourceDistribution,
        List<PipelineCandidateVO> candidates
) {
}
