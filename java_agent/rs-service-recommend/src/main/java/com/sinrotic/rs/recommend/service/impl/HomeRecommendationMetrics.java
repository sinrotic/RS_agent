package com.sinrotic.rs.recommend.service.impl;

import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;
import java.util.concurrent.TimeUnit;

@Component
public class HomeRecommendationMetrics {
    private final MeterRegistry registry;
    public HomeRecommendationMetrics(MeterRegistry registry) { this.registry = registry; }
    public void record(String mode, PersonalizedHomeCandidatePipeline.Selection selection, long elapsedNanos) {
        registry.timer("rs.recommend.home.latency", "mode", mode).record(elapsedNanos, TimeUnit.NANOSECONDS);
        registry.summary("rs.recommend.home.candidates").record(selection.stages().getOrDefault("recall", 0));
        registry.summary("rs.recommend.home.category.coverage").record(selection.items().stream()
                .map(item -> item.item().category()).distinct().count());
        selection.degradationReasons().forEach(reason -> registry.counter("rs.recommend.home.degraded", "reason", reason).increment());
    }
}
