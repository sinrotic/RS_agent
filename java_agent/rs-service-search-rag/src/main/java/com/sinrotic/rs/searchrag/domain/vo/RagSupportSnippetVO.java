package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * One compressed evidence snippet for Agent grounding.
 */
public record RagSupportSnippetVO(
        String field,
        String summary,
        @JsonProperty("evidence_hint")
        String evidenceHint
) {
}
