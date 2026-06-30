package com.sinrotic.rs.order.client.dto;

public record InventoryReleaseRequestDTO(
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity
) {
}
