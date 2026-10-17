package com.sinrotic.rs.platformtrace.service;

import com.sinrotic.rs.platformtrace.config.PlatformTraceClientProperties;
import com.sinrotic.rs.platformtrace.service.client.HttpPlatformTraceDownstreamClient;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class HttpPlatformTraceDownstreamClientTest {
    @Test
    void agentTraceCarriesReadOnlyRoleAndDownstreamFailureIsNotAnEmptyHistory() {
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var client = new HttpPlatformTraceDownstreamClient(builder, new PlatformTraceClientProperties());
        server.expect(requestTo("http://rs-service-agent:18104/api/platform/agent/session/turns"))
                .andExpect(header("X-User-Roles", "OBSERVER"))
                .andRespond(withSuccess("{\"session_id\":\"session\",\"turns\":[{\"request_id\":\"request\",\"user_message\":\"hello\",\"assistant_message\":\"answer\",\"tool_calls\":[{\"tool_name\":\"recommend_candidates\",\"status\":\"SUCCESS\"}],\"recommended_item_ids\":[\"REAL-A\"]}]}", MediaType.APPLICATION_JSON));
        assertEquals(java.util.List.of("recommend_candidates"), client.fetchAgentSessionTrace("session")
                .orElseThrow().turns().getFirst().toolCalls());
        server.verify();
        server.reset();
        server.expect(anything()).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        assertThrows(RuntimeException.class, () -> client.fetchAgentSessionTrace("session"));
    }
}
