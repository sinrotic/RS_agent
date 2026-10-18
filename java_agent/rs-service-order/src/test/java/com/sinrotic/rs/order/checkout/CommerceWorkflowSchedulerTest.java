package com.sinrotic.rs.order.checkout;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
class CommerceWorkflowSchedulerTest {
    @Test void enabledProductionSchedulerStartsWithoutConfigurationBeanNameCollision() {
        new ApplicationContextRunner().withUserConfiguration(CommerceWorkflowScheduler.class)
                .withBean(RefundService.class,()->mock(RefundService.class))
                .withBean(TradeEventDispatcher.class,()->mock(TradeEventDispatcher.class))
                .run(context->{
                    assertThat(context).hasNotFailed();
                    assertThat(context.getBean("commerceWorkflowScheduler")).isInstanceOf(ThreadPoolTaskScheduler.class);
                    assertThat(context.getBean("commerceWorkflowSchedulingConfiguration")).isInstanceOf(CommerceWorkflowScheduler.class);
                });
    }
}
