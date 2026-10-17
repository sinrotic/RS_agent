package com.sinrotic.rs.payment.domain.entity;

public record PaymentNotification(Long orderId, String provider, String providerTransactionId, int attempts) {}
