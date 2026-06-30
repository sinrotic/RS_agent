package com.sinrotic.rs.order.service.seckill;

import com.sinrotic.rs.order.service.OrderServiceException;

public record SeckillOrderItemSnapshot(
        String itemId,
        String itemTitle,
        Long unitPrice
) {

    public SeckillOrderItemSnapshot {
        if (itemId == null || itemId.isBlank()) {
            throw new OrderServiceException("seckill itemId is required");
        }
        if (itemTitle == null || itemTitle.isBlank()) {
            throw new OrderServiceException("seckill item title is required");
        }
        if (unitPrice == null || unitPrice <= 0) {
            throw new OrderServiceException("seckill item unitPrice must be positive");
        }
        itemId = itemId.trim();
        itemTitle = itemTitle.trim();
    }
}
