package com.sinrotic.rs.order.checkout;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

@Component
public class SeckillCheckoutConsumer {
    private final CheckoutService service;
    private final JsonMapper mapper;
    public record Accepted(String eventId,String requestId,String accountId,String activityId,
                           String itemId,String skuId,int quantity,String itemTitle,long unitPrice,String stockPoolId) {
        public Accepted(String eventId,String requestId,String accountId,String activityId,String itemId,String skuId,int quantity,String itemTitle,long unitPrice) {
            this(eventId,requestId,accountId,activityId,itemId,skuId,quantity,itemTitle,unitPrice,null);
        }
    }
    public SeckillCheckoutConsumer(CheckoutService service,JsonMapper mapper) { this.service = service; this.mapper = mapper; }
    @KafkaListener(topics="checkout-seckill-accepted",groupId="rs-checkout-seckill-v1",properties="auto.offset.reset=earliest")
    public void consume(String payload) throws Exception {
        Accepted accepted = mapper.readValue(payload,Accepted.class);
        if(accepted == null || accepted.quantity()!=1 || accepted.activityId()==null || accepted.activityId().isBlank())
            throw new IllegalArgumentException("秒杀事件不合法，每个受理事件仅可创建一件商品订单");
        if(accepted.stockPoolId()!=null && !accepted.stockPoolId().equals(accepted.activityId()))
            throw new IllegalArgumentException("活动库存范围与事件不匹配");
        service.createAccepted(accepted.accountId(),
                new CheckoutService.CreateRequest(accepted.eventId(),accepted.itemId(),accepted.skuId(),accepted.quantity(),null,null,null),
                new CheckoutService.Offer(accepted.skuId(),accepted.itemId(),accepted.itemTitle(),accepted.unitPrice()),accepted.stockPoolId());
    }
}
