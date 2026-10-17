package com.sinrotic.rs.order.checkout;

import com.sinrotic.rs.common.commerce.CommerceTaskMetrics;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public class CheckoutMetrics {
    public CheckoutMetrics(MeterRegistry registry,JdbcTemplate jdbc) {
        String pending="phase NOT IN ('READY','DONE','FAILED')";
        CommerceTaskMetrics.registerUtc(registry,jdbc,"checkout",
                "SELECT COUNT(*) FROM checkout_workflow WHERE "+pending,
                "SELECT COUNT(*) FROM checkout_workflow WHERE phase LIKE 'REVIEW_%'",
                "SELECT MIN(created_at) FROM checkout_workflow WHERE "+pending);
    }
}
