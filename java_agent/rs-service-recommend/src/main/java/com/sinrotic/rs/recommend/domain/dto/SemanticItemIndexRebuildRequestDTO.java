package com.sinrotic.rs.recommend.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record SemanticItemIndexRebuildRequestDTO(
        @JsonProperty("request_id")
        String requestId,
        @JsonProperty("page_size")
        Integer pageSize,
        @JsonProperty("max_pages")
        Integer maxPages
) {

    private static final int DEFAULT_PAGE_SIZE = 100;
    private static final int MAX_PAGE_SIZE = 1000;
    private static final int DEFAULT_MAX_PAGES = 1000;

    public SemanticItemIndexRebuildRequestDTO withDefaults() {
        int normalizedPageSize = pageSize == null ? DEFAULT_PAGE_SIZE : Math.min(Math.max(pageSize, 1), MAX_PAGE_SIZE);
        int normalizedMaxPages = maxPages == null ? DEFAULT_MAX_PAGES : Math.max(maxPages, 1);
        return new SemanticItemIndexRebuildRequestDTO(
                requestId == null || requestId.isBlank() ? "semantic_item_index_rebuild" : requestId,
                normalizedPageSize,
                normalizedMaxPages
        );
    }
}
