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
        CommerceTaskMetrics.registerUtc(registry,jdbc,"refund",
                "SELECT COUNT(*) FROM checkout_refund WHERE status<>'REFUNDED'",
                "SELECT COUNT(*) FROM checkout_refund WHERE status='REVIEW_REQUIRED'",
                "SELECT MIN(created_at) FROM checkout_refund WHERE status<>'REFUNDED'");
        CommerceTaskMetrics.registerUtc(registry,jdbc,"trade-event",
                "SELECT COUNT(*) FROM commerce_event_delivery WHERE status<>'DONE'",
                "SELECT COUNT(*) FROM commerce_event_delivery WHERE status='REVIEW_REQUIRED'",
                "SELECT MIN(e.created_at) FROM commerce_event_delivery d JOIN commerce_order_event e ON e.event_id=d.event_id WHERE d.status<>'DONE'");
    }
}
