package com.sinrotic.rs.inventory.service;
import com.sinrotic.rs.common.commerce.CommerceTaskMetrics;
import org.springframework.stereotype.Component;
import org.springframework.jdbc.core.JdbcTemplate;
import io.micrometer.core.instrument.MeterRegistry;
@Component
public class InventoryReconciliationMetrics {
    public InventoryReconciliationMetrics(MeterRegistry registry,JdbcTemplate jdbc) {
        CommerceTaskMetrics.registerUtc(registry,jdbc,"inventory-reconciliation",
                "SELECT COUNT(*) FROM inventory_reconciliation WHERE status<>'RESOLVED'",
                "SELECT COUNT(*) FROM inventory_reconciliation WHERE status='OPEN'",
                "SELECT MIN(created_at) FROM inventory_reconciliation WHERE status<>'RESOLVED'");
    }
}
