package com.sinrotic.rs.order.domain.dto;

public record SeckillOrderCreateMessageDTO(
        String requestId,
        Long accountId,
        String activityId,
        String itemId,
        String skuId,
        Integer quantity
) {
}
