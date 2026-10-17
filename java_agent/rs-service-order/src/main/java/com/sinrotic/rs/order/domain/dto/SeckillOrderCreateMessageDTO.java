package com.sinrotic.rs.order.domain.dto;

public record SeckillOrderCreateMessageDTO(
        String requestId,
        String accountId,
        String activityId,
        String itemId,
        String skuId,
        Integer quantity
) {
}
