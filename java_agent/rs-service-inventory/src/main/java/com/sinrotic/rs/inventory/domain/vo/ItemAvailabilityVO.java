package com.sinrotic.rs.inventory.domain.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

public record ItemAvailabilityVO(
        @JsonProperty("item_id")
        String itemId,
        @JsonProperty("sku_count")
        Integer skuCount,
        @JsonProperty("available_stock")
        Integer availableStock
) {

    @JsonProperty("available")
    public boolean available() {
        return availableStock != null && availableStock > 0;
    }
}
