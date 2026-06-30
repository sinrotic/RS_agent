package com.sinrotic.rs.inventory.domain.dto;

public record InventoryLockRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {
}
