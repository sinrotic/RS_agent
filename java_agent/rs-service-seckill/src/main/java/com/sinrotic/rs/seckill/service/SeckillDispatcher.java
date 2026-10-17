package com.sinrotic.rs.seckill.service;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@EnableScheduling
@ConditionalOnProperty(name="rs.seckill.worker.enabled",havingValue="true",matchIfMissing=true)
public class SeckillDispatcher {
    private final SeckillService service;
    public SeckillDispatcher(SeckillService service) { this.service = service; }
    @Scheduled(scheduler="seckillScheduler",fixedDelayString="${rs.seckill.worker.publish-delay-ms:100}")
    public void publish() { service.dispatch(); }
    @Scheduled(scheduler="seckillScheduler",fixedDelayString="${rs.seckill.worker.reconcile-delay-ms:1000}")
    public void reconcile() { service.reconcile(); }
    @Scheduled(scheduler="seckillScheduler",fixedDelayString="${rs.seckill.worker.allocation-delay-ms:10000}")
    public void allocations() { service.maintainAllocations(); }
}
