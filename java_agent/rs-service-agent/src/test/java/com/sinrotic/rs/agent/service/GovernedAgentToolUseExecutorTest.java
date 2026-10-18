package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.*;
import com.sinrotic.rs.agent.domain.*;
import com.sinrotic.rs.agent.domain.dto.AgentRuntimeToolUpsertDTO;
import com.sinrotic.rs.agent.domain.vo.AgentStreamEventVO;
import com.sinrotic.rs.agent.service.impl.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.springframework.ai.chat.model.*;
import org.springframework.ai.chat.prompt.Prompt;
import reactor.core.publisher.Flux;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

import static org.assertj.core.api.Assertions.*;

@Timeout(6)
class GovernedAgentToolUseExecutorTest {
    private final InMemoryAgentRuntimeConfigurationService runtime = new InMemoryAgentRuntimeConfigurationService();
    private final InMemoryAgentCapabilityRegistry registry = new InMemoryAgentCapabilityRegistry();
    private static final AgentModelStreamEvent RAG = AgentModelStreamEvent.toolUse("call_agent", Map.of("agent_name", "rag_agent", "query", "背包"));

    @Test
    void noProgressEntersFinalAnswerModeAndTheModelCannotBypassTheExecutionGate() {
        var cfg = settings(); cfg.setNoProgressLimit(2); var tools = new AtomicInteger(); var models = new AtomicInteger();
        try (var raw = new VirtualThreadAgentToolUseExecutor(event -> { tools.incrementAndGet(); return Map.of("status", "SUCCESS", "content", "same"); });
             var governed = new GovernedAgentToolUseExecutor(raw, cfg, runtime, registry)) {
            var loop = new RsAgentLoop(runtime, governed, (id, request, sink) -> {
                int round = models.incrementAndGet();
                if (round <= 3) sink.accept(AgentModelStreamEvent.toolUse("load_skill", Map.of("skill_name", "same")));
                else sink.accept(AgentModelStreamEvent.toolUse("emit_final_answer", Map.of("blocks", List.of(Map.of("type", "text", "content", "使用已有证据结束")))));
            });
            var events = new ArrayList<AgentStreamEventVO>();
            var result = loop.run(new com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO("s", "p", "任务", 1, Map.of()), events::add);
            assertThat(result.finishReason()).isEqualTo(AgentFinishReason.FINAL_ANSWER);
            assertThat(tools.get()).isEqualTo(2);
            assertThat(events).anySatisfy(event -> {
                assertThat(event.event()).isEqualTo("tool_result");
                assertThat(((Map<?, ?>) event.data().get("metadata")).get("error_code")).isEqualTo("TOOL_FINAL_ANSWER_ONLY");
            });
        }
    }

    @Test
    void parallelToolsShareOneAttemptBudgetRatherThanReadingTheSameRemainingValue() {
        var cfg = settings(); cfg.setMaxAttemptsPerTurn(2); var calls = new AtomicInteger();
        try (var raw = new VirtualThreadAgentToolUseExecutor(event -> { calls.incrementAndGet(); return Map.of("status", "SUCCESS"); });
             var governed = new GovernedAgentToolUseExecutor(raw, cfg, runtime, registry);
             var turn = governed.openTurn(new AgentInterruptContext("budget", "session"))) {
            var futures = java.util.stream.IntStream.range(0, 8).mapToObj(index -> turn.execute(
                    AgentModelStreamEvent.toolUse("read_tool_result_lines", Map.of("offset", index)))).toList();
            CompletableFuture.allOf(futures.toArray(CompletableFuture[]::new)).join();
            assertThat(calls.get()).isEqualTo(2);
            assertThat(futures.stream().map(CompletableFuture::join).filter(value -> "TOOL_BUDGET_EXHAUSTED".equals(value.get("error_code")))).hasSize(6);
        }
    }

