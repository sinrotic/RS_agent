package com.sinrotic.rs.agent.service.impl;

import java.util.HashMap;
import java.util.Map;
import java.util.function.LongSupplier;

/** 按受控依赖组隔离；epoch 防止旧周期迟到结果关闭新熔断器。 */
public final class AgentToolCircuitBreaker {
    private final int threshold;
    private final long openNanos;
    private final LongSupplier clock;
    private final Map<String, State> states = new HashMap<>();
    public AgentToolCircuitBreaker(int threshold, long openMs) { this(threshold, openMs, System::nanoTime); }
    public AgentToolCircuitBreaker(int threshold, long openMs, LongSupplier clock) {
        if (threshold < 1 || openMs < 1 || openMs > 3600000) throw new IllegalArgumentException("Invalid circuit settings");
        this.threshold = threshold; this.openNanos = openMs * 1_000_000; this.clock = clock;
    }
    public synchronized Permit acquire(String dependency) {
        if (!java.util.Set.of("recommend", "rag", "session", "internal").contains(dependency)) throw new IllegalArgumentException("Unknown dependency group");
        var state = states.computeIfAbsent(dependency, ignored -> new State());
        if (state.mode.equals("OPEN") && clock.getAsLong() - state.openedAt >= openNanos) { state.mode = "HALF_OPEN"; state.epoch++; return new Permit(dependency, state.epoch, true); }
        return state.mode.equals("CLOSED") ? new Permit(dependency, state.epoch, false) : null;
    }
    synchronized void complete(Permit permit, AgentToolFailure outcome) {
        var state = states.get(permit.dependency());
        if (permit.epoch() != state.epoch) return;
        if (permit.probe()) {
            if (outcome == AgentToolFailure.SUCCESS) { state.mode = "CLOSED"; state.failures = 0; state.epoch++; }
            else open(state); // 取消/拒绝也不能证明依赖恢复；不向其他探针放量。
        } else if (state.mode.equals("CLOSED")) {
            if (outcome == AgentToolFailure.SUCCESS) state.failures = 0;
            else if (outcome.infrastructure && ++state.failures >= threshold) open(state);
        }
    }
    public synchronized String state(String dependency) { var value = states.get(dependency); return value == null ? "CLOSED" : value.mode; }
    private void open(State state) { state.mode = "OPEN"; state.openedAt = clock.getAsLong(); state.epoch++; }
    public record Permit(String dependency, long epoch, boolean probe) { }
    private static final class State { String mode = "CLOSED"; int failures; long epoch, openedAt; }
}
