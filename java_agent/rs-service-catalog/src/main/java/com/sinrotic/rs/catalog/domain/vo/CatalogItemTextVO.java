package com.sinrotic.rs.catalog.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record CatalogItemTextVO(
        @JsonProperty("item_id")
        String itemId,
        String text
) {
}
