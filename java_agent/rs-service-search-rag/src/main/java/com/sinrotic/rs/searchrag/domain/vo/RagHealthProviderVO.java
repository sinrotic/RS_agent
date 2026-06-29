package com.sinrotic.rs.searchrag.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Health status for one RAG recall provider.
 */
public record RagHealthProviderVO(
        String provider,
        String status,
        @JsonProperty("index_name")
        String indexName,
        @JsonProperty("collection_name")
        String collectionName
) {
}
