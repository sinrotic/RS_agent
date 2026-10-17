package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import org.springframework.stereotype.Service;

import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.CancellationException;
import java.util.function.BooleanSupplier;

@Service
public class AgentExecutionLimiter {

    private final Semaphore activeLoopPermits;

    private final Semaphore modelStreamPermits;

    private final Semaphore toolCallPermits;

    private final Semaphore recommendationPermits;

    private final long activeLoopAcquireTimeoutMs;

    private final long modelStreamAcquireTimeoutMs;

    private final long toolAcquireTimeoutMs;

    private final long recommendationAcquireTimeoutMs;

    public AgentExecutionLimiter(AgentExecutionProperties properties) {
        this.activeLoopPermits = new Semaphore(positive(properties.getMaxActiveLoops()), true);
        this.modelStreamPermits = new Semaphore(positive(properties.getMaxModelStreams()), true);
        this.toolCallPermits = new Semaphore(positive(properties.getMaxToolCalls()), true);
        this.recommendationPermits = new Semaphore(positive(properties.getMaxRecommendationCalls()), true);
        this.activeLoopAcquireTimeoutMs = nonNegative(properties.getActiveLoopAcquireTimeoutMs());
        this.modelStreamAcquireTimeoutMs = nonNegative(properties.getModelStreamAcquireTimeoutMs());
        this.toolAcquireTimeoutMs = nonNegative(properties.getToolAcquireTimeoutMs());
        this.recommendationAcquireTimeoutMs = nonNegative(properties.getRecommendationAcquireTimeoutMs());
    }

    public void runWithActiveLoop(AgentExecutionAction action) {
        callWithActiveLoop(() -> {
            action.run();
            return null;
        });
    }

    public <T> T callWithActiveLoop(AgentExecutionTask<T> task) {
        return withPermit(activeLoopPermits, activeLoopAcquireTimeoutMs, "active agent loop", task);
    }

    public void runWithModelStream(AgentExecutionAction action) {
        callWithModelStream(() -> {
            action.run();
            return null;
        });
    }

    public <T> T callWithModelStream(AgentExecutionTask<T> task) {
        return withPermit(modelStreamPermits, modelStreamAcquireTimeoutMs, "model stream", task);
    }

    public void runWithModelStream(AgentExecutionAction action, BooleanSupplier cancelled) {
        withPermit(modelStreamPermits, modelStreamAcquireTimeoutMs, "model stream", () -> {
            action.run();
            return null;
        }, cancelled);
    }

    public <T> T callWithRecommendationPermit(AgentExecutionTask<T> task) {
        return withPermit(recommendationPermits, recommendationAcquireTimeoutMs, "recommendation pipeline", task);
    }

    public void runWithToolPermit(AgentExecutionAction action) {
        callWithToolPermit(() -> {
            action.run();
            return null;
        });
    }

    public <T> T callWithToolPermit(AgentExecutionTask<T> task) {
        return withPermit(toolCallPermits, toolAcquireTimeoutMs, "tool call", task);
    }

    private <T> T withPermit(
            Semaphore semaphore,
            long timeoutMs,
            String resourceName,
            AgentExecutionTask<T> task
    ) {
        return withPermit(semaphore, timeoutMs, resourceName, task, null);
    }

    private <T> T withPermit(
            Semaphore semaphore,
            long timeoutMs,
            String resourceName,
            AgentExecutionTask<T> task,
            BooleanSupplier cancelled
    ) {
        boolean acquired;
        try {
            if (cancelled == null) {
                acquired = semaphore.tryAcquire(timeoutMs, TimeUnit.MILLISECONDS);
            } else {
                long started = System.nanoTime();
                long budget = TimeUnit.MILLISECONDS.toNanos(timeoutMs);
                while (true) {
                    checkCancelled(cancelled);
                    long remaining = budget - (System.nanoTime() - started);
                    // 定时获取仍遵守公平信号量的等待顺序，同时及时观察 Turn 中断。
                    acquired = semaphore.tryAcquire(Math.max(0, Math.min(remaining,
                            TimeUnit.MILLISECONDS.toNanos(25))), TimeUnit.NANOSECONDS);
                    if (acquired || remaining <= 0) break;
                }
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new AgentBusyException("interrupted while waiting for " + resourceName + " permit", error);
        }
        if (!acquired) {
            throw new AgentBusyException("agent service busy waiting for " + resourceName + " permit");
        }
        try {
            checkCancelled(cancelled);
            return task.call();
        } catch (RuntimeException error) {
            throw error;
        } catch (Exception error) {
            throw new IllegalStateException(error);
        } finally {
            semaphore.release();
        }
    }

    private static void checkCancelled(BooleanSupplier cancelled) {
        if (cancelled != null && cancelled.getAsBoolean()) {
            throw new CancellationException("agent turn interrupted while waiting for model capacity");
        }
    }

    private static int positive(int value) {
        return Math.max(1, value);
    }

    private static long nonNegative(long value) {
        return Math.max(0, value);
    }

    @FunctionalInterface
    public interface AgentExecutionTask<T> {

        T call() throws Exception;
    }

    @FunctionalInterface
    public interface AgentExecutionAction {

        void run() throws Exception;
    }
}
