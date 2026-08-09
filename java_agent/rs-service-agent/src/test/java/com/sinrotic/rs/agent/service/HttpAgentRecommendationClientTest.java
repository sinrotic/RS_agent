package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentRecommendationProperties;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.HttpAgentRecommendationClient;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class HttpAgentRecommendationClientTest {

    @Test
    void mapsAgentRequestAndCandidateResponseWithoutLeakingRawFields() {
        CapturingHttpClient httpClient = new CapturingHttpClient("""
                {"request_id":"req-1","candidates":[
                  {"item_id":"B001","title":"Backpack","category_path":"Bags",
                   "price":99.9,"rating_summary":"4.8","short_text":"light",
                   "reason_hint":"commute match"}
                ]}
                """);
        AgentRecommendationProperties properties = new AgentRecommendationProperties();
        properties.setBaseUrl("http://recommend");
        properties.setSemanticRecallPath("/agent/recommend/semantic-recall");

        var result = new HttpAgentRecommendationClient(properties, httpClient)
                .recommend(new AgentChatRequestDTO(
                        "session-1", "user-1", "find a backpack", 3,
                        Map.of("scene", "agent_chat", "constraints", Map.of("price_max", 200))
                ));

        assertThat(httpClient.url).isEqualTo("http://recommend/agent/recommend/semantic-recall");
        assertThat(httpClient.payload).contains("\"profile_user_id\":\"user-1\"")
                .contains("\"query\":\"find a backpack\"")
                .contains("\"return_count\":3")
                .contains("\"price_max\":200");
        assertThat(result).singleElement().satisfies(item -> {
            assertThat(item.itemId()).isEqualTo("B001");
            assertThat(item.category()).isEqualTo("Bags");
            assertThat(item.reason()).isEqualTo("commute match");
            assertThat(item.score()).isZero();
        });
    }

    @Test
    void usesCandidatesEndpointWhenTheRequestHasNoQuery() {
        CapturingHttpClient httpClient = new CapturingHttpClient("{\"candidates\":[]}");
        AgentRecommendationProperties properties = new AgentRecommendationProperties();
        properties.setBaseUrl("http://recommend");
        properties.setCandidatesPath("/agent/recommend/candidates");

        new HttpAgentRecommendationClient(properties, httpClient)
                .recommend(new AgentChatRequestDTO("session-1", "user-1", " ", 2, Map.of()));

        assertThat(httpClient.url).isEqualTo("http://recommend/agent/recommend/candidates");
        assertThat(httpClient.payload).contains("\"limit\":2")
                .doesNotContain("\"query\"");
    }

    @Test
    void hidesDownstreamFailureDetailsBehindStableMessage() {
        AgentRecommendationProperties properties = new AgentRecommendationProperties();
        AgentModelProviderHttpClient failingClient = (url, payload, accept) -> {
            throw new IllegalStateException("HTTP 503 with internal response");
        };

        assertThatThrownBy(() -> new HttpAgentRecommendationClient(properties, failingClient)
                .recommend(new AgentChatRequestDTO("session-1", "user-1", "", 1, Map.of())))
                .isInstanceOf(IllegalStateException.class)
                .hasMessage("recommendation service unavailable");
    }

    private static final class CapturingHttpClient implements AgentModelProviderHttpClient {
        private final String response;
        private String url;
        private String payload;

        private CapturingHttpClient(String response) {
            this.response = response;
        }

        @Override
        public String postJson(String url, String payload, String accept) {
            this.url = url;
            this.payload = payload;
            return response;
        }
    }
}
