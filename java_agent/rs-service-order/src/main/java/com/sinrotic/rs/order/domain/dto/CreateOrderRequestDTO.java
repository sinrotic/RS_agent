package com.sinrotic.rs.order.domain.dto;

public record CreateOrderRequestDTO(
        String requestId,
        Long accountId,
        String profileUserId,
        String sessionId,
        String recommendRequestId,
        String itemId,
        String skuId,
        String itemTitle,
        Integer quantity,
        Long unitPrice
) {
}
