package com.sinrotic.rs.inventory.domain.entity;

import java.time.LocalDateTime;

public record StockLog(
        Long id,
        String requestId,
        Long orderId,
        String skuId,
        Integer quantity,
        String type,
        LocalDateTime createdAt
) {
}
