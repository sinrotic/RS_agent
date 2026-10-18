package com.sinrotic.rs.order.checkout;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@EnableScheduling
@ConditionalOnProperty(name="rs.checkout.worker.enabled",havingValue="true",matchIfMissing=true)
public class CheckoutWorker {
    private final CheckoutService service;
    public CheckoutWorker(CheckoutService service) { this.service = service; }
    @Scheduled(scheduler="commerceWorkflowScheduler",fixedDelayString="${rs.checkout.worker.delay-ms:500}")
    public void tick() { service.processPending(); }
}
