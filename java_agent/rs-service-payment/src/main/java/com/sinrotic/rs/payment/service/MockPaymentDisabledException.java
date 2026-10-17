package com.sinrotic.rs.payment.service;

public final class MockPaymentDisabledException extends PaymentServiceException {
    public MockPaymentDisabledException() { super("模拟支付未启用"); }
}
