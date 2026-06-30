package com.sinrotic.rs.inventory.domain.entity;

import java.time.LocalDateTime;

public record SkuStock(
        String skuId,
        String itemId,
        Integer availableStock,
        Integer lockedStock,
        Integer soldStock,
        Long version,
        LocalDateTime updatedAt
) {
}
