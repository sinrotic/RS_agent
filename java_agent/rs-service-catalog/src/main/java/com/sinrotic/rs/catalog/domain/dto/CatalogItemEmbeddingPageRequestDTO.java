package com.sinrotic.rs.catalog.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record CatalogItemEmbeddingPageRequestDTO(
        @JsonProperty("after_item_id")
        String afterItemId,
        Integer limit
) {

    private static final int DEFAULT_LIMIT = 500;
    private static final int MAX_LIMIT = 1000;

    public CatalogItemEmbeddingPageRequestDTO withDefaults() {
        int normalizedLimit = limit == null ? DEFAULT_LIMIT : Math.min(Math.max(limit, 1), MAX_LIMIT);
        return new CatalogItemEmbeddingPageRequestDTO(
                afterItemId == null || afterItemId.isBlank() ? null : afterItemId,
                normalizedLimit
        );
    }
}
