package com.sinrotic.rs.order.mq;

import com.sinrotic.rs.order.domain.dto.SeckillOrderCreateMessageDTO;
import com.sinrotic.rs.order.config.OrderKafkaConfiguration;
import com.sinrotic.rs.order.service.OrderService;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.env.MapPropertySource;
import org.springframework.kafka.config.KafkaListenerEndpointRegistry;
import org.springframework.kafka.core.ConsumerFactory;
import tools.jackson.databind.json.JsonMapper;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class SeckillOrderCreateConsumerTest {

    @Test
    void consumeParsesJsonAndCreatesSeckillOrder() throws Exception {
        OrderService orderService = mock(OrderService.class);
        SeckillOrderCreateConsumer consumer = new SeckillOrderCreateConsumer(orderService, new JsonMapper());

        consumer.consume("""
                {
                  "requestId": "sec-req-1",
                  "accountId": 1,
                  "activityId": "activity-1",
                  "itemId": "item-9",
                  "skuId": "sku-9",
                  "quantity": 3
                }
                """);

        verify(orderService).createSeckillOrder(new SeckillOrderCreateMessageDTO(
                "sec-req-1",
                1L,
                "activity-1",
                "item-9",
                "sku-9",
                3
        ));
    }

    @Test
    void kafkaListenerEndpointIsRegisteredInSpringContext() {
        try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext()) {
            context.getEnvironment().getPropertySources().addFirst(new MapPropertySource("kafka-test", Map.of(
                    "spring.kafka.bootstrap-servers", "127.0.0.1:65535",
                    "spring.kafka.listener.auto-startup", "false"
            )));
            context.register(OrderKafkaConfiguration.class, ListenerRegistrationTestConfiguration.class);
            context.refresh();

            KafkaListenerEndpointRegistry registry = context.getBean(KafkaListenerEndpointRegistry.class);

            assertNotNull(context.getBean(ConsumerFactory.class));
            assertTrue(context.containsBean("kafkaListenerContainerFactory"));
            assertTrue(registry.getListenerContainerIds().contains("seckillOrderCreateConsumer"));
        }
    }

    @Configuration(proxyBeanMethods = false)
    static class ListenerRegistrationTestConfiguration {

        @Bean
        SeckillOrderCreateConsumer seckillOrderCreateConsumer(OrderService orderService, JsonMapper jsonMapper) {
            return new SeckillOrderCreateConsumer(orderService, jsonMapper);
        }

        @Bean
        OrderService orderService() {
            return mock(OrderService.class);
        }

        @Bean
        JsonMapper jsonMapper() {
            return new JsonMapper();
        }
    }
}
