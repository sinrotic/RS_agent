package com.sinrotic.rs.platformtrace.service.client;

import com.sinrotic.rs.platformtrace.config.PlatformTraceClientProperties;
import com.sinrotic.rs.platformtrace.domain.vo.AgentSessionTraceVO;
import com.sinrotic.rs.platformtrace.domain.vo.PlatformAccountProfileVO;
import com.sinrotic.rs.platformtrace.domain.vo.RecommendTraceVO;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.Optional;

public class HttpPlatformTraceDownstreamClient implements PlatformTraceDownstreamClient {

    private final RestClient userClient;
    private final RestClient recommendClient;
    private final RestClient agentClient;

    public HttpPlatformTraceDownstreamClient(
            RestClient.Builder restClientBuilder,
            PlatformTraceClientProperties properties
    ) {
        this.userClient = restClientBuilder.clone().baseUrl(properties.getUserBaseUrl()).build();
        this.recommendClient = restClientBuilder.clone().baseUrl(properties.getRecommendBaseUrl()).build();
        this.agentClient = restClientBuilder.clone().baseUrl(properties.getAgentBaseUrl()).build();
    }

    @Override
    public Optional<PlatformAccountProfileVO> fetchAccountProfile(String accountId) {
        return get(userClient, "/api/platform/accounts/{accountId}/profile", PlatformAccountProfileVO.class, accountId);
    }

    @Override
    public Optional<RecommendTraceVO> fetchRecommendTrace(String requestId) {
        return get(recommendClient, "/api/platform/recommend/{requestId}/trace", RecommendTraceVO.class, requestId);
    }

    @Override
    public Optional<AgentSessionTraceVO> fetchAgentSessionTrace(String sessionId) {
        return get(agentClient, "/api/platform/agent/{sessionId}/turns", AgentWireTrace.class, sessionId)
                .map(AgentWireTrace::toView);
    }

    private record AgentWireTrace(
            @com.fasterxml.jackson.annotation.JsonProperty("session_id") String sessionId,
            java.util.List<AgentWireTurn> turns) {
        AgentSessionTraceVO toView() {
            return new AgentSessionTraceVO(sessionId,
                    turns == null ? java.util.List.of() : turns.stream().map(AgentWireTurn::toView).toList());
        }
    }

    private record AgentWireTurn(
            @com.fasterxml.jackson.annotation.JsonProperty("request_id") String requestId,
            @com.fasterxml.jackson.annotation.JsonProperty("user_message") String userMessage,
            @com.fasterxml.jackson.annotation.JsonProperty("assistant_message") String assistantMessage,
            @com.fasterxml.jackson.annotation.JsonProperty("tool_calls") java.util.List<Object> toolCalls,
            @com.fasterxml.jackson.annotation.JsonProperty("recommended_item_ids") java.util.List<String> itemIds) {
        com.sinrotic.rs.platformtrace.domain.vo.AgentTurnVO toView() {
            java.util.List<String> names = toolCalls == null ? java.util.List.of() : toolCalls.stream()
                    .map(tool -> tool instanceof java.util.Map<?, ?> map ? map.get("tool_name") : tool)
                    .filter(String.class::isInstance).map(String.class::cast).filter(name -> !name.isBlank()).toList();
            return new com.sinrotic.rs.platformtrace.domain.vo.AgentTurnVO(
                    requestId, userMessage, assistantMessage, names, itemIds);
        }
    }

    private <T> Optional<T> get(RestClient client, String uri, Class<T> responseType, String value) {
        if (value == null || value.isBlank()) {
            return Optional.empty();
        }
        try {
            return Optional.ofNullable(client.get()
                    .uri(uri, value)
                    .header("X-User-Roles", "OBSERVER")
                    .retrieve()
                    .body(responseType));
        } catch (RestClientException ex) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.BAD_GATEWAY, "Platform trace dependency is unavailable", ex);
        }
    }
}
