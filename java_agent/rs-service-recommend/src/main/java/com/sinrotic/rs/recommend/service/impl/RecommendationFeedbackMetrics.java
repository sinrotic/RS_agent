package com.sinrotic.rs.recommend.service.impl;

import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

@Component
public class RecommendationFeedbackMetrics {

    private final MeterRegistry registry;

    public RecommendationFeedbackMetrics(MeterRegistry registry) {
        this.registry = registry;
    }

    public void accepted(String eventType, String applicationStatus, boolean duplicate) {
        registry.counter(
                "rs.recommend.feedback.accepted",
                "event_type", eventType,
                "application_status", applicationStatus,
                "duplicate", Boolean.toString(duplicate)
        ).increment();
    }

    public void rejected(String eventType) {
        registry.counter("rs.recommend.feedback.rejected", "event_type", eventType).increment();
    }

    public void projectionRetry(boolean success) {
        registry.counter("rs.recommend.feedback.projection.retry", "success", Boolean.toString(success)).increment();
    }

    public void projectionRebuild(String scope, boolean success) {
        registry.counter("rs.recommend.feedback.projection.rebuild",
                "scope", scope, "success", Boolean.toString(success)).increment();
    }
}
