package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record SemanticItemIndexResultVO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("collection_name")
        String collectionName,
        @JsonProperty("model_key")
        String modelKey,
        @JsonProperty("indexed_count")
        int indexedCount,
        @JsonProperty("page_count")
        int pageCount,
        @JsonProperty("last_item_id")
        String lastItemId
) {
}
