package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Safety boundaries for RAG output consumers.
 */
public record RagGovernanceVO(
        @JsonProperty("candidate_generation_allowed")
        boolean candidateGenerationAllowed,
        @JsonProperty("ranking_input_replacement_allowed")
        boolean rankingInputReplacementAllowed,
        @JsonProperty("promotion_allowed")
        boolean promotionAllowed,
        @JsonProperty("public_payload_allowed")
        boolean publicPayloadAllowed
) {
}
