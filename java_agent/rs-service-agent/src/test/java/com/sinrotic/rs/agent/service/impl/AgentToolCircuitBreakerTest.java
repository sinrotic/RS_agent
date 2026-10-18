package com.sinrotic.rs.agent.service.impl;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.AtomicLong;
import static org.assertj.core.api.Assertions.*;

class AgentToolCircuitBreakerTest {
    @Test
    void oneProbeIsAdmittedAndStaleResultsCannotCloseOrReopenAnotherEpoch() {
        var clock = new AtomicLong();
        var breaker = new AgentToolCircuitBreaker(1, 10, clock::get);
        var failed = breaker.acquire("rag"); var old = breaker.acquire("rag");
        breaker.complete(failed, AgentToolFailure.TRANSIENT_DEPENDENCY);
        breaker.complete(old, AgentToolFailure.SUCCESS);
        assertThat(breaker.state("rag")).isEqualTo("OPEN");
        assertThat(breaker.acquire("rag")).isNull();
        assertThat(breaker.acquire("recommend")).isNotNull();
        clock.addAndGet(10_000_000);
        var probe = breaker.acquire("rag");
        assertThat(probe.probe()).isTrue();
        assertThat(breaker.acquire("rag")).isNull();
        breaker.complete(probe, AgentToolFailure.SUCCESS);
        breaker.complete(old, AgentToolFailure.TIMEOUT);
        assertThat(breaker.state("rag")).isEqualTo("CLOSED");
    }

    @Test
    void businessRejectionsDoNotTripTheCircuitAndCancelledProbeDoesNotReleaseTraffic() {
        var clock = new AtomicLong(); var breaker = new AgentToolCircuitBreaker(1, 10, clock::get);
        for (var outcome : new AgentToolFailure[]{AgentToolFailure.AUTHORIZATION, AgentToolFailure.INVALID_ARGUMENTS,
                AgentToolFailure.CAPACITY, AgentToolFailure.CANCELLED, AgentToolFailure.UNKNOWN})
            breaker.complete(breaker.acquire("rag"), outcome);
        assertThat(breaker.state("rag")).isEqualTo("CLOSED");
        breaker.complete(breaker.acquire("rag"), AgentToolFailure.TIMEOUT); clock.addAndGet(10_000_000);
        breaker.complete(breaker.acquire("rag"), AgentToolFailure.CANCELLED);
        assertThat(breaker.acquire("rag")).isNull();
    }
}
