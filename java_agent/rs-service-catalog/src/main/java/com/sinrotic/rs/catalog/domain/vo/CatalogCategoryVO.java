package com.sinrotic.rs.catalog.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record CatalogCategoryVO(
        @JsonProperty("category_id")
        String categoryId,
        String name
) {
}
