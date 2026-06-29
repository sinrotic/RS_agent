package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Candidate item emitted by one recommendation pipeline stage.
 */
public record PipelineCandidateVO(
        @JsonProperty("item_id")
        String itemId,
        String source,
        @JsonProperty("recall_score")
        Double recallScore,
        @JsonProperty("coarse_score")
        Double coarseScore,
        @JsonProperty("fine_score")
        Double fineScore,
        @JsonProperty("final_score")
        Double finalScore
) {
}
