package com.sinrotic.rs.payment.service;

import com.sinrotic.rs.common.commerce.CommerceTaskMetrics;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class PaymentTaskMetrics {
    public PaymentTaskMetrics(MeterRegistry registry,JdbcTemplate jdbc) {
        String pending="status IN ('PENDING','PROCESSING','REVIEW')";
        CommerceTaskMetrics.register(registry,jdbc,"payment",
                "SELECT COUNT(*) FROM payment_order_notifications WHERE "+pending,
                "SELECT COUNT(*) FROM payment_order_notifications WHERE status='REVIEW'",
                "SELECT COALESCE(MAX(TIMESTAMPDIFF(SECOND,next_attempt_at,CURRENT_TIMESTAMP(6))),0) FROM payment_order_notifications WHERE "+pending);
    }
}
