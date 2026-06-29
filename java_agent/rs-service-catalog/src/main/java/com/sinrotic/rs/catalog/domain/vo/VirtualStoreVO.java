package com.sinrotic.rs.catalog.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record VirtualStoreVO(
        @JsonProperty("store_id")
        String storeId,
        @JsonProperty("store_name")
        String storeName
) {
}
