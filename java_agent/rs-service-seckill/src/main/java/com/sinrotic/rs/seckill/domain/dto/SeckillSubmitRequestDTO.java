package com.sinrotic.rs.seckill.domain.dto;

public record SeckillSubmitRequestDTO(
        String requestId,
        Long accountId,
        String activityId,
        String itemId,
        String skuId,
        Integer quantity
) {}
