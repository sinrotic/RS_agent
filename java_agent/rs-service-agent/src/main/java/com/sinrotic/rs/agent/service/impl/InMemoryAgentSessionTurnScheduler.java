package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentExecutionProperties;
import com.sinrotic.rs.agent.service.AgentBusyException;
import com.sinrotic.rs.agent.service.AgentSessionTurnScheduler;
import org.springframework.stereotype.Service;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

@Service
public class InMemoryAgentSessionTurnScheduler implements AgentSessionTurnScheduler {

    private final ConcurrentMap<String, SessionGate> sessions = new ConcurrentHashMap<>();

    private final int maxSessionQueueSize;

    private final long sessionQueueTimeoutMs;

    public InMemoryAgentSessionTurnScheduler(AgentExecutionProperties properties) {
        this.maxSessionQueueSize = Math.max(0, properties.getMaxSessionQueueSize());
        this.sessionQueueTimeoutMs = Math.max(0, properties.getSessionQueueTimeoutMs());
    }

    @Override
    public void runExclusive(String sessionId, AgentSessionTurnAction action) {
        callExclusive(sessionId, () -> {
            action.run();
            return null;
        });
    }

    @Override
    public <T> T callExclusive(String sessionId, AgentSessionTurnTask<T> task) {
        String resolvedSessionId = resolveSessionId(sessionId);
        int[] registeredCount = new int[1];
        SessionGate gate = sessions.compute(resolvedSessionId, (ignored, current) -> {
            SessionGate registered = current == null ? new SessionGate() : current;
            registeredCount[0] = registered.waitingAndRunning.incrementAndGet();
            return registered;
        });
        int queued = registeredCount[0];
        if (queued > maxSessionQueueSize + 1) {
            gate.waitingAndRunning.decrementAndGet();
            cleanup(resolvedSessionId, gate);
            throw new AgentBusyException("agent session queue is full");
        }

        boolean acquired = false;
        try {
            try {
                acquired = gate.permit.tryAcquire(sessionQueueTimeoutMs, TimeUnit.MILLISECONDS);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                throw new AgentBusyException("interrupted while waiting for session queue", error);
            }
            if (!acquired) {
                throw new AgentBusyException("agent service busy waiting for session queue");
            }
            return task.call();
        } catch (RuntimeException error) {
            throw error;
        } catch (Exception error) {
            throw new IllegalStateException(error);
        } finally {
            if (acquired) {
                gate.permit.release();
            }
            gate.waitingAndRunning.decrementAndGet();
            cleanup(resolvedSessionId, gate);
        }
    }

    private void cleanup(String sessionId, SessionGate gate) {
        sessions.computeIfPresent(sessionId, (ignored, current) ->
                current == gate && gate.waitingAndRunning.get() == 0 && gate.permit.availablePermits() == 1
                        ? null : current);
    }

    private static String resolveSessionId(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            return "__anonymous__";
        }
        return sessionId;
    }

    private static class SessionGate {

        private final Semaphore permit = new Semaphore(1, true);

        private final AtomicInteger waitingAndRunning = new AtomicInteger();
    }
}
