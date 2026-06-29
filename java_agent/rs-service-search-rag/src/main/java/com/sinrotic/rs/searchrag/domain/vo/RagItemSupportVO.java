package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Candidate-scoped evidence support for one item.
 */
public record RagItemSupportVO(
        @JsonProperty("item_id")
        String itemId,
        List<RagSupportSnippetVO> support
) {
}
