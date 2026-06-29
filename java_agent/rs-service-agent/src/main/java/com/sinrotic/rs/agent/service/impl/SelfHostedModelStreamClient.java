package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentModelProviderProperties;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.AgentModelProviderHttpClient;
import com.sinrotic.rs.agent.service.AgentModelStreamClient;

import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

public class SelfHostedModelStreamClient implements AgentModelStreamClient {

    private final AgentModelProviderProperties properties;

    private final AgentModelProviderHttpClient httpClient;

    private final ObjectMapper objectMapper = new ObjectMapper();

    public SelfHostedModelStreamClient(
            AgentModelProviderProperties properties,
            AgentModelProviderHttpClient httpClient
    ) {
        this.properties = properties;
        this.httpClient = httpClient;
    }

    @Override
    public void streamAssistantEvents(
            String requestId,
            AgentChatRequestDTO request,
            Consumer<AgentModelStreamEvent> consumer
    ) {
        Map<String, Object> payload = Map.of(
                "model_key", properties.selfHosted().getModelKey(),
                "request_id", requestId,
                "messages", List.of(Map.of("role", "user", "content", request.userMessage())),
                "context", request.resolvedContext(),
                "options", Map.of("stream", true)
        );
        httpClient.streamJson(
                joinUrl(properties.selfHosted().getBaseUrl(), properties.selfHosted().getStreamPath()),
                writeJson(payload),
                "text/event-stream",
                line -> parseSseLine(line, consumer)
        );
        consumer.accept(AgentModelStreamEvent.done());
    }

    private void parseSseLine(String line, Consumer<AgentModelStreamEvent> consumer) {
        String trimmed = line.trim();
        if (!trimmed.startsWith("data:")) {
            return;
        }
        String json = trimmed.substring("data:".length()).trim();
        if (json.isBlank()) {
            return;
        }
        AgentModelStreamEvent event = readEvent(json);
        if (!event.isDone()) {
            consumer.accept(event);
        }
    }

    private AgentModelStreamEvent readEvent(String json) {
        try {
            JsonNode root = objectMapper.readTree(json);
            JsonNode done = root.path("done");
            if (done.isBoolean() && done.asBoolean()) {
                return AgentModelStreamEvent.done();
            }
            String type = root.path("type").asText(root.path("event").asText("token"));
            if ("tool_use".equals(type)) {
                return AgentModelStreamEvent.toolUse(
                        root.path("tool_name").asText(root.path("name").asText("")),
                        readArguments(root.path("arguments"))
                );
            }
            return AgentModelStreamEvent.token(root.path("delta").asText(""));
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("self-hosted stream data is not valid JSON", ex);
        }
    }

    private Map<String, Object> readArguments(JsonNode arguments) {
        if (arguments == null || arguments.isMissingNode() || arguments.isNull()) {
            return Map.of();
        }
        return objectMapper.convertValue(arguments, new TypeReference<>() {
        });
    }

    private String writeJson(Object payload) {
        try {
            return objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("failed to serialize self-hosted model request", ex);
        }
    }

    private String joinUrl(String baseUrl, String path) {
        String normalizedBase = baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
        String normalizedPath = path.startsWith("/") ? path : "/" + path;
        return normalizedBase + normalizedPath;
    }
}
