package com.sinrotic.rs.agent.service;

import com.sinrotic.rs.agent.config.AgentDelegateProperties;
import com.sinrotic.rs.agent.service.impl.HttpAgentDelegateService;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class HttpAgentDelegateServiceTest {

    @Test
    void ragAgentDelegatePostsToRecommendRagSupportByDefault() {
        AgentDelegateProperties properties = new AgentDelegateProperties();
        AtomicReference<String> calledUrl = new AtomicReference<>();
        AtomicReference<String> calledPayload = new AtomicReference<>();
        AgentModelProviderHttpClient httpClient = new AgentModelProviderHttpClient() {
            @Override
            public String postJson(String url, String payload, String accept) {
                calledUrl.set(url);
                calledPayload.set(payload);
                return """
                        {"request_id":"agent_req_001","query_rewrite":"bluetooth earbuds","candidate_scoped":true,"providers":[],"item_support":[],"comparison_points":[],"agent_context":{"instruction":"ok","public_payload_allowed":false},"governance":{"candidate_generation_allowed":false,"ranking_input_replacement_allowed":false,"promotion_allowed":false,"public_payload_allowed":false}}
                        """;
            }

            @Override
            public void streamJson(String url, String payload, String accept, java.util.function.Consumer<String> lineConsumer) {
            }
        };
        HttpAgentDelegateService service = new HttpAgentDelegateService(properties, httpClient);

        Map<String, Object> result = service.callAgent("", "rag_agent", Map.of(
                "session_id", "sess_001",
                "task", "bluetooth earbuds",
                "candidate_item_ids", List.of("B001")
        ));

        assertThat(calledUrl.get()).isEqualTo("http://rs-service-recommend:18103/agent/recommend/rag/support");
        assertThat(calledPayload.get()).contains("\"user_query\":\"bluetooth earbuds\"");
        assertThat(result).containsEntry("request_id", "agent_req_001");
    }
}
