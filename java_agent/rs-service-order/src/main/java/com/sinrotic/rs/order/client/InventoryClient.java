package com.sinrotic.rs.order.client;

public interface InventoryClient {
    default void activity(String action,String activityId,Long orderId,String skuId,Integer quantity) {
        throw new IllegalStateException("活动库存能力未配置");
    }

    void lock(String requestId, Long orderId, String skuId, Integer quantity);

    void confirm(String requestId, Long orderId, String skuId, Integer quantity);

    void release(String requestId, Long orderId, String skuId, Integer quantity);

    default void cancel(String requestId, Long orderId, String skuId, Integer quantity) {
        throw new IllegalStateException("库存取消预留能力未配置");
    }
}
