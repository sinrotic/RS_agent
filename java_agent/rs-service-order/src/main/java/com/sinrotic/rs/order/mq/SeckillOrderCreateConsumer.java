package com.sinrotic.rs.order.mq;

import com.sinrotic.rs.order.domain.dto.SeckillOrderCreateMessageDTO;
import com.sinrotic.rs.order.service.OrderService;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

@Component
public class SeckillOrderCreateConsumer {

    private final OrderService orderService;
    private final JsonMapper jsonMapper;

    public SeckillOrderCreateConsumer(OrderService orderService, JsonMapper jsonMapper) {
        this.orderService = orderService;
        this.jsonMapper = jsonMapper;
    }

    @KafkaListener(id = "seckillOrderCreateConsumer", topics = "seckill-order-create", groupId = "rs-service-order")
    public void consume(String payload) throws Exception {
        SeckillOrderCreateMessageDTO message = jsonMapper.readValue(payload, SeckillOrderCreateMessageDTO.class);
        orderService.createSeckillOrder(message);
    }
}
