package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentReasoningProperties;
import java.util.Map;

/** 请求准备后的执行门禁，不能使用会吞掉异常的观测回调代替。 */
final class AgentBudgetCall implements AutoCloseable {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final AgentTurnBudget.Reservation reservation;
    private final AgentInterruptContext context;
    private Map<String, Object> usage = Map.of();
    private boolean complete, explicitFinal, closed;
    final int outputLimit;
    static AgentBudgetCall open(AgentInterruptContext context, AgentReasoningProperties settings, String model,
            Object preparedInput, int requestedOutput) {
        if (context == null || context.budget() == null) return new AgentBudgetCall(null, context, requestedOutput);
        int output = Math.min(settings.getMaxOutputTokens(), requestedOutput > 0 ? requestedOutput : settings.getMaxOutputTokens());
        long estimate;
        try { estimate = (long) JSON.writeValueAsBytes(preparedInput).length + settings.getInputPaddingTokens(); }
        catch (Exception invalid) { throw new AgentModelBudgetException("MODEL_BUDGET_INPUT_UNAVAILABLE"); }
        if (context.interrupted()) throw new AgentModelBudgetException("MODEL_BUDGET_CANCELLED");
        var reservation = context.budget().reserve(model, context.callKind(), estimate, output);
        return new AgentBudgetCall(reservation, context, output);
    }
    private AgentBudgetCall(AgentTurnBudget.Reservation reservation, AgentInterruptContext context, int output) {
        this.reservation = reservation; this.context = context; outputLimit = output;
    }
    boolean active() { return reservation != null; }
    void record(AgentModelStreamEvent event) {
        if (event.isUsage()) { usage = event.arguments(); explicitFinal = Boolean.TRUE.equals(usage.get("usage_final")); }
    }
    void transportCompleted() { complete = true; }
    @Override public void close() {
        if (closed) return; closed = true;
        if (reservation != null) {
            reservation.settle(usage, complete || explicitFinal);
            if (Boolean.TRUE.equals(context.budget().snapshot().get("breached"))) context.interrupt("model_budget_exceeded");
        }
    }
}
