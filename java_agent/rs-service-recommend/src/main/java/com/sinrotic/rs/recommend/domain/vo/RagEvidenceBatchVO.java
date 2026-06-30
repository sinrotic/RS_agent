package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Batch item evidence response.
 */
public record RagEvidenceBatchVO(
        @JsonProperty("request_id")
        String requestId,
        List<RagEvidenceItemVO> items
) {
}
