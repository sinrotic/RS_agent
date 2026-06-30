package com.sinrotic.rs.payment.domain.vo;

public record PaymentPrepayVO(
        Long paymentId,
        Long orderId,
        String provider,
        String status
) {
}
