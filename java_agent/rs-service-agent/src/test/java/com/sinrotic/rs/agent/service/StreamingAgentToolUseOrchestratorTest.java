package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.StreamingAgentToolUseOrchestrator;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;

class StreamingAgentToolUseOrchestratorTest {

    @Test
    void cancellationBeforeTheRawFutureIsPublishedStillCancelsThatFuture() throws Exception {
        var entered = new java.util.concurrent.CountDownLatch(1); var release = new java.util.concurrent.CountDownLatch(1);
        var raw = new java.util.concurrent.CompletableFuture<Map<String, Object>>();
        var run = new StreamingAgentToolUseOrchestrator(event -> {
            entered.countDown(); try { release.await(); } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            return raw;
        }).start();
        var submission = java.util.concurrent.CompletableFuture.runAsync(() -> run.submit("call", AgentModelStreamEvent.toolUse("load_skill", Map.of())));
        try {
            assertThat(entered.await(1, java.util.concurrent.TimeUnit.SECONDS)).isTrue(); run.cancel(); release.countDown();
            submission.get(1, java.util.concurrent.TimeUnit.SECONDS);
            assertThat(raw.isCancelled()).isTrue();
            assertThat(run.awaitResults()).hasSize(1);
        } finally { release.countDown(); }
    }

    @Test
    void concurrentSafeToolsStartWithoutWaitingForEachOther() {
        AtomicInteger running = new AtomicInteger();
        AtomicInteger maxRunning = new AtomicInteger();
        StreamingAgentToolUseOrchestrator orchestrator = new StreamingAgentToolUseOrchestrator(
                new VirtualThreadAgentToolUseExecutor(event -> {
                    int current = running.incrementAndGet();
                    maxRunning.accumulateAndGet(current, Math::max);
                    sleep(150);
                    running.decrementAndGet();
                    return Map.of("status", "SUCCESS", "tool_name", event.toolName());
                })
        );

        AgentToolUseOrchestrator.Run run = orchestrator.start();
        run.submit("toolu_1", AgentModelStreamEvent.toolUse("load_skill", Map.of("skill_name", "a")));
        run.submit("toolu_2", AgentModelStreamEvent.toolUse("rag_support", Map.of("query", "earbuds")));

        List<AgentToolUseResult> results = run.awaitResults();

        assertThat(maxRunning.get()).isGreaterThanOrEqualTo(2);
        assertThat(results).extracting(AgentToolUseResult::toolCallId)
                .containsExactly("toolu_1", "toolu_2");
    }

    @Test
    void serialToolWaitsForPreviousToolsAndBlocksLaterConcurrentTools() {
        Map<String, Long> startedAt = new ConcurrentHashMap<>();
        Map<String, Long> finishedAt = new ConcurrentHashMap<>();
        StreamingAgentToolUseOrchestrator orchestrator = new StreamingAgentToolUseOrchestrator(
                new VirtualThreadAgentToolUseExecutor(event -> {
                    startedAt.put(event.toolName(), System.nanoTime());
                    sleep(sleepMillis(event.toolName()));
                    finishedAt.put(event.toolName(), System.nanoTime());
                    return Map.of("status", "SUCCESS", "tool_name", event.toolName());
                })
        );

        AgentToolUseOrchestrator.Run run = orchestrator.start();
        run.submit("toolu_read_1", AgentModelStreamEvent.toolUse("load_skill", Map.of("skill_name", "a")));
        run.submit("toolu_read_2", AgentModelStreamEvent.toolUse("rag_support", Map.of("query", "earbuds")));
        run.submit("toolu_write", AgentModelStreamEvent.toolUse("custom_write", Map.of("value", "x")));
        run.submit("toolu_read_3", AgentModelStreamEvent.toolUse("read_tool_result_lines", Map.of("result_ref", "r1")));

        List<AgentToolUseResult> results = run.awaitResults();

        assertThat(startedAt.get("custom_write"))
                .isGreaterThanOrEqualTo(finishedAt.get("load_skill"))
                .isGreaterThanOrEqualTo(finishedAt.get("rag_support"));
        assertThat(startedAt.get("read_tool_result_lines"))
                .isGreaterThanOrEqualTo(finishedAt.get("custom_write"));
        assertThat(results).extracting(AgentToolUseResult::toolCallId)
                .containsExactly("toolu_read_1", "toolu_read_2", "toolu_write", "toolu_read_3");
    }

    private static long sleepMillis(String toolName) {
        return "custom_write".equals(toolName) ? 80 : 120;
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        }
    }
}
