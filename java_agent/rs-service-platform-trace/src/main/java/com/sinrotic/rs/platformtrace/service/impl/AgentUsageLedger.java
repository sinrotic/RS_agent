package com.sinrotic.rs.platformtrace.service.impl;

import com.sinrotic.rs.platformtrace.domain.vo.AgentRunEventVO;
import java.util.*;

/** 仅最终调用快照参与总量；历史事件、冲突与不完整调用保持显式未知。 */
final class AgentUsageLedger {
    private static final List<String> FIELDS = List.of("prompt_tokens", "completion_tokens", "total_tokens",
            "cache_read_input_tokens", "cache_write_input_tokens");

    static Result summarize(List<AgentRunEventVO> events) {
        Map<List<String>, Call> calls = new LinkedHashMap<>();
        Set<List<String>> canonicalRuns = new HashSet<>(), legacyRuns = new HashSet<>();
        for (var event : events) {
            var run = List.of(event.sessionId(), event.requestId());
            if (!Set.of("model_call_started", "model_call_completed").contains(event.eventType())) continue;
            canonicalRuns.add(run);
            Object id = event.data().get("model_call_id");
            boolean invalidId = !(id instanceof String text) || text.isBlank();
            String callId = invalidId ? "invalid:" + event.eventId() : id.toString();
            var call = calls.computeIfAbsent(List.of(event.sessionId(), event.requestId(), callId), ignored -> new Call());
            if (invalidId) call.conflict = true;
            if (!event.eventType().equals("model_call_completed")) continue;
            var usage = new LinkedHashMap<String, Long>();
            boolean malformed = false;
            if (event.data().get("usage") instanceof Map<?, ?> raw) {
                for (var field : FIELDS) {
                    Object value = raw.get(field);
                    if (value == null) continue;
                    if ((value instanceof Integer || value instanceof Long) && ((Number) value).longValue() >= 0)
                        usage.put(field, ((Number) value).longValue());
                    else malformed = true;
                }
            } else malformed = true;
            var snapshot = List.of(usage, event.data().getOrDefault("usage_final", false),
                    event.data().getOrDefault("status", "unknown"));
            if (call.snapshot != null && !call.snapshot.equals(snapshot)) call.conflict = true;
            call.snapshot = snapshot;
            call.usage = usage;
            call.finalized = Boolean.TRUE.equals(event.data().get("usage_final"));
            call.conflict |= malformed;
        }
        for (var event : events) {
            var run = List.of(event.sessionId(), event.requestId());
            if (!canonicalRuns.contains(run) && (event.promptTokens() != null || event.completionTokens() != null
                    || event.totalTokens() != null || event.eventType().equals("model_usage"))) legacyRuns.add(run);
        }
        Map<String, Object> fields = new LinkedHashMap<>();
        Map<String, Integer> totals = new HashMap<>();
        for (var field : FIELDS) {
            long subtotal = 0;
            int observed = 0, finalized = 0;
            boolean overflow = false;
            for (var call : calls.values()) {
                if (call.conflict || !call.usage.containsKey(field)) continue;
                observed++;
                if (call.finalized) finalized++;
                try { subtotal = Math.addExact(subtotal, call.usage.get(field)); }
                catch (ArithmeticException error) { overflow = true; }
            }
            boolean complete = !calls.isEmpty() && finalized == calls.size() && legacyRuns.isEmpty() && !overflow;
            var row = new LinkedHashMap<String, Object>();
            row.put("known_subtotal", observed > 0 && !overflow ? subtotal : null);
            row.put("observed_calls", observed);
            row.put("finalized_calls", finalized);
            row.put("total", complete ? subtotal : null);
            fields.put(field, Collections.unmodifiableMap(row));
            totals.put(field, complete && subtotal <= Integer.MAX_VALUE ? (int) subtotal : null);
        }
        String mode = !canonicalRuns.isEmpty() ? legacyRuns.isEmpty() ? "canonical" : "mixed"
                : legacyRuns.isEmpty() ? "not_observed" : "legacy_unverified";
        Map<String, Object> coverage = Map.of("mode", mode, "model_calls", calls.size(),
                "completed_observations", calls.values().stream().filter(call -> call.snapshot != null).count(),
                "conflicting_observations", calls.values().stream().filter(call -> call.conflict).count(),
                "legacy_runs", legacyRuns.size(), "fields", fields,
                "basis", "observed_generation_client_invocations_only");
        return new Result(totals.get("prompt_tokens"), totals.get("completion_tokens"), totals.get("total_tokens"), coverage);
    }

    record Result(Integer promptTokens, Integer completionTokens, Integer totalTokens, Map<String, Object> coverage) { }
    private static final class Call {
        Map<String, Long> usage = Map.of();
        List<Object> snapshot;
        boolean finalized, conflict;
    }
}
