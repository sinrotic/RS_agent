package com.sinrotic.rs.order.client.dto;

public record InventoryLockRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {
}
