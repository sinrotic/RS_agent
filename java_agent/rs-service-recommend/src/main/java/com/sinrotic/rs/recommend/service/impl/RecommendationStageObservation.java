package com.sinrotic.rs.recommend.service.impl;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.util.function.Supplier;

/** Record independent pipeline costs without logging queries or identities. */
@Component
public final class RecommendationStageObservation {
    private static final Logger log = LoggerFactory.getLogger(RecommendationStageObservation.class);
    private final boolean enabled;
    public RecommendationStageObservation(
            @Value("${rs.recommend.performance-observation-enabled:${RS_RECOMMEND_PERFORMANCE_OBSERVATION_ENABLED:false}}") boolean enabled) {
        this.enabled = enabled;
    }
    public <T> T measure(String stage, Supplier<T> work) {
        if (!enabled) return work.get();
        long started = System.nanoTime();
        boolean success = false;
        try {
            T result = work.get(); success = true; return result;
        } finally {
            log.info("推荐阶段耗时 stage={} success={} duration_ms={}", stage, success,
                    (System.nanoTime() - started) / 1_000_000.0);
        }
    }
}
