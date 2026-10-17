package com.sinrotic.rs.agent.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sinrotic.rs.agent.domain.dto.AgentChatRequestDTO;
import com.sinrotic.rs.agent.service.impl.HttpAgentSessionAdmissionClient;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import static org.assertj.core.api.Assertions.*;

class HttpAgentSessionAdmissionClientTest {
    @Test
    void readingEndedHistoryVerifiesBothOwnersWithoutAdmissionOrActivityUpdate() throws Exception {
        var requests = new java.util.concurrent.atomic.AtomicInteger();
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/sessions/ended", exchange -> {
            requests.incrementAndGet();
            assertThat(exchange.getRequestMethod()).isEqualTo("GET");
            assertThat(exchange.getRequestHeaders().getFirst("X-Profile-User-Id")).isEqualTo("profile");
            byte[] response = "{\"sessionId\":\"ended\",\"accountId\":\"account\",\"profileUserId\":\"profile\",\"status\":\"ENDED\"}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response); exchange.close();
        });
        server.start();
        try {
            var client = new HttpAgentSessionAdmissionClient("http://127.0.0.1:" + server.getAddress().getPort());
            client.verifyOwner("account", "profile", "ended");
            assertThatThrownBy(() -> client.verifyOwner("other-account", "profile", "ended")).hasMessageContaining("404");
            assertThat(requests).hasValue(2);
        } finally { server.stop(0); }
    }

    @Test
    void admissionUsesTrustedAccountAndEncodedSessionAndFailsClosed() throws Exception {
        var body = new AtomicReference<String>();
        var path = new AtomicReference<String>();
        var status = new java.util.concurrent.atomic.AtomicInteger(200);
        var server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/internal/sessions/", exchange -> {
            path.set(exchange.getRequestURI().getRawPath());
            body.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            byte[] response = "{\"accepted\":true}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(status.get(), response.length);
            exchange.getResponseBody().write(response); exchange.close();
        });
        server.start();
        try {
            var client = new HttpAgentSessionAdmissionClient("http://127.0.0.1:" + server.getAddress().getPort());
            var request = new AgentChatRequestDTO("session space", "profile", "预算五百", 1, Map.of("authenticated_account_id", "account"));
            client.admit(request);
            assertThat(path.get()).isEqualTo("/internal/sessions/session%20space/admit");
            assertThat(new ObjectMapper().readTree(body.get()).path("account_id").asText()).isEqualTo("account");
            assertThat(body.get()).contains("预算五百", "profile");
            status.set(410); assertThatThrownBy(() -> client.admit(request)).hasMessageContaining("410");
            status.set(404); assertThatThrownBy(() -> client.admit(request)).hasMessageContaining("404");
            status.set(500); assertThatThrownBy(() -> client.admit(request)).hasMessageContaining("503");
            assertThatThrownBy(() -> client.admit(new AgentChatRequestDTO("session", "profile", "继续", 1, Map.of())))
                    .hasMessageContaining("404");
        } finally { server.stop(0); }
    }
}
