package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.config.AgentDelegateProperties;
import com.sinrotic.rs.agent.service.AgentDelegateService;
import com.sinrotic.rs.agent.service.AgentModelProviderHttpClient;

import java.util.LinkedHashMap;
import java.util.Map;

public class HttpAgentDelegateService implements AgentDelegateService {

    private final AgentDelegateProperties properties;

    private final AgentModelProviderHttpClient httpClient;

    private final ObjectMapper objectMapper = new ObjectMapper();

    public HttpAgentDelegateService(
            AgentDelegateProperties properties,
            AgentModelProviderHttpClient httpClient
    ) {
        this.properties = properties;
        this.httpClient = httpClient;
    }

    @Override
    public Map<String, Object> callAgent(String requestId, String agentName, Map<String, Object> arguments) {
        if (!"rag_agent".equals(agentName)) {
            throw new IllegalArgumentException("unknown agent: " + agentName);
        }
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("request_id", requestId);
        payload.put("session_id", arguments.get("session_id"));
        payload.put("user_query", valueOrDefault(arguments.get("query"), arguments.get("task")));
        payload.put("candidate_item_ids", arguments.getOrDefault("candidate_item_ids", java.util.List.of()));
        payload.put("stage", arguments.get("stage"));
        payload.put("top_k", arguments.get("top_k"));
        payload.put("rerank_top_k", arguments.get("rerank_top_k"));
        payload.put("providers", arguments.get("providers"));
        payload.put("small2big", arguments.get("small2big"));
        payload.put("max_support_per_item", arguments.get("max_support_per_item"));
        payload.put("max_text_chars", arguments.get("max_text_chars"));

        try {
            String response = httpClient.postJson(
                    properties.ragAgent().getBaseUrl() + properties.ragAgent().getSupportPath(),
                    objectMapper.writeValueAsString(payload),
                    "application/json"
            );
            return objectMapper.readValue(response, new TypeReference<>() {
            });
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("failed to call rag agent", ex);
        }
    }

    private Object valueOrDefault(Object value, Object fallback) {
        if (value instanceof String text && !text.isBlank()) {
            return text;
        }
        return fallback;
    }
}
