package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record RagItemSupportVO(
        @JsonProperty("item_id")
        String itemId,
        List<RagSupportSnippetVO> snippets
) {
    public RagItemSupportVO {
        snippets = snippets == null ? List.of() : List.copyOf(snippets);
    }
}
