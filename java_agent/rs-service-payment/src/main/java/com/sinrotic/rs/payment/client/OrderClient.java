package com.sinrotic.rs.payment.client;

public interface OrderClient {

    record PaymentQuote(Long orderId, String accountId, long amount) {}

    default PaymentQuote paymentQuote(Long orderId, String accountId) {
        throw new IllegalStateException("订单支付核验未配置");
    }

    void markPaid(Long orderId, String provider, String providerTransactionId);
}
