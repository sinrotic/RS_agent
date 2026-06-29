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
        return get(agentClient, "/api/platform/agent/{sessionId}/turns", AgentSessionTraceVO.class, sessionId);
    }

    private <T> Optional<T> get(RestClient client, String uri, Class<T> responseType, String value) {
        if (value == null || value.isBlank()) {
            return Optional.empty();
        }
        try {
            return Optional.ofNullable(client.get()
                    .uri(uri, value)
                    .retrieve()
                    .body(responseType));
        } catch (RestClientException ex) {
            return Optional.empty();
        }
    }
}
