package com.sinrotic.rs.catalog.domain.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

public record BatchItemIdsRequestDTO(
        @JsonProperty("item_ids")
        List<String> itemIds
) {

    private static final int MAX_ITEM_IDS = 100;

    public List<String> normalizedItemIds() {
        if (itemIds == null) {
            return List.of();
        }
        return itemIds.stream()
                .filter(itemId -> itemId != null && !itemId.isBlank())
                .map(String::trim)
                .limit(MAX_ITEM_IDS)
                .toList();
    }
}
