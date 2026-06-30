package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Evidence attached to one recommendation candidate item.
 */
public record RagEvidenceItemVO(
        @JsonProperty("item_id")
        String itemId,
        List<RagSupportSnippetVO> evidence
) {
}
