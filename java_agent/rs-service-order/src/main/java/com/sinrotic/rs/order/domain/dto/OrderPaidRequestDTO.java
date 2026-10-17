package com.sinrotic.rs.order.domain.dto;

public record OrderPaidRequestDTO(
        String requestId,
        Long orderId,
        String provider,
        String providerTransactionId,
        Long amount
) {
    public OrderPaidRequestDTO(String requestId,Long orderId,String provider,String providerTransactionId) {
        this(requestId,orderId,provider,providerTransactionId,null);
    }
}
