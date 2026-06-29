package com.sinrotic.rs.catalog.domain.dto;

public record CatalogItemPageRequestDTO(
        String key,
        Integer limit
) {

    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 50;

    public int normalizedLimit() {
        if (limit == null || limit <= 0) {
            return DEFAULT_LIMIT;
        }
        return Math.min(limit, MAX_LIMIT);
    }

    public String normalizedKey() {
        return key == null ? "" : key.trim();
    }
}