    @Test
    void replaySafeTemporaryFailuresRetryButValidationAuthorizationAndUnknownFailuresDoNot() {
        var count = new AtomicInteger(); var cfg = settings();
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> {
            if (count.incrementAndGet() == 1) throw new AgentToolDependencyException(503);
            return Map.of("status", "SUCCESS", "items", List.of());
        }); var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry)) {
            var result = executor.execute(RAG).join();
            assertThat(result).containsEntry("status", "SUCCESS");
            assertThat(governance(result)).containsEntry("attempts", 2).containsEntry("category", "success");
            assertThat(count.get()).isEqualTo(2);
        }
        for (RuntimeException error : List.of(new IllegalArgumentException("bad argument"), new SecurityException("denied"),
                new IllegalStateException("unknown"), new AgentBusyException("busy"), new AgentBusyException("interrupted permit wait", new InterruptedException()))) {
            count.set(0);
            try (var workers = new VirtualThreadAgentToolUseExecutor(event -> { count.incrementAndGet(); throw error; });
                 var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry)) {
                var result = governance(executor.execute(RAG).join());
                assertThat(result).containsEntry("attempts", 1).containsEntry("circuit_state", "CLOSED");
                if (error.getCause() instanceof InterruptedException) assertThat(result).containsEntry("category", "cancelled");
                assertThat(count.get()).isEqualTo(1);
            }
        }
    }

    @Test
    void nonReplaySafeAndRevokedToolsCannotBeAutomaticallyRetried() {
        var count = new AtomicInteger();
        var tool = runtime.tools().stream().filter(value -> value.name().equals("call_agent")).findFirst().orElseThrow();
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> {
            count.incrementAndGet(); runtime.upsertTool(tool.name(), new AgentRuntimeToolUpsertDTO(tool.service(), tool.description(), false, tool.parametersSchema()));
            throw new AgentToolDependencyException(503);
        }); var executor = new GovernedAgentToolUseExecutor(workers, settings(), runtime, registry)) {
            assertThat(governance(executor.execute(RAG).join())).containsEntry("attempts", 1);
            assertThat(count.get()).isEqualTo(1);
        }
        var external = AgentModelStreamEvent.toolUse("custom_unverified_tool", Map.of()); count.set(0);
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> { count.incrementAndGet(); throw new AgentToolDependencyException(503); });
             var executor = new GovernedAgentToolUseExecutor(workers, settings(), runtime, registry)) {
            executor.execute(external).join(); assertThat(count.get()).isEqualTo(1);
        }
    }

    @Test
    void attemptsAreSharedAcrossCallsInATurnAndUnknownResultsDoNotResetTheBudget() {
        var count = new AtomicInteger(); var cfg = settings(); cfg.setMaxAttemptsPerTurn(2);
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> {
            if (count.incrementAndGet() == 1) throw new AgentToolDependencyException(503);
            return Map.of("status", "SUCCESS");
        }); var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry);
             var turn = executor.openTurn(new AgentInterruptContext("turn", "session"))) {
            assertThat(governance(turn.execute(RAG).join())).containsEntry("attempts", 2);
            assertThat(turn.execute(AgentModelStreamEvent.toolUse("load_skill", Map.of("skill_name", "other"))).join())
                    .containsEntry("error_code", "TOOL_BUDGET_EXHAUSTED");
            assertThat(count.get()).isEqualTo(2);
        }
    }

    @Test
    void unchangedEvidenceStopsButPaginationUpdatedResultsAndNewTurnsRemainUsable() {
        var count = new AtomicInteger(); var cfg = settings(); cfg.setNoProgressLimit(2);
        var read = AgentModelStreamEvent.toolUse("read_tool_result_lines", Map.of("offset", 0));
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> { count.incrementAndGet(); return Map.of("status", "SUCCESS", "lines", List.of("evidence"), "request_id", UUID.randomUUID().toString()); });
             var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry)) {
            try (var turn = executor.openTurn(new AgentInterruptContext("first", "session"))) {
                turn.execute(read).join(); assertThat(governance(turn.execute(read).join())).containsEntry("no_progress", true);
                assertThat(turn.execute(read).join()).containsEntry("error_code", "TOOL_NO_PROGRESS");
                assertThat(turn.execute(AgentModelStreamEvent.toolUse("read_tool_result_lines", Map.of("offset", 20))).join()).containsEntry("status", "SUCCESS");
            }
            try (var turn = executor.openTurn(new AgentInterruptContext("next", "session"))) { assertThat(turn.execute(read).join()).containsEntry("status", "SUCCESS"); }
            assertThat(count.get()).isEqualTo(4);
        }
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS", "price", count.incrementAndGet()));
             var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry);
             var turn = executor.openTurn(new AgentInterruptContext("updated", "session"))) {
            for (int i = 0; i < 4; i++) assertThat(governance(turn.execute(read).join())).containsEntry("no_progress", false);
        }
    }

    @Test
    void externalizedResultReferencesDoNotHideRepeatsOrDiscardChangesBeyondThePreview() {
        var cfg = settings(); cfg.setNoProgressLimit(2); var version = new AtomicInteger();
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS", "result",
                Map.of("padding", "unchanged".repeat(1000), "tail", version.get())));
             var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry);
             var turn = executor.openTurn(new AgentInterruptContext("large", "session"))) {
            var first = turn.execute(AgentModelStreamEvent.toolUse("a", "rag_support", Map.of("query", "same"))).join();
            var second = turn.execute(AgentModelStreamEvent.toolUse("b", "rag_support", Map.of("query", "same"))).join();
            assertThat(first.get("result_ref")).isNotEqualTo(second.get("result_ref"));
            assertThat(governance(second)).containsEntry("no_progress", true);
        }
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> Map.of("status", "SUCCESS", "result",
                new TreeMap<>(Map.of("padding", "unchanged".repeat(1000), "tail", version.incrementAndGet()))));
             var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry);
             var turn = executor.openTurn(new AgentInterruptContext("refresh", "session"))) {
            var first = turn.execute(RAG).join(); var second = turn.execute(RAG).join();
            assertThat(first.get("preview_lines")).isEqualTo(second.get("preview_lines"));
            assertThat(first.get("result_sha256")).isNotEqualTo(second.get("result_sha256"));
            assertThat(governance(second)).containsEntry("no_progress", false);
        }
    }

    @Test
    void closedTurnDoesNotLaterInterruptItsContextOrTheNextTurn() throws Exception {
        var cfg = settings(); cfg.setTurnTimeoutMs(50);
        var closedContext = new AgentInterruptContext("closed", "session");
        try (var executor = new GovernedAgentToolUseExecutor(event -> CompletableFuture.completedFuture(Map.of("status", "SUCCESS")), cfg, runtime, registry)) {
            executor.openTurn(closedContext).close();
            var nextContext = new AgentInterruptContext("next", "session"); var timedOut = new CountDownLatch(1);
            nextContext.onInterrupt(timedOut::countDown);
            try (var next = executor.openTurn(nextContext)) {
                assertThat(timedOut.await(1, TimeUnit.SECONDS)).isTrue();
                assertThat(nextContext.reason()).isEqualTo("turn_timeout");
                assertThat(closedContext.interrupted()).isFalse();
            }
        }
    }

    @Test
    void timeoutInterruptsTheActualWorkerAndReleasesCapacityWithoutRetrying() throws Exception {
        var cfg = settings(); cfg.setCallTimeoutMs(80);
        var limits = new AgentExecutionProperties(); limits.setMaxToolCalls(1);
        var entered = new CountDownLatch(1); var stopped = new CountDownLatch(1); var count = new AtomicInteger();
        try (var workers = blockingWorkers(new AgentExecutionLimiter(limits), count, entered, stopped);
             var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry)) {
            var future = executor.execute(RAG); assertThat(entered.await(1, TimeUnit.SECONDS)).isTrue();
            assertThat(future.get(2, TimeUnit.SECONDS)).containsEntry("error_code", "TOOL_TIMEOUT");
            assertThat(stopped.await(1, TimeUnit.SECONDS)).isTrue(); assertThat(count.get()).isEqualTo(1);
            assertThat(executor.execute(RAG).get(1, TimeUnit.SECONDS)).containsEntry("status", "SUCCESS");
        }
    }

    @Test
    void aWorkerIgnoringInterruptKeepsItsPermitUntilItActuallyExitsAndIsNotRetried() throws Exception {
        var cfg = settings(); cfg.setCallTimeoutMs(80);
        var limits = new AgentExecutionProperties(); limits.setMaxToolCalls(1); limits.setToolAcquireTimeoutMs(20);
        var entered = new CountDownLatch(1); var release = new CountDownLatch(1); var exited = new CountDownLatch(1);
        var calls = new AtomicInteger();
        try (var workers = new VirtualThreadAgentToolUseExecutor(runtime,
                (VirtualThreadAgentToolUseExecutor.TriFunction<String, String, Map<String, Object>, Map<String, Object>>) (id, agent, args) -> {
                    if (calls.incrementAndGet() == 1) {
                        entered.countDown();
                        try { while (true) { try { release.await(); break; } catch (InterruptedException ignored) { } } }
                        finally { exited.countDown(); }
                    }
                    return Map.of("status", "SUCCESS");
                }, new InMemoryAgentToolResultStore(), new AgentExecutionLimiter(limits));
             var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry)) {
            try {
                var first = executor.execute(RAG); assertThat(entered.await(1, TimeUnit.SECONDS)).isTrue();
                assertThat(first.get(2, TimeUnit.SECONDS)).containsEntry("error_code", "TOOL_TIMEOUT");
                assertThat(executor.execute(RAG).get(1, TimeUnit.SECONDS)).containsEntry("error_code", "TOOL_CAPACITY");
                assertThat(calls.get()).isEqualTo(1);
            } finally { release.countDown(); }
            assertThat(exited.await(1, TimeUnit.SECONDS)).isTrue();
            assertThat(executor.execute(RAG).get(1, TimeUnit.SECONDS)).containsEntry("status", "SUCCESS");
        } finally { release.countDown(); }
    }

    @Test
    void callerCancellationPropagatesToTheWorkerAndDoesNotTripTheDependency() throws Exception {
        var cfg = settings(); var limits = new AgentExecutionProperties(); limits.setMaxToolCalls(1);
        var entered = new CountDownLatch(1); var stopped = new CountDownLatch(1); var count = new AtomicInteger();
        try (var workers = blockingWorkers(new AgentExecutionLimiter(limits), count, entered, stopped);
             var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry);
             var turn = executor.openTurn(new AgentInterruptContext("cancel", "session"))) {
            var future = turn.execute(RAG); assertThat(entered.await(1, TimeUnit.SECONDS)).isTrue(); future.cancel(true);
            assertThat(stopped.await(1, TimeUnit.SECONDS)).isTrue();
            assertThat(future.isCancelled()).isTrue();
            assertThat(governance(turn.execute(RAG).get(1, TimeUnit.SECONDS))).containsEntry("circuit_state", "CLOSED");
        }
    }

    @Test
    void turnDeadlineAlsoStopsAWaitingModel() {
        var cfg = settings(); cfg.setTurnTimeoutMs(150);
        ChatModel model = new ChatModel() {
            @Override public ChatResponse call(Prompt prompt) { throw new AssertionError(); }
            @Override public Flux<ChatResponse> stream(Prompt prompt) { return Flux.never(); }
        };
        try (var executor = new GovernedAgentToolUseExecutor(event -> { throw new AssertionError("No tools expected"); }, cfg, runtime, registry)) {
            var loop = new RsAgentLoop(runtime, executor, new SpringAiAgentModelStreamClient(model, runtime));
            var events = new ArrayList<AgentStreamEventVO>();
            var result = loop.run(new com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO("session", "profile", "需求", 1, Map.of()), events::add);
            assertThat(result.finishReason()).isEqualTo(AgentFinishReason.INTERRUPTED);
            assertThat(events).anySatisfy(event -> { assertThat(event.event()).isEqualTo("interrupted"); assertThat(event.data()).containsEntry("reason", "turn_timeout"); });
        }
    }

    @Test
    void circuitIsSharedBetweenTurnsAndOnlyOneRecoveryProbeRuns() throws Exception {
        var clock = new AtomicLong(); var count = new AtomicInteger(); var cfg = settings(); cfg.setMaxAttempts(1);
        var breaker = new AgentToolCircuitBreaker(2, 10, clock::get);
        var probe = new CountDownLatch(1); var release = new CountDownLatch(1);
        try (var workers = new VirtualThreadAgentToolUseExecutor(event -> {
            int call = count.incrementAndGet(); if (call <= 2) throw new AgentToolDependencyException(503);
            if (call == 3) { probe.countDown(); try { release.await(); } catch (InterruptedException failure) { Thread.currentThread().interrupt(); throw new CancellationException(); } }
            return Map.of("status", "SUCCESS");
        }); var executor = new GovernedAgentToolUseExecutor(workers, cfg, runtime, registry, breaker)) {
            executor.execute(RAG).join(); executor.execute(RAG).join();
            assertThat(executor.execute(RAG).join()).containsEntry("error_code", "TOOL_CIRCUIT_OPEN");
            assertThat(count.get()).isEqualTo(2); clock.addAndGet(10_000_000);
            var active = executor.execute(RAG); assertThat(probe.await(1, TimeUnit.SECONDS)).isTrue();
            assertThat(executor.execute(RAG).join()).containsEntry("error_code", "TOOL_CIRCUIT_OPEN");
            release.countDown(); assertThat(active.get(1, TimeUnit.SECONDS)).containsEntry("status", "SUCCESS");
            assertThat(breaker.state("rag")).isEqualTo("CLOSED");
        } finally { release.countDown(); }
    }

    private VirtualThreadAgentToolUseExecutor blockingWorkers(AgentExecutionLimiter limiter, AtomicInteger count, CountDownLatch entered, CountDownLatch stopped) {
        return new VirtualThreadAgentToolUseExecutor(runtime,
                (VirtualThreadAgentToolUseExecutor.TriFunction<String, String, Map<String, Object>, Map<String, Object>>) (id, agent, args) -> {
                    if (count.incrementAndGet() == 1) {
                        entered.countDown(); try { new CountDownLatch(1).await(); }
                        catch (InterruptedException interrupted) { stopped.countDown(); Thread.currentThread().interrupt(); throw new CancellationException(); }
                    }
                    return Map.of("status", "SUCCESS");
                }, new InMemoryAgentToolResultStore(), limiter);
    }
    private static AgentToolGovernanceProperties settings() { var cfg = new AgentToolGovernanceProperties(); cfg.setRetryDelayMs(0); return cfg; }
    @SuppressWarnings("unchecked") private static Map<String, Object> governance(Map<String, Object> result) { return (Map<String, Object>) result.get("governance"); }
}
