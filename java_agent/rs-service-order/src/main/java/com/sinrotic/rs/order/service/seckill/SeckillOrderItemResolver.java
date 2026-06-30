package com.sinrotic.rs.order.service.seckill;

public interface SeckillOrderItemResolver {

    SeckillOrderItemSnapshot resolve(String activityId, String itemId, String skuId);
}
