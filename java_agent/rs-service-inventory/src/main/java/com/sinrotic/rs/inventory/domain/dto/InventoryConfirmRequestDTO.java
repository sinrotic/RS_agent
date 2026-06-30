package com.sinrotic.rs.inventory.domain.dto;

public record InventoryConfirmRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {
}
