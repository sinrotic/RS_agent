package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import com.sinrotic.rs.agent.domain.AgentCapabilityDescriptor;
import com.sinrotic.rs.agent.domain.AgentCapabilityRequest;
import com.sinrotic.rs.agent.domain.AgentCapabilityResult;
import com.sinrotic.rs.agent.service.impl.AgentCapabilityToolUseExecutor;
import com.sinrotic.rs.agent.service.impl.AgentModelStreamEvent;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentCapabilityRegistry;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentRuntimeConfigurationService;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentToolResultStore;
import com.sinrotic.rs.agent.service.impl.StreamingAgentToolUseOrchestrator;
import com.sinrotic.rs.agent.service.impl.VirtualThreadAgentToolUseExecutor;
import org.junit.jupiter.api.Test;

import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Function;

import static org.assertj.core.api.Assertions.assertThat;

class CapabilityToolOrchestrationTest {

    @Test
    void capabilityCallsOverlapAndResultsKeepSubmissionOrder() throws Exception {
        CountDownLatch started = new CountDownLatch(2);
        CountDownLatch release = new CountDownLatch(1);
        var registry = new InMemoryAgentCapabilityRegistry();
        Function<AgentCapabilityRequest, AgentCapabilityResult> handler = request -> {
            started.countDown();
            await(release);
            return AgentCapabilityResult.success(request.capabilityId(),
                    Map.of("request_id", request.requestId(), "virtual", Thread.currentThread().isVirtual()));
        };
        registry.register(capability("recommend", handler));
        registry.register(capability("rag-explain", handler));
        try (var worker = new VirtualThreadAgentToolUseExecutor();
             var producer = Executors.newVirtualThreadPerTaskExecutor()) {
            var executor = new AgentCapabilityToolUseExecutor(worker, registry, new InMemoryAgentRuntimeConfigurationService());
            var run = new StreamingAgentToolUseOrchestrator(executor).start();
            var submitted = producer.submit(() -> {
                run.submit("first", AgentModelStreamEvent.toolUse("first", "recommend_candidates", Map.of()));
                run.submit("second", AgentModelStreamEvent.toolUse("second", "rag_support", Map.of()));
            });
            try {
                assertThat(started.await(2, TimeUnit.SECONDS)).as("两个独立能力工具都应在前一个完成前启动").isTrue();
            } finally {
                release.countDown();
            }
            submitted.get(2, TimeUnit.SECONDS);
            var results = run.awaitResults();
            assertThat(results).extracting(AgentToolUseResult::toolCallId).containsExactly("first", "second");
            for (var result : results) {
                assertThat(result.succeeded()).isTrue();
                assertThat(((Map<?, ?>) result.metadata().get("payload")).get("virtual")).isEqualTo(true);
            }
        }
    }

    @Test
    void serialCapabilityKeepsItsDependencyBarrier() throws Exception {
        CountDownLatch readStarted = new CountDownLatch(1);
        CountDownLatch serialStarted = new CountDownLatch(1);
        CountDownLatch laterStarted = new CountDownLatch(1);
        CountDownLatch releaseRead = new CountDownLatch(1);
        CountDownLatch releaseSerial = new CountDownLatch(1);
        var registry = new InMemoryAgentCapabilityRegistry();
        registry.register(capability("recommend", request -> {
            readStarted.countDown();
            await(releaseRead);
            return AgentCapabilityResult.success("recommend", Map.of());
        }));
        registry.register(capability("session-memory", request -> {
            serialStarted.countDown();
            await(releaseSerial);
            return AgentCapabilityResult.success("session-memory", Map.of());
        }));
        registry.register(capability("rag-explain", request -> {
            laterStarted.countDown();
            return AgentCapabilityResult.success("rag-explain", Map.of());
        }));
        try (var worker = new VirtualThreadAgentToolUseExecutor()) {
            var executor = new AgentCapabilityToolUseExecutor(worker, registry, new InMemoryAgentRuntimeConfigurationService());
            var run = new StreamingAgentToolUseOrchestrator(executor).start();
            run.submit("read", AgentModelStreamEvent.toolUse("recommend_candidates", Map.of()));
            run.submit("serial", AgentModelStreamEvent.toolUse("session_memory", Map.of()));
            run.submit("later", AgentModelStreamEvent.toolUse("rag_support", Map.of()));
            try {
                assertThat(readStarted.await(2, TimeUnit.SECONDS)).isTrue();
                assertThat(serialStarted.await(100, TimeUnit.MILLISECONDS)).isFalse();
                releaseRead.countDown();
                assertThat(serialStarted.await(2, TimeUnit.SECONDS)).isTrue();
                assertThat(laterStarted.await(100, TimeUnit.MILLISECONDS)).isFalse();
            } finally {
                releaseRead.countDown();
                releaseSerial.countDown();
            }
            assertThat(run.awaitResults()).extracting(AgentToolUseResult::toolCallId)
                    .containsExactly("read", "serial", "later");
            assertThat(laterStarted.getCount()).isZero();
        }
    }

