package com.sinrotic.rs.order.client;

public interface InventoryClient {

    void lock(String requestId, Long orderId, String skuId, Integer quantity);

    void confirm(String requestId, Long orderId, String skuId, Integer quantity);

    void release(String requestId, Long orderId, String skuId, Integer quantity);
}
