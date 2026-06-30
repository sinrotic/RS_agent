package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Request for item-scoped recommendation evidence lookup.
 */
public record RagBatchEvidenceRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("item_ids")
        List<String> itemIds,
        @JsonProperty("max_support_per_item")
        Integer maxSupportPerItem,
        @JsonProperty("max_text_chars")
        Integer maxTextChars,
        @JsonProperty("include_parent_profile")
        Boolean includeParentProfile
) {

    private static final int DEFAULT_MAX_SUPPORT_PER_ITEM = 3;
    private static final int DEFAULT_MAX_TEXT_CHARS = 220;

    public RagBatchEvidenceRequestDTO withDefaults() {
        return new RagBatchEvidenceRequestDTO(
                requestId,
                itemIds == null ? List.of() : itemIds,
                maxSupportPerItem == null ? DEFAULT_MAX_SUPPORT_PER_ITEM : Math.max(1, maxSupportPerItem),
                maxTextChars == null ? DEFAULT_MAX_TEXT_CHARS : Math.max(1, maxTextChars),
                includeParentProfile == null || includeParentProfile
        );
    }
}
