package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Evidence attached to one item.
 */
public record RagEvidenceItemVO(
        @JsonProperty("item_id")
        String itemId,
        List<RagSupportSnippetVO> evidence
) {
}
