package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record RagSupportSnippetVO(
        @JsonProperty("item_id")
        String itemId,
        String field,
        String summary,
        String hint
) {

    public RagSupportSnippetVO(String field, String summary, String hint) {
        this(null, field, summary, hint);
    }
}
