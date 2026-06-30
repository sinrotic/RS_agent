package com.sinrotic.rs.recommend.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * Health status for one recommendation RAG recall provider.
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
