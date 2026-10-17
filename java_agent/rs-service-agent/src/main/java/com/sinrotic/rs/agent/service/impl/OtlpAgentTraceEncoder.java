package com.sinrotic.rs.agent.service.impl;

import com.sinrotic.rs.agent.config.AgentTraceReporterProperties;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.*;
import java.util.function.Function;

/** OTLP/HTTP JSON 元数据投影；不序列化外部正文、错误文本或任意 data 字段。 */
public final class OtlpAgentTraceEncoder implements Function<AgentTraceEventVO, Optional<Object>> {
    private final byte[] identityKey;
    private final String serviceName, modelName;
    private final Map<String, Instant> starts = new LinkedHashMap<>(128, .75f, true) {
        protected boolean removeEldestEntry(Map.Entry<String, Instant> eldest) { return size() > 1024; }
    };

    public OtlpAgentTraceEncoder(AgentTraceReporterProperties.Otlp config) {
        if (config.getIdentityKey() == null || config.getIdentityKey().length() < 16)
            throw new IllegalArgumentException("OTLP identity-key 至少需要 16 个字符");
        identityKey = config.getIdentityKey().getBytes(StandardCharsets.UTF_8);
        if (config.getServiceName() == null || config.getServiceName().isBlank())
            throw new IllegalArgumentException("OTLP service-name 不能为空");
        serviceName = config.getServiceName();
        modelName = config.getModelName();
    }

    @Override
    public synchronized Optional<Object> apply(AgentTraceEventVO event) {
        String traceId = id("trace", List.of(safe(event.sessionId()), event.requestId()), 32);
        String root = id("turn", List.of(traceId), 16);
        String type = safe(event.eventType());
        String modelId = safe(event.data().get("model_call_id"));
        String toolId = safe(event.toolCallId());
        String spanId = switch (type) {
            case "model_call_started", "model_call_completed" -> id("model", List.of(traceId, modelId), 16);
            case "tool_use", "tool_result" -> id("tool", List.of(traceId, toolId), 16);
            default -> root;
        };
        if (Set.of("agent_started", "model_call_started", "tool_use").contains(type)) {
            if (type.equals("model_call_started") && modelId.isBlank() || type.equals("tool_use") && toolId.isBlank())
                return Optional.empty();
            starts.merge(spanId, event.createdAt(), (old, next) -> old.isBefore(next) ? old : next);
            return Optional.empty();
        }
        boolean model = type.equals("model_call_completed"), tool = type.equals("tool_result");
        if (!model && !tool && !type.equals("agent_done")) return Optional.empty();
        if (model && modelId.isBlank() || tool && toolId.isBlank()) return Optional.empty();
        Instant start = starts.get(spanId);
        boolean durationKnown = start != null;
        if (event.latencyMs() != null && event.latencyMs() >= 0) {
            try { start = event.createdAt().minusMillis(event.latencyMs()); durationKnown = true; }
            catch (RuntimeException badTimestamp) { durationKnown = false; }
        }
        if (start == null || start.isAfter(event.createdAt())) { start = event.createdAt(); durationKnown = false; }
        if (start.isBefore(Instant.EPOCH) || event.createdAt().isBefore(Instant.EPOCH)) return Optional.empty();
        var attributes = new ArrayList<Map<String, Object>>();
        attribute(attributes, "langfuse.observation.type", model ? "generation" : tool ? "tool" : "agent");
        attribute(attributes, "langfuse.session.id", id("session", List.of(safe(event.sessionId())), 32));
        attribute(attributes, "rs.duration.known", durationKnown);
        String status = safe(event.data().getOrDefault("status", event.status())).toLowerCase(Locale.ROOT);
        if (tool && event.data().get("metadata") instanceof Map<?, ?> metadata)
            status = safe(metadata.get("status")).toLowerCase(Locale.ROOT);
        boolean error = Set.of("error", "failed", "timeout").contains(status);
        if (Set.of("completed", "answer_emitted", "hook_stopped", "interrupted", "error", "failed", "timeout", "success").contains(status))
            attribute(attributes, "rs.status", status);
        if (model) {
            boolean finalized = Boolean.TRUE.equals(event.data().get("usage_final"));
            attribute(attributes, "rs.usage.final", finalized);
            if (modelName != null && !modelName.isBlank()) attribute(attributes, "gen_ai.request.model", modelName);
            if (event.data().get("usage") instanceof Map<?, ?> usage) {
                for (String key : List.of("prompt_tokens", "completion_tokens", "total_tokens", "cache_read_input_tokens", "cache_write_input_tokens")) {
                    Object value = usage.get(key);
                    if (!(value instanceof Integer || value instanceof Long) || ((Number) value).longValue() < 0) continue;
                    attribute(attributes, "rs.usage.observed." + key, value);
                    if (finalized && key.equals("prompt_tokens")) attribute(attributes, "gen_ai.usage.input_tokens", value);
                    if (finalized && key.equals("completion_tokens")) attribute(attributes, "gen_ai.usage.output_tokens", value);
                }
            }
            for (String key : List.of("prompt_sha256", "tools_sha256", "skills_sha256")) {
                Object value = event.data().get(key);
                if (value instanceof String text && text.matches("[a-f0-9]{64}")) attribute(attributes, "rs.version." + key, text);
            }
        }
        var span = new LinkedHashMap<String, Object>();
        span.put("traceId", traceId); span.put("spanId", spanId);
        if (!spanId.equals(root)) span.put("parentSpanId", root);
        span.put("name", model ? "agent.model" : tool ? "agent.tool" : "agent.turn");
        span.put("kind", model ? 3 : 1);
        span.put("startTimeUnixNano", nanos(start)); span.put("endTimeUnixNano", nanos(event.createdAt()));
        span.put("attributes", attributes); span.put("status", Map.of("code", error ? 2 : 0));
        return Optional.of(Map.of("resourceSpans", List.of(Map.of(
                "resource", Map.of("attributes", List.of(Map.of("key", "service.name", "value", Map.of("stringValue", serviceName)))),
                "scopeSpans", List.of(Map.of("scope", Map.of("name", "rs-agent-metadata", "version", "1"), "spans", List.of(span)))))));
    }

    private String id(String domain, List<String> values, int length) {
        try {
            var mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(identityKey, "HmacSHA256"));
            var input = new StringBuilder(domain);
            values.forEach(value -> input.append(':').append(value.length()).append(':').append(value));
            return HexFormat.of().formatHex(mac.doFinal(input.toString().getBytes(StandardCharsets.UTF_8))).substring(0, length);
        } catch (java.security.GeneralSecurityException unavailable) { throw new IllegalStateException("HMAC unavailable"); }
    }
    private static String safe(Object value) { return value instanceof String text ? text : ""; }
    private static String nanos(Instant instant) {
        return BigInteger.valueOf(instant.getEpochSecond()).multiply(BigInteger.valueOf(1_000_000_000L))
                .add(BigInteger.valueOf(instant.getNano())).toString();
    }
    private static void attribute(List<Map<String, Object>> rows, String key, Object value) {
        Map<String, Object> encoded = value instanceof Boolean ? Map.of("boolValue", value)
                : value instanceof Number ? Map.of("intValue", value.toString()) : Map.of("stringValue", value);
        rows.add(Map.of("key", key, "value", encoded));
    }
}
