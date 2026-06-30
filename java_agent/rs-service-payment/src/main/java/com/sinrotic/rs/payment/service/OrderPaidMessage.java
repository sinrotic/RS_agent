package com.sinrotic.rs.payment.service;

public record OrderPaidMessage(
        Long orderId,
        String provider,
        String providerTransactionId
) {
}
