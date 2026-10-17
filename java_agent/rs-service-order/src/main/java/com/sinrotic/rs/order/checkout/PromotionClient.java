package com.sinrotic.rs.order.checkout;

public interface PromotionClient {
    long lock(long orderId, String couponId, String accountId, String itemId, long originalAmount);
    void confirm(long orderId, String couponId);
    void release(long orderId, String couponId);

    default void cancel(long orderId, String couponId, String accountId, String itemId, long originalAmount) {
        throw new IllegalStateException("优惠券取消预留能力未配置");
    }
}
