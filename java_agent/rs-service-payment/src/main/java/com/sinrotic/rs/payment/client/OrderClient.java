package com.sinrotic.rs.payment.client;

public interface OrderClient {

    void markPaid(Long orderId, String provider, String providerTransactionId);
}
