package com.sinrotic.rs.payment.domain.dto;

public record PaymentCallbackDTO(
        String provider,
        String providerTransactionId,
        Long orderId,
        Long amount,
        String signature,
        String rawPayload
) {
}