    @Test
    void cancellationInterruptsAnExecutingCapability() throws Exception {
        CountDownLatch started = new CountDownLatch(1);
        CountDownLatch interrupted = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        var registry = new InMemoryAgentCapabilityRegistry();
        registry.register(capability("recommend", request -> {
            started.countDown();
            try {
                release.await();
            } catch (InterruptedException error) {
                interrupted.countDown();
                Thread.currentThread().interrupt();
            }
            return AgentCapabilityResult.success("recommend", Map.of());
        }));
        try (var worker = new VirtualThreadAgentToolUseExecutor()) {
            var executor = new AgentCapabilityToolUseExecutor(worker, registry, new InMemoryAgentRuntimeConfigurationService());
            var future = executor.execute(AgentModelStreamEvent.toolUse("recommend_candidates", Map.of()));
            try {
                assertThat(started.await(2, TimeUnit.SECONDS)).isTrue();
                future.cancel(true);
                assertThat(interrupted.await(2, TimeUnit.SECONDS)).isTrue();
            } finally {
                release.countDown();
            }
        }
    }

    @Test
    void capabilitiesShareTheExistingToolConcurrencyLimit() throws Exception {
        var properties = new AgentExecutionProperties();
        properties.setMaxToolCalls(1);
        properties.setToolAcquireTimeoutMs(2000);
        verifyRecommendationConcurrencyLimit(properties);
    }

    @Test
    void recommendationCapabilitiesShareThePipelineLimit() throws Exception {
        var properties = new AgentExecutionProperties();
        properties.setMaxToolCalls(2);
        properties.setMaxRecommendationCalls(1);
        properties.setRecommendationAcquireTimeoutMs(2000);
        verifyRecommendationConcurrencyLimit(properties);
    }

    private void verifyRecommendationConcurrencyLimit(AgentExecutionProperties properties) throws Exception {
        CountDownLatch firstStarted = new CountDownLatch(1);
        CountDownLatch bothStarted = new CountDownLatch(2);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger running = new AtomicInteger();
        AtomicInteger maximum = new AtomicInteger();
        var registry = new InMemoryAgentCapabilityRegistry();
        registry.register(capability("recommend", request -> {
            maximum.accumulateAndGet(running.incrementAndGet(), Math::max);
            firstStarted.countDown();
            bothStarted.countDown();
            try {
                await(release);
                return AgentCapabilityResult.success("recommend", Map.of());
            } finally {
                running.decrementAndGet();
            }
        }));
        var runtime = new InMemoryAgentRuntimeConfigurationService();
        try (var worker = new VirtualThreadAgentToolUseExecutor(runtime,
                (AgentDelegateService) (requestId, agentName, arguments) -> Map.of(), new InMemoryAgentToolResultStore(),
                new AgentExecutionLimiter(properties))) {
            var executor = new AgentCapabilityToolUseExecutor(worker, registry, runtime);
            var first = executor.execute(AgentModelStreamEvent.toolUse("recommend_candidates", Map.of()));
            var second = executor.execute(AgentModelStreamEvent.toolUse("recommend_candidates", Map.of()));
            try {
                assertThat(firstStarted.await(2, TimeUnit.SECONDS)).isTrue();
                assertThat(bothStarted.await(100, TimeUnit.MILLISECONDS)).isFalse();
            } finally {
                release.countDown();
            }
            assertThat(first.get(2, TimeUnit.SECONDS)).containsEntry("status", "SUCCESS");
            assertThat(second.get(2, TimeUnit.SECONDS)).containsEntry("status", "SUCCESS");
            assertThat(maximum.get()).isEqualTo(1);
        }
    }

    private static AgentCapability capability(String id, Function<AgentCapabilityRequest, AgentCapabilityResult> handler) {
        return new AgentCapability() {
            @Override
            public AgentCapabilityDescriptor descriptor() {
                return AgentCapabilityDefinitions.byId(id);
            }

            @Override
            public AgentCapabilityResult execute(AgentCapabilityRequest request) {
                return handler.apply(request);
            }
        };
    }

    private static void await(CountDownLatch latch) {
        try {
            latch.await();
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        }
    }
}
