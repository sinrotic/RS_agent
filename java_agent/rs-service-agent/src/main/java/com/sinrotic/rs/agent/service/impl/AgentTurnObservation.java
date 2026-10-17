package com.sinrotic.rs.agent.service.impl;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import java.util.LinkedHashMap;
import java.util.Map;

/** Server-side timings only; contains neither messages nor user identifiers. */
@Component
public final class AgentTurnObservation {
    private static final Logger log = LoggerFactory.getLogger(AgentTurnObservation.class);
    private final boolean enabled;

    public AgentTurnObservation(@Value("${rs.agent.performance-observation-enabled:false}") boolean enabled) {
        this.enabled = enabled;
    }

    public Timing start(long receivedNanos) { return new Timing(receivedNanos); }

    public final class Timing implements AutoCloseable {
        private final long received;
        private final Map<String, Double> stages = new LinkedHashMap<>();
        private String route = "agent";
        private boolean success;
        private Timing(long received) {
            this.received = received;
        }
        public void record(String stage, long started) {
            if (enabled) stages.put(stage + "_ms", (System.nanoTime() - started) / 1_000_000.0);
        }
        public void route(String route) { this.route = route; }
        long receivedNanos() { return received; }
        public void success() { success = true; }
        @Override public void close() {
            if (enabled) {
                if (!stages.containsKey("admission_ms")) record("admission", received);
                record("total", received);
                log.info("推荐轮次耗时 route={} success={} stages={}", route, success, stages);
            }
        }
    }
}
