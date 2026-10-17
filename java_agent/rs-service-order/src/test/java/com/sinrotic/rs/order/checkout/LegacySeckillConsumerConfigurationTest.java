package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.order.mq.SeckillOrderCreateConsumer;
import com.sinrotic.rs.order.service.OrderService;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import tools.jackson.databind.json.JsonMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class LegacySeckillConsumerConfigurationTest {
    @Test
    void internalLegacyPaidAndTimeoutOperationsRequireMigration() {
        var checkout=mock(CheckoutService.class);
        var controller=new com.sinrotic.rs.order.controller.internal.InternalOrderController(checkout,false);
        assertThatThrownBy(()->controller.markPaid(7L,new com.sinrotic.rs.order.domain.dto.OrderPaidRequestDTO("pay",7L,"mock","tx",500L)))
                .isInstanceOfSatisfying(org.springframework.web.server.ResponseStatusException.class,e->assertThat(e.getStatusCode().value()).isEqualTo(409));
        assertThatThrownBy(()->controller.closeTimeout(7L,null)).isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        verify(checkout,never()).paidFromProvider(anyLong(),any(),anyString(),anyString());
        verify(checkout,never()).closeTimeout(anyLong());
    }
    @Test
    void legacyConsumerIsAbsentUnlessExplicitlyEnabled() {
        var context=new ApplicationContextRunner().withBean(OrderService.class,()->mock(OrderService.class))
                .withBean(JsonMapper.class,JsonMapper::new).withUserConfiguration(SeckillOrderCreateConsumer.class);
        context.run(c -> assertThat(c).doesNotHaveBean(SeckillOrderCreateConsumer.class));
        context.withPropertyValues("rs.checkout.legacy-seckill-consumer-enabled=true")
                .run(c -> assertThat(c).hasSingleBean(SeckillOrderCreateConsumer.class));
    }
}
