package com.sinrotic.rs.order.domain.dto;

public record CreateOrderRequestDTO(
        String requestId,
        String accountId,
        String profileUserId,
        String sessionId,
        String recommendRequestId,
        String itemId,
        String skuId,
        String itemTitle,
        Integer quantity,
        Long unitPrice,
        String couponId
) {
    public CreateOrderRequestDTO(String requestId, String accountId, String profileUserId, String sessionId,
            String recommendRequestId, String itemId, String skuId, String itemTitle, Integer quantity, Long unitPrice) {
        this(requestId,accountId,profileUserId,sessionId,recommendRequestId,itemId,skuId,itemTitle,quantity,unitPrice,null);
    }
}
