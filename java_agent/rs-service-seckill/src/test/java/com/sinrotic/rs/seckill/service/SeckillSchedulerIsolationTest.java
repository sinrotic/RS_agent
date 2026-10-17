package com.sinrotic.rs.seckill.service;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SeckillSchedulerIsolationTest {
    @Test
    void springSchedulingContinuesPublishingWhileReconciliationIsBlocked() {
        var service=mock(SeckillService.class);
        var checking=new CountDownLatch(1);var release=new CountDownLatch(1);var published=new CountDownLatch(1);
        doAnswer(invocation -> { checking.countDown();release.await(5,TimeUnit.SECONDS);return null; }).when(service).reconcile();
        doAnswer(invocation -> { if(checking.getCount()==0) published.countDown();return null; }).when(service).dispatch();
        new ApplicationContextRunner().withBean(SeckillService.class,()->service)
                .withUserConfiguration(SeckillDispatcher.class,SeckillSchedulerConfiguration.class)
                .withPropertyValues("rs.seckill.worker.publish-delay-ms=10","rs.seckill.worker.reconcile-delay-ms=10")
                .run(context -> {
                    try {
                        assertThat(context).hasSingleBean(SeckillDispatcher.class);
                        assertThat(checking.await(2,TimeUnit.SECONDS)).isTrue();
                        assertThat(published.await(2,TimeUnit.SECONDS)).isTrue();
                    } finally { release.countDown(); }
                });
    }
}
