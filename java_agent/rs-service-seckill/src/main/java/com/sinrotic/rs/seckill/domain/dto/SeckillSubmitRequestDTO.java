package com.sinrotic.rs.seckill.domain.dto;

public record SeckillSubmitRequestDTO(
        String requestId,
        String accountId,
        String activityId,
        String itemId,
        String skuId,
        Integer quantity
) {}
