package com.sinrotic.rs.order.service;

public record StockMovement(Long orderId, String skuId, Integer quantity) {
}
