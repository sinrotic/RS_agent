package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentReasoningProperties;
import java.math.BigDecimal;
import java.util.*;

/** 单 Turn 账本。预留/结算共用一把锁，未知用量保留额度；已关闭仍接受迟到的最终回执。 */
public final class AgentTurnBudget implements AutoCloseable {
    private final long maxTokens;
    private final int maxCalls;
    private final BigDecimal maxUsd, inputRate, outputRate;
    private final String pricedModel;
    private final List<Reservation> calls = new ArrayList<>();
    private boolean closed, conflict;

    public AgentTurnBudget(AgentReasoningProperties settings) {
        maxTokens = settings.getMaxTokens(); maxCalls = settings.getMaxModelCalls(); maxUsd = settings.getMaxUsd();
        inputRate = settings.isPricingConfigured() ? settings.getInputUsdPerMillion() : null;
        outputRate = settings.isPricingConfigured() ? settings.getOutputUsdPerMillion() : null; pricedModel = settings.getPricedModel();
        if (maxUsd.signum() > 0 && (inputRate == null || outputRate == null || pricedModel.isBlank()))
            throw new IllegalArgumentException("Fee budget requires explicit model and both rates");
    }

    public synchronized Reservation reserve(String model, String kind, long input, long output) {
        if (closed) throw new AgentModelBudgetException("MODEL_BUDGET_CLOSED");
        if (input < 0 || output < 1 || input > 10000000 || output > 131072) throw new AgentModelBudgetException("MODEL_BUDGET_INVALID_ESTIMATE");
        if (maxUsd.signum() > 0 && !pricedModel.equals(model)) throw new AgentModelBudgetException("MODEL_PRICE_UNKNOWN");
        boolean priced = !pricedModel.isBlank() && pricedModel.equals(model) && inputRate != null && outputRate != null;
        BigDecimal cost = priced ? cost(input, output) : null;
        if (conflict || calls.size() >= maxCalls || usedTokens() + input + output > maxTokens
                || maxUsd.signum() > 0 && usedCost().add(cost).compareTo(maxUsd) > 0)
            throw new AgentModelBudgetException("MODEL_BUDGET_EXHAUSTED");
        var call = new Reservation(calls.size() + 1, kind, input, output, cost); calls.add(call); return call;
    }

    private BigDecimal cost(long input, long output) {
        return inputRate.multiply(BigDecimal.valueOf(input)).add(outputRate.multiply(BigDecimal.valueOf(output))).movePointLeft(6);
    }
    private long usedTokens() { return calls.stream().mapToLong(c -> c.input + c.output).sum(); }
    private BigDecimal usedCost() { return calls.stream().map(c -> c.cost == null ? BigDecimal.ZERO : c.cost).reduce(BigDecimal.ZERO, BigDecimal::add); }
    private boolean breached() { return conflict || usedTokens() > maxTokens || maxUsd.signum() > 0 && usedCost().compareTo(maxUsd) > 0; }

    public synchronized Map<String, Object> snapshot() {
        long settled = calls.stream().filter(c -> c.finalUsage).mapToLong(c -> c.input + c.output).sum();
        long held = usedTokens() - settled;
        var data = new LinkedHashMap<String, Object>();
        data.put("max_tokens", maxTokens); data.put("settled_tokens", settled); data.put("held_tokens", held);
        data.put("used_or_held_tokens", settled + held); data.put("remaining_tokens", Math.max(0, maxTokens - settled - held));
        data.put("calls", calls.size()); data.put("unknown_usage_calls", calls.stream().filter(c -> c.finished && !c.finalUsage).count());
        data.put("max_calls",maxCalls); data.put("remaining_calls",Math.max(0,maxCalls-calls.size()));
        data.put("in_flight_calls", calls.stream().filter(c -> !c.finished).count());
        data.put("closed", closed); data.put("breached", breached()); data.put("receipt_conflict", conflict);
        data.put("cost_basis", "configured_rate_estimate_not_provider_invoice"); data.put("currency", "USD");
        data.put("input_estimate_basis", "prepared_utf8_bytes_plus_padding_not_tokenizer_count");
        boolean allPriced = calls.stream().allMatch(c -> c.cost != null) && inputRate != null && outputRate != null && !pricedModel.isBlank();
        data.put("pricing_status", allPriced ? "configured" : "unknown");
        if (allPriced) {
            data.put("used_or_held_usd", usedCost());
            data.put("settled_usd", calls.stream().filter(c -> c.finalUsage).map(c -> c.cost).reduce(BigDecimal.ZERO, BigDecimal::add));
        }
        data.put("max_usd", maxUsd); data.put("fee_limit_enabled", maxUsd.signum() > 0);
        data.put("by_kind", calls.stream().map(c -> c.kind).distinct().sorted().collect(java.util.stream.Collectors.toMap(k -> k,
                k -> Map.of("calls", calls.stream().filter(c -> c.kind.equals(k)).count(),
                        "used_or_held_tokens", calls.stream().filter(c -> c.kind.equals(k)).mapToLong(c -> c.input + c.output).sum()), (a,b) -> a, LinkedHashMap::new)));
        return Collections.unmodifiableMap(data);
    }
    @Override public synchronized void close() { closed = true; }

    public final class Reservation {
        private final int id;
        private final String kind;
        private long input, output;
        private BigDecimal cost;
        private boolean finalUsage, finished;
        private Reservation(int id, String kind, long input, long output, BigDecimal cost) {
            this.id = id; this.kind = kind; this.input = input; this.output = output; this.cost = cost;
        }
        public String id() { return "budget_" + id; }
        public void settle(Map<String, Object> usage, boolean finalReceipt) {
            synchronized (AgentTurnBudget.this) {
                Long actualInput = count(usage.get("prompt_tokens")), actualOutput = count(usage.get("completion_tokens"));
                Long total = count(usage.get("total_tokens"));
                boolean valid = actualInput != null && actualOutput != null
                        && (!usage.containsKey("total_tokens") || total != null && total == actualInput + actualOutput);
                if (finalUsage) {
                    if (finalReceipt && (!valid || input != actualInput || output != actualOutput)) conflict = true;
                    return;
                }
                finished = true;
                if (finalReceipt && valid) { input = actualInput; output = actualOutput; finalUsage = true; }
                else {
                    // 有可信部分用量但没有最终回执时，只能增加保守占用，不能退款。
                    if (actualInput != null) input = Math.max(input, actualInput);
                    if (actualOutput != null) output = Math.max(output, actualOutput);
                }
                if (cost != null) cost = AgentTurnBudget.this.cost(input, output);
            }
        }
    }
    private static Long count(Object value) {
        if (value instanceof Byte || value instanceof Short || value instanceof Integer || value instanceof Long) {
            long count = ((Number)value).longValue(); return count >= 0 && count <= 1000000000 ? count : null;
        }
        return null;
    }
}
