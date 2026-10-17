package com.sinrotic.rs.platformtrace.service;

import com.sinrotic.rs.platformtrace.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.platformtrace.service.impl.InMemoryPlatformTraceService;
import org.junit.jupiter.api.Test;
import java.time.Instant;
import java.util.Map;
import static org.assertj.core.api.Assertions.*;

class CanonicalModelUsageTest {
    private final InMemoryPlatformTraceService service = new InMemoryPlatformTraceService();

    @Test
    void explicitZeroIsCompleteButAbsentOrMalformedFieldsStayUnknown() {
        service.saveAgentTraceEvent(finalEvent("zero", "zero-run", "zero", Map.of("total_tokens", 0), true, null, 1000));
        var zero = service.agentRequestMonitor("zero-run").summary();
        assertThat(zero.totalTokens()).isZero();
        assertThat(zero.promptTokens()).isNull();
        service.saveAgentTraceEvent(finalEvent("bad", "bad-run", "bad", Map.of("total_tokens", -1), true, null, 1000));
        var bad = service.agentRequestMonitor("bad-run").summary();
        assertThat(bad.totalTokens()).isNull();
        assertThat(bad.usageCoverage()).containsEntry("conflicting_observations", 1L);
    }

    @Test
    void duplicateFinalsAndStreamSnapshotsDoNotDoubleCountAndOrderDoesNotMatter() {
        var result = finalEvent("done", "run", "call", Map.of("prompt_tokens", 20, "completion_tokens", 5,
                "total_tokens", 25, "cache_read_input_tokens", 0), true, 100L, 1000);
        service.saveAgentTraceEvent(result);
        service.saveAgentTraceEvent(result);
        service.saveAgentTraceEvent(event("start", "run", "model_call_started", Map.of("model_call_id", "call"), null, 800));
        service.saveAgentTraceEvent(new AgentTraceEventVO("stream", "session", "run", "model_usage", "", "", "agent", "", "",
                null, 999, 999, 1998, null, null, Map.of(), Instant.EPOCH));
        var monitor = service.agentRequestMonitor("run");
        assertThat(monitor.summary().totalTokens()).isEqualTo(25);
        assertThat(monitor.summary().usageCoverage()).containsEntry("model_calls", 1);
        assertThat(monitor.phases().stream().filter(phase -> phase.phase().equals("model_call")).findFirst().orElseThrow().totalTokens())
                .isEqualTo(25);
    }

    @Test
    void failedOrStartedOnlyCallsRemainInTheDenominator() {
        service.saveAgentTraceEvent(finalEvent("a", "run", "a", Map.of("total_tokens", 25), true, null, 1000));
        service.saveAgentTraceEvent(event("b", "run", "model_call_started", Map.of("model_call_id", "b"), null, 1001));
        var summary = service.agentRequestMonitor("run").summary();
        assertThat(summary.totalTokens()).isNull();
        assertThat(summary.usageCoverage()).containsEntry("model_calls", 2);
        var fields = (Map<?, ?>) summary.usageCoverage().get("fields");
        assertThat(((Map<?, ?>) fields.get("total_tokens")).get("known_subtotal")).isEqualTo(25L);
    }

    @Test
    void unfinishedUsageAndConflictingFinalsCannotProduceACompleteTotal() {
        service.saveAgentTraceEvent(finalEvent("a", "run", "a", Map.of("total_tokens", 25), true, null, 1000));
        service.saveAgentTraceEvent(finalEvent("b", "run", "a", Map.of("total_tokens", 30), true, null, 1000));
        service.saveAgentTraceEvent(finalEvent("c", "run", "b", Map.of("total_tokens", 10), false, null, 1000));
        var summary = service.agentRequestMonitor("run").summary();
        assertThat(summary.totalTokens()).isNull();
        assertThat(summary.usageCoverage()).containsEntry("conflicting_observations", 1L);
    }

    @Test
    void sameCallIdInAnotherRunIsIndependentAndLegacyRunsKeepSessionTotalsUnknown() {
        service.saveAgentTraceEvent(finalEvent("a", "run-1", "same", Map.of("total_tokens", 10), true, null, 1000));
        service.saveAgentTraceEvent(finalEvent("b", "run-2", "same", Map.of("total_tokens", 20), true, null, 1000));
        assertThat(service.agentSessionMonitor("session", null).summary().totalTokens()).isEqualTo(30);
        service.saveAgentTraceEvent(new AgentTraceEventVO("old", "session", "old-run", "model_usage", "", "", "agent", "", "",
                null, 5, 5, 10, null, null, Map.of(), Instant.EPOCH));
        var mixed = service.agentSessionMonitor("session", null).summary();
        assertThat(mixed.totalTokens()).isNull();
        assertThat(mixed.usageCoverage()).containsEntry("mode", "mixed").containsEntry("legacy_runs", 1);
    }

    @Test
    void parallelAndNestedDurationsAreCombinedInsteadOfAdded() {
        service.saveAgentTraceEvent(finalEvent("a", "run", "a", Map.of(), false, 200L, 1000));
        service.saveAgentTraceEvent(finalEvent("b", "run", "b", Map.of(), false, 200L, 1100));
        service.saveAgentTraceEvent(event("root", "run", "agent_done", Map.of(), 400L, 1150));
        var monitor = service.agentRequestMonitor("run");
        assertThat(monitor.summary().totalLatencyMs()).isEqualTo(400L);
        assertThat(monitor.phases().stream().filter(phase -> phase.phase().equals("model_call")).findFirst().orElseThrow().latencyMs())
                .isEqualTo(300L);
    }

    private AgentTraceEventVO finalEvent(String id, String run, String call, Map<String, Object> usage, boolean finalized, Long latency, long end) {
        return event(id, run, "model_call_completed", Map.of("model_call_id", call, "usage", usage,
                "usage_final", finalized, "status", "completed"), latency, end);
    }
    private AgentTraceEventVO event(String id, String run, String type, Map<String, Object> data, Long latency, long end) {
        return new AgentTraceEventVO(id, "session", run, type, "", "", "agent", "", "", latency, data, Instant.ofEpochMilli(end));
    }
}
