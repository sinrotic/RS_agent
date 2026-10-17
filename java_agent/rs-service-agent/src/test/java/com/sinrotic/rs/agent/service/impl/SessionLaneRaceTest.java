package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import org.junit.jupiter.api.Test;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.assertj.core.api.Assertions.assertThat;

class SessionLaneRaceTest {
    @Test
    void gateCleanupCannotCreateASecondExecutionLaneForAnArrivingTurn() throws Exception {
        var properties = new AgentExecutionProperties(); properties.setSessionQueueTimeoutMs(3000);
        var scheduler = new InMemoryAgentSessionTurnScheduler(properties);
        var ownerRunning = new CountDownLatch(1); var finishOwner = new CountDownLatch(1);
        var cleanupPaused = new CountDownLatch(1); var resumeCleanup = new CountDownLatch(1);
        var newcomerRunning = new CountDownLatch(1); var releaseNewcomer = new CountDownLatch(1);
        var active = new AtomicInteger(); var maximum = new AtomicInteger();
        try (var pool = Executors.newVirtualThreadPerTaskExecutor()) {
            var owner = pool.submit(() -> { Thread.currentThread().setName("old-owner"); scheduler.runExclusive("same", () -> {
                ownerRunning.countDown(); await(finishOwner);
            }); });
            assertThat(ownerRunning.await(2, TimeUnit.SECONDS)).isTrue();
            var sessionsField = InMemoryAgentSessionTurnScheduler.class.getDeclaredField("sessions"); sessionsField.setAccessible(true);
            var gate = ((Map<?, ?>) sessionsField.get(scheduler)).get("same");
            var permitField = gate.getClass().getDeclaredField("permit"); permitField.setAccessible(true);
            permitField.set(gate, new Semaphore(0, true) {
                @Override public int availablePermits() {
                    int available = super.availablePermits();
                    if (Thread.currentThread().getName().equals("old-owner")) { cleanupPaused.countDown(); await(resumeCleanup); }
                    return available;
                }
            });
            finishOwner.countDown(); assertThat(cleanupPaused.await(2, TimeUnit.SECONDS)).isTrue();
            var second = pool.submit(() -> scheduler.runExclusive("same", () -> {
                maximum.accumulateAndGet(active.incrementAndGet(), Math::max);
                newcomerRunning.countDown(); await(releaseNewcomer); active.decrementAndGet();
            }));
            newcomerRunning.await(200, TimeUnit.MILLISECONDS);
            resumeCleanup.countDown(); owner.get(2, TimeUnit.SECONDS);
            assertThat(newcomerRunning.await(2, TimeUnit.SECONDS)).isTrue();
            var third = pool.submit(() -> scheduler.runExclusive("same", () -> {
                maximum.accumulateAndGet(active.incrementAndGet(), Math::max); active.decrementAndGet();
            }));
            try { third.get(100, TimeUnit.MILLISECONDS); } catch (TimeoutException expectedQueue) { }
            releaseNewcomer.countDown(); second.get(2, TimeUnit.SECONDS); third.get(2, TimeUnit.SECONDS);
            assertThat(maximum).hasValue(1);
        } finally { finishOwner.countDown(); resumeCleanup.countDown(); releaseNewcomer.countDown(); }
    }
    private static void await(CountDownLatch latch) {
        try { if (!latch.await(4, TimeUnit.SECONDS)) throw new AssertionError("latch timeout"); }
        catch (InterruptedException failure) { Thread.currentThread().interrupt(); throw new AssertionError(failure); }
    }
}
