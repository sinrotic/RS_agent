package com.sinrotic.rs.payment.domain.dto;

public record CreatePaymentRequestDTO(
        Long orderId,
        Long accountId,
        Long amount,
        String provider
) {
}
