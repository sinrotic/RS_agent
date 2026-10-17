package com.sinrotic.rs.seckill.domain.vo;

public record SeckillSubmitVO(
        String requestId,
        String status,
        Long orderId
) {
    public SeckillSubmitVO(String requestId, String status) { this(requestId,status,null); }
}
