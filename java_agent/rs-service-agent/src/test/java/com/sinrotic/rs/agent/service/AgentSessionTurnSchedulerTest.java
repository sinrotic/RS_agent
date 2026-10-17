package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import com.sinrotic.rs.agent.service.impl.InMemoryAgentSessionTurnScheduler;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentSessionTurnSchedulerTest {

    @Test
    void sameSessionTurnsRunSerially() throws Exception {
        AgentSessionTurnScheduler scheduler = new InMemoryAgentSessionTurnScheduler(properties(1, 500));
        CountDownLatch firstEntered = new CountDownLatch(1);
        CountDownLatch releaseFirst = new CountDownLatch(1);
        AtomicBoolean secondStarted = new AtomicBoolean(false);

        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            CompletableFuture<Void> first = CompletableFuture.runAsync(() -> scheduler.runExclusive("sess_1", () -> {
                firstEntered.countDown();
                await(releaseFirst);
            }), executor);
            assertThat(firstEntered.await(1, TimeUnit.SECONDS)).isTrue();

            CompletableFuture<Void> second = CompletableFuture.runAsync(() -> scheduler.runExclusive("sess_1", () -> {
                secondStarted.set(true);
            }), executor);

            Thread.sleep(80);
            assertThat(secondStarted).isFalse();

            releaseFirst.countDown();
            first.join();
            second.join();
            assertThat(secondStarted).isTrue();
        }
    }

    @Test
    void differentSessionsCanRunConcurrently() {
        AgentSessionTurnScheduler scheduler = new InMemoryAgentSessionTurnScheduler(properties(1, 500));
        AtomicInteger running = new AtomicInteger();
        AtomicInteger maxRunning = new AtomicInteger();

        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            CompletableFuture<Void> first = CompletableFuture.runAsync(
                    () -> scheduler.runExclusive("sess_a", () -> trackRunning(running, maxRunning)),
                    executor
            );
            CompletableFuture<Void> second = CompletableFuture.runAsync(
                    () -> scheduler.runExclusive("sess_b", () -> trackRunning(running, maxRunning)),
                    executor
            );

            CompletableFuture.allOf(first, second).join();
        }

        assertThat(maxRunning.get()).isGreaterThanOrEqualTo(2);
    }

    @Test
    void sessionQueueLimitRejectsExcessTurns() throws Exception {
        AgentSessionTurnScheduler scheduler = new InMemoryAgentSessionTurnScheduler(properties(0, 10));
        CountDownLatch firstEntered = new CountDownLatch(1);
        CountDownLatch releaseFirst = new CountDownLatch(1);

        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            CompletableFuture<Void> first = CompletableFuture.runAsync(() -> scheduler.runExclusive("sess_busy", () -> {
                firstEntered.countDown();
                await(releaseFirst);
            }), executor);
            assertThat(firstEntered.await(1, TimeUnit.SECONDS)).isTrue();

            assertThatThrownBy(() -> scheduler.runExclusive("sess_busy", () -> {
            })).isInstanceOf(AgentBusyException.class)
                    .hasMessageContaining("session queue");

            releaseFirst.countDown();
            first.join();
        }
    }

    private static AgentExecutionProperties properties(int maxSessionQueueSize, long sessionQueueTimeoutMs) {
        AgentExecutionProperties properties = new AgentExecutionProperties();
        properties.setMaxSessionQueueSize(maxSessionQueueSize);
        properties.setSessionQueueTimeoutMs(sessionQueueTimeoutMs);
        return properties;
    }

    private static void trackRunning(AtomicInteger running, AtomicInteger maxRunning) {
        int current = running.incrementAndGet();
        maxRunning.accumulateAndGet(current, Math::max);
        try {
            Thread.sleep(120);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        } finally {
            running.decrementAndGet();
        }
    }

    private static void await(CountDownLatch latch) {
        try {
            if (!latch.await(1, TimeUnit.SECONDS)) {
                throw new IllegalStateException("timed out waiting for latch");
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        }
    }
}
