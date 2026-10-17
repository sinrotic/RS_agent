package com.sinrotic.rs.agent.service.impl;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

public class AgentInterruptContext {

    private final String requestId;

    private final String sessionId;

    private final String profileUserId;

    private final String accountId;

    private final AtomicBoolean interrupted = new AtomicBoolean(false);

    private final AtomicReference<String> reason = new AtomicReference<>("");

    private final List<Runnable> callbacks = new CopyOnWriteArrayList<>();

    public AgentInterruptContext(String requestId, String sessionId) {
        this(requestId, sessionId, "");
    }

    public AgentInterruptContext(String requestId, String sessionId, String profileUserId) {
        this(requestId, sessionId, "", profileUserId);
    }

    public AgentInterruptContext(String requestId, String sessionId, String accountId, String profileUserId) {
        this.requestId = requestId;
        this.sessionId = sessionId;
        this.accountId = accountId == null ? "" : accountId;
        this.profileUserId = profileUserId == null ? "" : profileUserId;
    }

    public String accountId() { return accountId; }

    public String requestId() {
        return requestId;
    }

    public String sessionId() {
        return sessionId;
    }

    public String profileUserId() {
        return profileUserId;
    }

    public boolean interrupted() {
        return interrupted.get();
    }

    public String reason() {
        return reason.get();
    }

    public void onInterrupt(Runnable callback) {
        if (interrupted()) {
            callback.run();
            return;
        }
        callbacks.add(callback);
        if (interrupted() && callbacks.remove(callback)) {
            callback.run();
        }
    }

    public boolean interrupt(String reason) {
        String resolvedReason = reason == null || reason.isBlank() ? "interrupted" : reason;
        this.reason.compareAndSet("", resolvedReason);
        if (!interrupted.compareAndSet(false, true)) {
            return false;
        }
        for (Runnable callback : callbacks) {
            callback.run();
        }
        callbacks.clear();
        return true;
    }
}
