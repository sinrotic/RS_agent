package com.sinrotic.rs.order.client.dto;

public record InventoryConfirmRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {
}
