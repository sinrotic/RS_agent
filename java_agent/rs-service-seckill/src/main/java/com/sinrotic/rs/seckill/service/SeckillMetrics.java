package com.sinrotic.rs.seckill.service;

import com.sinrotic.rs.common.commerce.CommerceTaskMetrics;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class SeckillMetrics {
    public SeckillMetrics(MeterRegistry registry,JdbcTemplate jdbc) {
        String pending="status NOT IN ('PAID','FAILED','CANCELED','TIMEOUT_CLOSED','REFUNDED')";
        CommerceTaskMetrics.registerUtc(registry,jdbc,"seckill",
                "SELECT COUNT(*) FROM seckill_request_v1 WHERE "+pending,
                "SELECT COUNT(*) FROM seckill_request_v1 WHERE status='REVIEW_REQUIRED'",
                "SELECT MIN(created_at) FROM seckill_request_v1 WHERE "+pending);
        CommerceTaskMetrics.registerUtc(registry,jdbc,"allocation",
                "SELECT COUNT(*) FROM seckill_activity_allocation WHERE status IN ('PENDING','REVIEW','CLOSING')",
                "SELECT COUNT(*) FROM seckill_activity_allocation WHERE status='REVIEW'",
                "SELECT MIN(phase_started_at) FROM seckill_activity_allocation WHERE status IN ('PENDING','REVIEW','CLOSING')");
    }
}
