package com.sinrotic.rs.inventory.domain.dto;

public record InventoryReleaseRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {
}
