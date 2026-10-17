package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentTraceReporterProperties;
import com.sinrotic.rs.agent.domain.vo.AgentTraceEventVO;
import com.sinrotic.rs.agent.service.impl.OtlpAgentTraceEncoder;
import org.junit.jupiter.api.Test;

import java.time.Instant;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;

class OtlpAgentTraceEncoderTest {
    private static final String SECRET = "private-body-session-credential";
    private final ObjectMapper json = new ObjectMapper();

    @Test
    void projectsOnlyAllowlistedMetadataWithStableHashedParentage() throws Exception {
        var config = config();
        var encoder = new OtlpAgentTraceEncoder(config);
        assertThat(encoder.apply(event("agent_started", "", Map.of(), 0))).isEmpty();
        assertThat(encoder.apply(event("model_call_started", "", Map.of("model_call_id", SECRET), 1))).isEmpty();
        var completed = event("model_call_completed", "", Map.of(
                "model_call_id", SECRET, "usage_final", true, "status", "completed",
                "usage", Map.of("prompt_tokens", 10, "completion_tokens", 5, "total_tokens", 15),
                "prompt", SECRET, "native_usage", Map.of("credential", SECRET),
                "prompt_sha256", "a".repeat(64), "tools_sha256", SECRET, "request_sha256", "b".repeat(64)), 3);
        var envelope = json.valueToTree(encoder.apply(completed).orElseThrow());
        var model = span(envelope);
        var root = span(json.valueToTree(encoder.apply(event("agent_done", "", Map.of(), 4)).orElseThrow()));
        assertThat(envelope.toString()).doesNotContain(SECRET, config.getIdentityKey(), "native_usage");
        assertThat(model.path("traceId").asText()).matches("[a-f0-9]{32}").isEqualTo(root.path("traceId").asText());
        assertThat(model.path("spanId").asText()).matches("[a-f0-9]{16}");
        assertThat(model.path("parentSpanId").asText()).isEqualTo(root.path("spanId").asText());
        assertThat(model.path("kind").asInt()).isEqualTo(3);
        assertThat(model.path("startTimeUnixNano").asText()).isEqualTo("1792281601000000000");
        assertThat(model.path("endTimeUnixNano").isTextual()).isTrue();
        assertThat(attribute(model, "gen_ai.usage.input_tokens").path("intValue").asText()).isEqualTo("10");
        assertThat(attribute(model, "rs.version.prompt_sha256").path("stringValue").asText()).isEqualTo("a".repeat(64));
        assertThat(attribute(model, "rs.version.tools_sha256").isMissingNode()).isTrue();
        assertThat(envelope.toString()).doesNotContain("request_sha256", "b".repeat(64));
        assertThat(span(json.valueToTree(encoder.apply(completed).orElseThrow()))).isEqualTo(model);
        var changedKey = config();
        changedKey.setIdentityKey("different-identity-key-for-test");
        assertThat(span(json.valueToTree(new OtlpAgentTraceEncoder(changedKey).apply(completed).orElseThrow()))
                .path("traceId")).isNotEqualTo(model.path("traceId"));
    }

    @Test
    void incompleteUsageIsNotExportedAsBillableUsageAndInvalidCountsAreIgnored() {
        var encoder = new OtlpAgentTraceEncoder(config());
        var model = span(json.valueToTree(encoder.apply(event("model_call_completed", "", Map.of(
                "model_call_id", "call", "usage_final", false, "status", "error",
                "usage", Map.of("prompt_tokens", 8, "completion_tokens", -1, "total_tokens", 2.5)), 3)).orElseThrow()));
        assertThat(attribute(model, "gen_ai.usage.input_tokens").isMissingNode()).isTrue();
        assertThat(attribute(model, "rs.usage.observed.prompt_tokens").path("intValue").asText()).isEqualTo("8");
        assertThat(attribute(model, "rs.usage.observed.completion_tokens").isMissingNode()).isTrue();
        assertThat(model.path("status").path("code").asInt()).isEqualTo(2);
        assertThat(attribute(model, "rs.duration.known").path("boolValue").asBoolean()).isFalse();
    }

    @Test
    void startCacheIsBoundedAndToolLatencyRemainsUsableWithoutCachedStart() {
        var encoder = new OtlpAgentTraceEncoder(config());
        encoder.apply(event("model_call_started", "", Map.of("model_call_id", "first"), 1));
        for (int i = 0; i < 1024; i++)
            encoder.apply(event("model_call_started", "", Map.of("model_call_id", "call-" + i), 1));
        var evicted = span(json.valueToTree(encoder.apply(event("model_call_completed", "", Map.of("model_call_id", "first"), 3)).orElseThrow()));
        assertThat(attribute(evicted, "rs.duration.known").path("boolValue").asBoolean()).isFalse();
        var toolEvent = new AgentTraceEventVO("event", SECRET, SECRET, "tool_result", "tool-id", SECRET,
                SECRET, SECRET, SECRET, 250L, Map.of("metadata", Map.of("status", "timeout")), Instant.parse("2026-10-18T00:00:03Z"));
        var tool = span(json.valueToTree(encoder.apply(toolEvent).orElseThrow()));
        assertThat(attribute(tool, "rs.duration.known").path("boolValue").asBoolean()).isTrue();
        assertThat(tool.path("startTimeUnixNano").asText()).isEqualTo("1792281602750000000");
        assertThat(tool.path("status").path("code").asInt()).isEqualTo(2);
    }

    static AgentTraceReporterProperties.Otlp config() {
        var config = new AgentTraceReporterProperties.Otlp();
        config.setIdentityKey("test-only-identity-key-32-characters");
        return config;
    }

    static AgentTraceEventVO event(String type, String toolId, Map<String, Object> data, int second) {
        return new AgentTraceEventVO(SECRET, SECRET, SECRET, type, toolId, SECRET, SECRET, SECRET, SECRET,
                null, data, Instant.parse("2026-10-18T00:00:00Z").plusSeconds(second));
    }

    static JsonNode span(JsonNode envelope) {
        return envelope.path("resourceSpans").get(0).path("scopeSpans").get(0).path("spans").get(0);
    }

    static JsonNode attribute(JsonNode span, String key) {
        for (var attr : span.path("attributes")) if (attr.path("key").asText().equals(key)) return attr.path("value");
        return com.fasterxml.jackson.databind.node.MissingNode.getInstance();
    }
}
