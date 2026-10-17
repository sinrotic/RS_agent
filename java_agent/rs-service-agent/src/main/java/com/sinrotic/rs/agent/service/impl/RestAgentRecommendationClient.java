package com.sinrotic.rs.agent.service.impl;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.domain.vo.AgentRecommendedItemVO;
import com.sinrotic.rs.agent.service.AgentRecommendationClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

import java.util.List;
import java.util.Map;

@Service
public class RestAgentRecommendationClient implements AgentRecommendationClient {

    private final RestClient restClient;

    public RestAgentRecommendationClient(
            RestClient.Builder restClientBuilder,
            @Value("${rs.recommend.base-url:http://rs-service-recommend:18103}") String recommendBaseUrl
    ) {
        this.restClient = restClientBuilder.baseUrl(recommendBaseUrl).build();
    }

    @Override
    public List<AgentRecommendedItemVO> recommend(AgentChatRequestDTO request) {
        try {
            HomeRecommendResponse response = restClient.post()
                    .uri("/api/recommend/home")
                    .body(Map.of(
                            "session_id", request.sessionId(),
                            "scene", "agent_chat",
                            "page_size", request.resolvedLimit(),
                            "cursor", "",
                            "debug", false
                    ))
                    .retrieve()
                    .body(HomeRecommendResponse.class);
            if (response == null || response.items() == null) {
                return List.of();
            }
            return response.items().stream()
                    .limit(request.resolvedLimit())
                    .map(item -> new AgentRecommendedItemVO(
                            item.itemId(),
                            item.display() == null ? item.itemId() : valueOrFallback(item.display().title(), item.itemId()),
                            item.display() == null ? "" : valueOrFallback(item.display().category(), ""),
                            item.score(),
                            valueOrFallback(item.reason(), "")
                    ))
                    .toList();
        } catch (RestClientException ignored) {
            return List.of();
        }
    }

    private static String valueOrFallback(String value, String fallback) {
        return value == null || value.isBlank() ? fallback : value;
    }

    private record HomeRecommendResponse(List<HomeRecommendItem> items) {
    }

    private record HomeRecommendItem(
            @JsonProperty("item_id") String itemId,
            double score,
            String reason,
            Display display
    ) {
    }

    private record Display(String title, String category) {
    }
}
