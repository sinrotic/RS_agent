package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class AgentExecutionLimiterTest {

    @Test
    void recommendationPermitIsIndependentAndReleasedAfterFailure() {
        var properties = properties(1, 1, 1);
        properties.setMaxRecommendationCalls(1);
        properties.setRecommendationAcquireTimeoutMs(10);
        var limiter = new AgentExecutionLimiter(properties);
        assertThat(limiter.callWithModelStream(() -> limiter.callWithRecommendationPermit(() -> "independent")))
                .isEqualTo("independent");
        assertThatThrownBy(() -> limiter.callWithRecommendationPermit(() -> {
            throw new IllegalStateException("recommendation failed");
        })).isInstanceOf(IllegalStateException.class);
        assertThat(limiter.callWithRecommendationPermit(() -> "released")).isEqualTo("released");
    }

    @Test
    void activeLoopPermitIsReleasedAfterSuccessfulCall() {
        AgentExecutionLimiter limiter = new AgentExecutionLimiter(properties(1, 1, 1));

        assertThat(limiter.callWithActiveLoop(() -> "first")).isEqualTo("first");
        assertThat(limiter.callWithActiveLoop(() -> "second")).isEqualTo("second");
    }

    @Test
    void activeLoopPermitIsReleasedAfterFailedCall() {
        AgentExecutionLimiter limiter = new AgentExecutionLimiter(properties(1, 1, 1));

        assertThatThrownBy(() -> limiter.callWithActiveLoop(() -> {
            throw new IllegalStateException("boom");
        })).isInstanceOf(IllegalStateException.class);

        assertThat(limiter.callWithActiveLoop(() -> "after-failure")).isEqualTo("after-failure");
    }

    @Test
    void activeLoopReturnsBusyWhenPermitCannotBeAcquiredBeforeTimeout() throws Exception {
        AgentExecutionLimiter limiter = new AgentExecutionLimiter(properties(1, 1, 1));
        CountDownLatch entered = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);

        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            CompletableFuture<Void> running = CompletableFuture.runAsync(() -> limiter.runWithActiveLoop(() -> {
                entered.countDown();
                await(release);
            }), executor);
            assertThat(entered.await(1, TimeUnit.SECONDS)).isTrue();

            assertThatThrownBy(() -> limiter.callWithActiveLoop(() -> "queued"))
                    .isInstanceOf(AgentBusyException.class)
                    .hasMessageContaining("active agent loop");

            release.countDown();
            running.join();
        }
    }

    @Test
    void modelAndToolPermitsUseIndependentLimits() {
        AgentExecutionLimiter limiter = new AgentExecutionLimiter(properties(2, 1, 1));

        assertThat(limiter.callWithModelStream(() -> "model")).isEqualTo("model");
        assertThat(limiter.callWithToolPermit(() -> "tool")).isEqualTo("tool");
        assertThat(limiter.callWithActiveLoop(() -> "loop")).isEqualTo("loop");
    }

    private static AgentExecutionProperties properties(
            int maxActiveLoops,
            int maxModelStreams,
            int maxToolCalls
    ) {
        AgentExecutionProperties properties = new AgentExecutionProperties();
        properties.setMaxActiveLoops(maxActiveLoops);
        properties.setActiveLoopAcquireTimeoutMs(10);
        properties.setMaxModelStreams(maxModelStreams);
        properties.setModelStreamAcquireTimeoutMs(10);
        properties.setMaxToolCalls(maxToolCalls);
        properties.setToolAcquireTimeoutMs(10);
        return properties;
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
