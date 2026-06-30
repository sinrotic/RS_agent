package com.sinrotic.rs.order.domain.dto;

public record OrderPaidRequestDTO(
        String requestId,
        Long orderId,
        String provider,
        String providerTransactionId
) {
}
