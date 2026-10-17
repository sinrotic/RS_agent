package com.sinrotic.rs.payment.service;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@EnableScheduling
@ConditionalOnProperty(name = "rs.payment.notification.worker.enabled", havingValue = "true", matchIfMissing = true)
public class PaymentNotificationWorker {
    private final PaymentNotificationService service;
    public PaymentNotificationWorker(PaymentNotificationService service) { this.service = service; }
    @Scheduled(fixedDelayString = "${rs.payment.notification.worker.delay-ms:1000}")
    public void tick() { service.processPending(); }
}
