package com.sinrotic.rs.inventory.service;
import org.springframework.stereotype.Component;
import org.springframework.scheduling.annotation.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
@Component
@EnableScheduling
@ConditionalOnProperty(name="rs.inventory.reconciliation.enabled",havingValue="true",matchIfMissing=true)
public class InventoryReconciliationWorker {
    private final InventoryManagement service;
    public InventoryReconciliationWorker(InventoryManagement service) {this.service=service;}
    @Scheduled(initialDelay=60000,fixedDelayString="${rs.inventory.reconciliation.delay-ms:60000}") public void tick() {service.tick();}
}
