package com.sinrotic.rs.payment.client.dto;

public record OrderPaidRequestDTO(
        String requestId,
        Long orderId,
        String provider,
        String providerTransactionId
) {
}
